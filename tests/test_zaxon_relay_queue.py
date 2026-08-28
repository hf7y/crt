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


class TestValidateMessage(unittest.TestCase):
    """140 is inclusive (Zach 2026-08-25): the budget is the rendered
    message, not the question that goes inside it."""

    def _question_rendering_to(self, length):
        """A question whose RENDERED message is exactly `length` chars."""
        overhead = len(q.format_message("musc", "", None))
        return "x" * (length - overhead)

    def test_at_the_limit_is_accepted(self):
        text = q.validate_message("musc", self._question_rendering_to(q.MAX_QUESTION_CHARS))
        self.assertEqual(len(text), q.MAX_QUESTION_CHARS)

    def test_one_over_the_limit_raises(self):
        with self.assertRaises(ValueError):
            q.validate_message("musc", self._question_rendering_to(q.MAX_QUESTION_CHARS + 1))

    def test_options_count_against_the_budget(self):
        """The regression this fixes: a question that fits alone but whose
        rendered poll does not."""
        question = self._question_rendering_to(q.MAX_QUESTION_CHARS)
        q.validate_message("musc", question)  # fits with no options
        with self.assertRaises(ValueError):
            q.validate_message("musc", question, ["yes", "no"])

    def test_repo_tag_counts_against_the_budget(self):
        question = self._question_rendering_to(q.MAX_QUESTION_CHARS)
        with self.assertRaises(ValueError):
            q.validate_message("a-much-longer-repo-name", question)

    def test_does_not_truncate(self):
        long_q = "x" * (q.MAX_QUESTION_CHARS + 50)
        with self.assertRaises(ValueError) as ctx:
            q.validate_message("musc", long_q)
        self.assertIn(str(len(q.format_message("musc", long_q, None))), str(ctx.exception))

    def test_repo_must_be_a_repo(self):
        for bad in ("", "   ", "my repo", "agent"):
            with self.assertRaises(ValueError):
                q.validate_message(bad, "Coffee or tea?")


class TestFormatMessage(unittest.TestCase):
    def test_bold_repo_leads_and_nothing_decorates_it(self):
        text = q.format_message("musc", "Coffee or tea?", None)
        self.assertTrue(text.startswith("*musc* "), text)
        self.assertIn("Coffee or tea?", text)

    def test_no_ticket_id_and_no_brackets(self):
        """The watcher matches on the WhatsApp quote, never on the id text --
        so the id is screen spent on nobody."""
        text = q.format_message("musc", "Coffee or tea?", None)
        for junk in ("(#", "[", "]", "\U0001F500"):
            self.assertNotIn(junk, text)

    def test_options_render_as_numbered_poll(self):
        text = q.format_message("musc", "Pick one", ["Coffee", "Tea"])
        self.assertIn("1. Coffee", text)
        self.assertIn("2. Tea", text)


class TestEditDelivered(unittest.TestCase):
    """Editing the message already on his phone is the whole point: hermes's
    WhatsApp adapter has no edit_message, so every other path in the stack
    answers a change of mind with a SECOND notification."""

    def _delivered(self, conn):
        _insert(conn, "t1", "Q1", "queued")
        q.sweep_and_promote(
            conn, sender=lambda text: {"success": True, "message_id": "wa1"}
        )
        return conn

    def test_deliver_records_the_chat_id_the_edit_will_need(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = self._delivered(_fresh_conn(tmp))
            chat_id = conn.execute(
                "SELECT chat_id FROM tickets WHERE id='t1'"
            ).fetchone()[0]
            self.assertTrue(chat_id)

    def test_edits_the_delivered_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = self._delivered(_fresh_conn(tmp))
            calls = []

            def editor(chat_id, message_id, text):
                calls.append((chat_id, message_id, text))
                return {"success": True}

            q.edit_delivered(conn, "t1", "*musc* new question", editor=editor)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][1], "wa1")
            self.assertEqual(calls[0][2], "*musc* new question")

    def test_a_refused_edit_raises_and_never_sends_a_second_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = self._delivered(_fresh_conn(tmp))
            with self.assertRaises(RuntimeError):
                q.edit_delivered(
                    conn, "t1", "new",
                    editor=lambda *_: {"success": False, "error": "not connected"},
                )

    def test_queued_ticket_has_nothing_to_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = _fresh_conn(tmp)
            _insert(conn, "t1", "Q1", "queued")
            with self.assertRaises(ValueError):
                q.edit_delivered(conn, "t1", "new", editor=lambda *_: {"success": True})


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


class TestAdmissionControl(unittest.TestCase):
    """crt#96: the slot is a human, and it was allocated first-come with no
    reference to whether a caller had ever been worth answering."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.conn = _fresh_conn(self._tmp.name)

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def _asked(self, n, from_agent="loud", answered=0, created_at=None):
        for i in range(n):
            self.conn.execute(
                "INSERT INTO tickets (id, from_agent, question, status, created_at, answered_at) "
                "VALUES (?, ?, 'q', ?, ?, ?)",
                (f"{from_agent}{i}", from_agent,
                 "answered" if i < answered else "stale",
                 created_at or q._iso_now(),
                 q._iso_now() if i < answered else None),
            )
        self.conn.commit()

    def test_a_quiet_caller_is_admitted(self):
        self._asked(3)
        self.assertIsNone(q.admission_error(self.conn, "loud"))

    def test_a_caller_nobody_answers_is_refused_at_the_threshold(self):
        self._asked(q.ADMIT_MAX_UNANSWERED)
        self.assertIn("none", q.admission_error(self.conn, "loud"))

    def test_one_answer_readmits_a_loud_caller(self):
        self._asked(q.ADMIT_MAX_UNANSWERED + 20, answered=1)
        self.assertIsNone(q.admission_error(self.conn, "loud"))

    def test_the_window_rolls_so_a_refusal_expires_by_itself(self):
        old = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                            time.gmtime(time.time() - q.ADMIT_WINDOW_SECS - 60))
        self._asked(q.ADMIT_MAX_UNANSWERED + 5, created_at=old)
        self.assertIsNone(q.admission_error(self.conn, "loud"))

    def test_one_caller_starving_the_slot_does_not_refuse_another(self):
        self._asked(q.ADMIT_MAX_UNANSWERED + 5)
        self._asked(1, from_agent="quiet")
        self.assertIsNone(q.admission_error(self.conn, "quiet"))


class TestSlotReport(unittest.TestCase):
    """crt#89/#96: 'pending' read the same next-up and 18 hours deep, so a
    caller could not tell whether waiting was worth it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.conn = _fresh_conn(self._tmp.name)

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def test_the_ticket_on_the_phone_has_nothing_ahead_of_it(self):
        _insert(self.conn, "a", "q", "pending")
        self.assertEqual(q.slot_report(self.conn, "a")["queued_ahead"], 0)

    def test_a_queued_ticket_counts_the_slot_and_everything_older(self):
        _insert(self.conn, "a", "q", "pending", created_at="2026-08-28T00:00:00Z")
        _insert(self.conn, "b", "q", "queued", created_at="2026-08-28T00:01:00Z")
        _insert(self.conn, "c", "q", "queued", created_at="2026-08-28T00:02:00Z")
        self.assertEqual(q.slot_report(self.conn, "c")["queued_ahead"], 2)

    def test_the_wait_is_the_worst_case_every_one_ahead_expiring(self):
        _insert(self.conn, "a", "q", "pending", created_at="2026-08-28T00:00:00Z")
        _insert(self.conn, "b", "q", "queued", created_at="2026-08-28T00:01:00Z")
        r = q.slot_report(self.conn, "b")
        self.assertEqual(r["est_wait_hours"],
                         round(r["queued_ahead"] * q.QUESTION_TTL_SECS / 3600, 1))

    def test_an_unknown_ticket_reports_nothing_rather_than_zero(self):
        self.assertEqual(q.slot_report(self.conn, "nope"), {})
