#!/usr/bin/env python3
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

RELAY_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "provision", "dexter", "zaxon", "relay",
)
sys.path.insert(0, RELAY_DIR)


class _FakeMCPServer:
    def __init__(self, *args, **kwargs):
        pass

    def tool(self):
        def deco(fn):
            return fn
        return deco

    def run(self, *args, **kwargs):
        raise AssertionError("mcp.run() should never be called from a test")


if "mcp" not in sys.modules:
    fake_mcp = types.ModuleType("mcp")
    fake_mcp_server = types.ModuleType("mcp.server")
    fake_mcpserver = types.ModuleType("mcp.server.mcpserver")
    fake_mcpserver.MCPServer = _FakeMCPServer
    fake_mcp_server.mcpserver = fake_mcpserver
    fake_mcp.server = fake_mcp_server
    sys.modules["mcp"] = fake_mcp
    sys.modules["mcp.server"] = fake_mcp_server
    sys.modules["mcp.server.mcpserver"] = fake_mcpserver

import zaxon_relay_db as db  # noqa: E402
import zaxon_relay_queue as queue  # noqa: E402
import zaxon_relay_server as server  # noqa: E402


class TestRefusals(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        db.DB_PATH = Path(self._tmpdir.name) / "tickets.db"

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_ask_zach_refuses_too_long_without_raising(self):
        result = server.ask_zach("x" * 200, "crt")
        self.assertEqual(result["status"], "refused")
        self.assertIn("140", result["error"])

    def test_ask_zach_refuses_bad_repo_without_raising(self):
        result = server.ask_zach("short", "apms postmortem")
        self.assertEqual(result["status"], "refused")
        self.assertIn("space", result["error"])

    def test_ask_zach_refusal_does_not_insert_a_ticket(self):
        server.ask_zach("x" * 200, "crt")
        conn = db.get_conn()
        try:
            count = conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(count, 0)

    def test_ask_zach_valid_input_still_returns_a_ticket(self):
        result = server.ask_zach("Coffee or tea?", "crt")
        self.assertIn("ticket_id", result)
        self.assertNotEqual(result["status"], "refused")

    def _insert_queued_bypassing_delivery(self, ticket_id, question, from_agent="crt"):
        conn = db.get_conn()
        try:
            conn.execute(
                "INSERT INTO tickets (id, from_agent, question, status, created_at) "
                "VALUES (?, ?, ?, 'queued', '2026-01-01T00:00:00Z')",
                (ticket_id, from_agent, question),
            )
            conn.commit()
        finally:
            conn.close()

    def test_revise_zach_question_refuses_too_long_without_raising(self):
        self._insert_queued_bypassing_delivery("t1", "Coffee or tea?")
        result = server.revise_zach_question("t1", "x" * 200)
        self.assertEqual(result["status"], "refused")
        self.assertIn("140", result["error"])

    def test_revise_zach_question_refusal_leaves_original_question(self):
        self._insert_queued_bypassing_delivery("t1", "Coffee or tea?")
        server.revise_zach_question("t1", "x" * 200)
        conn = db.get_conn()
        try:
            question = conn.execute(
                "SELECT question FROM tickets WHERE id=?", ("t1",)
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(question, "Coffee or tea?")


if __name__ == "__main__":
    unittest.main()


class TestSlotVisibility(unittest.TestCase):
    """crt#89/#96: ask_zach returned 'pending' whether the question was next
    up or 18 hours deep behind expiring tickets, so a caller could not learn
    its odds and could not choose a different channel."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        db.DB_PATH = Path(self._tmpdir.name) / "tickets.db"

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_ask_zach_reports_the_wait_alongside_the_ticket(self):
        r = server.ask_zach("is this on?", from_agent="crt")
        self.assertIn("queued_ahead", r)
        self.assertIn("est_wait_hours", r)

    def test_check_zach_reply_reports_the_wait_too(self):
        r = server.check_zach_reply(server.ask_zach("q", from_agent="crt")["ticket_id"])
        self.assertIn("est_wait_hours", r)

    def test_a_caller_nobody_answers_is_refused_and_files_no_ticket(self):
        conn = db.get_conn()
        for i in range(queue.ADMIT_MAX_UNANSWERED):
            conn.execute(
                "INSERT INTO tickets (id, from_agent, question, status, created_at) "
                "VALUES (?, 'noisy', 'q', 'stale', strftime('%Y-%m-%dT%H:%M:%SZ','now'))",
                (f"t{i}",),
            )
        conn.commit()
        before = conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
        r = server.ask_zach("one more", from_agent="noisy")
        self.assertEqual(r["status"], "refused")
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0], before)
        conn.close()

    def test_the_refusal_says_what_would_readmit_the_caller(self):
        conn = db.get_conn()
        for i in range(40):
            conn.execute(
                "INSERT INTO tickets (id, from_agent, question, status, created_at) "
                "VALUES (?, 'noisy', 'q', 'stale', strftime('%Y-%m-%dT%H:%M:%SZ','now'))",
                (f"t{i}",),
            )
        conn.commit()
        conn.close()
        self.assertIn("answered", server.ask_zach("x", from_agent="noisy")["error"])
