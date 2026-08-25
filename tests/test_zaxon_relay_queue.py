#!/usr/bin/env python3
"""Tests for zaxon_relay_queue.py (crt#67): the single-slot question queue,
its staleness TTL, and the style guard. Loaded straight from relay/ the way
it ships (flat, mcp-free -- only zaxon_relay_server.py needs mcp)."""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

RELAY_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "provision", "dexter", "zaxon", "relay",
)
sys.path.insert(0, RELAY_DIR)

import zaxon_relay_db as db  # noqa: E402
import zaxon_relay_queue as q  # noqa: E402


def _fresh_conn(tmpdir):
    db.DB_PATH = Path(tmpdir) / "tickets.db"
    return db.get_conn()


def _insert(conn, ticket_id, question, status, created_at=None, options=None):
    import json
    conn.execute(
        "INSERT INTO tickets (id, from_agent, question, status, created_at, options) "
        "VALUES (?, 'agent', ?, ?, ?, ?)",
        (ticket_id, question, status, created_at or q._iso_now(),
         json.dumps(options) if options else None),
    )
    conn.commit()


class TestValidateQuestion(unittest.TestCase):
    def test_under_limit_ok(self):
        q.validate_question("short question")

    def test_at_or_over_limit_raises(self):
        with self.assertRaises(ValueError):
            q.validate_question("x" * q.MAX_QUESTION_CHARS)

    def test_does_not_truncate(self):
        """A caller over the limit gets an exception, not a silently shortened question."""
        long_q = "x" * (q.MAX_QUESTION_CHARS + 50)
        with self.assertRaises(ValueError) as ctx:
            q.validate_question(long_q)
        self.assertIn(str(len(long_q)), str(ctx.exception))


class TestFormatMessage(unittest.TestCase):
    def test_free_text_has_no_boilerplate_header(self):
        text = q.format_message("agent", "abc123", "Coffee or tea?", None)
        self.assertNotIn("Question 1 of", text)
        self.assertNotIn("---", text)
        self.assertIn("Coffee or tea?", text)
        self.assertIn("#abc123", text)

    def test_options_render_as_numbered_poll(self):
        text = q.format_message("agent", "abc123", "Pick one", ["Coffee", "Tea"])
        self.assertIn("1. Coffee", text)
        self.assertIn("2. Tea", text)


class TestSweepAndPromote(unittest.TestCase):
    def test_promotes_lone_queued_ticket_when_slot_is_free(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = _fresh_conn(tmp)
            _insert(conn, "t1", "Q1", "queued")
            sent = []
            q.sweep_and_promote(conn, sender=lambda text: sent.append(text) or {"success": True, "message_id": "wa1"})
            row = conn.execute("SELECT status, wa_message_id FROM tickets WHERE id='t1'").fetchone()
            self.assertEqual(row, ("pending", "wa1"))
            self.assertEqual(len(sent), 1)

    def test_second_queued_ticket_stays_queued_while_first_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = _fresh_conn(tmp)
            _insert(conn, "t1", "Q1", "pending")
            _insert(conn, "t2", "Q2", "queued")
            sent = []
            q.sweep_and_promote(conn, sender=lambda text: sent.append(text) or {"success": True})
            self.assertEqual(len(sent), 0)
            status = conn.execute("SELECT status FROM tickets WHERE id='t2'").fetchone()[0]
            self.assertEqual(status, "queued")

    def test_stale_pending_ticket_frees_slot_for_next_queued(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = _fresh_conn(tmp)
            old_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - q.QUESTION_TTL_SECS - 10))
            _insert(conn, "t1", "Q1", "pending", created_at=old_ts)
            _insert(conn, "t2", "Q2", "queued")
            sent = []
            q.sweep_and_promote(conn, sender=lambda text: sent.append(text) or {"success": True, "message_id": "wa2"})
            t1_status = conn.execute("SELECT status FROM tickets WHERE id='t1'").fetchone()[0]
            t2_status = conn.execute("SELECT status FROM tickets WHERE id='t2'").fetchone()[0]
            self.assertEqual(t1_status, "stale")
            self.assertEqual(t2_status, "pending")
            self.assertEqual(len(sent), 1)

    def test_fresh_pending_ticket_blocks_promotion(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = _fresh_conn(tmp)
            _insert(conn, "t1", "Q1", "pending")
            _insert(conn, "t2", "Q2", "queued")
            q.sweep_and_promote(conn, sender=lambda text: {"success": True})
            t1_status = conn.execute("SELECT status FROM tickets WHERE id='t1'").fetchone()[0]
            self.assertEqual(t1_status, "pending")

    def test_promoted_ticket_carries_its_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = _fresh_conn(tmp)
            _insert(conn, "t1", "Pick one", "queued", options=["A", "B"])
            sent = []
            q.sweep_and_promote(conn, sender=lambda text: sent.append(text) or {"success": True, "message_id": "wa1"})
            self.assertIn("1. A", sent[0])
            self.assertIn("2. B", sent[0])

    def test_send_failure_marks_ticket_failed_not_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = _fresh_conn(tmp)
            _insert(conn, "t1", "Q1", "queued")
            q.sweep_and_promote(conn, sender=lambda text: {"success": False, "error": "boom"})
            row = conn.execute("SELECT status, answer FROM tickets WHERE id='t1'").fetchone()
            self.assertEqual(row, ("failed", "boom"))

    def test_send_exception_marks_ticket_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = _fresh_conn(tmp)
            _insert(conn, "t1", "Q1", "queued")

            def _raise(text):
                raise RuntimeError("no network")

            q.sweep_and_promote(conn, sender=_raise)
            status = conn.execute("SELECT status FROM tickets WHERE id='t1'").fetchone()[0]
            self.assertEqual(status, "failed")

    def test_failed_ticket_does_not_block_next_queued(self):
        """A failed send frees the slot on the very next sweep, no stale-timeout wait."""
        with tempfile.TemporaryDirectory() as tmp:
            conn = _fresh_conn(tmp)
            _insert(conn, "t1", "Q1", "queued")
            _insert(conn, "t2", "Q2", "queued")
            responses = iter([{"success": False, "error": "boom"}, {"success": True, "message_id": "wa2"}])
            q.sweep_and_promote(conn, sender=lambda text: next(responses))
            q.sweep_and_promote(conn, sender=lambda text: next(responses))
            t2_status = conn.execute("SELECT status FROM tickets WHERE id='t2'").fetchone()[0]
            self.assertEqual(t2_status, "pending")

    def test_no_queued_tickets_is_a_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = _fresh_conn(tmp)
            _insert(conn, "t1", "Q1", "pending")
            q.sweep_and_promote(conn, sender=lambda text: {"success": True})
            status = conn.execute("SELECT status FROM tickets WHERE id='t1'").fetchone()[0]
            self.assertEqual(status, "pending")


class TestOptionsColumnMigration(unittest.TestCase):
    def test_get_conn_adds_options_column_to_pre_existing_db(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tickets.db"
            legacy = sqlite3.connect(str(path))  # pre-crt#67 schema, no options column
            legacy.execute(
                "CREATE TABLE tickets (id TEXT PRIMARY KEY, from_agent TEXT NOT NULL, "
                "question TEXT NOT NULL, wa_message_id TEXT, status TEXT NOT NULL "
                "DEFAULT 'pending', answer TEXT, created_at TEXT NOT NULL, answered_at TEXT)"
            )
            legacy.commit()
            legacy.close()

            db.DB_PATH = path
            conn = db.get_conn()
            cols = {row[1] for row in conn.execute("PRAGMA table_info(tickets)")}
            self.assertIn("options", cols)


if __name__ == "__main__":
    unittest.main()
