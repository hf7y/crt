#!/usr/bin/env python3
"""Tests for zaxon-status-collect.py's verdict ladder.

The one thing worth pinning mechanically: A RELAY THAT ANSWERS IS NEVER OK
ON ITS OWN. Every cheap version of this page reports the port, and the port
was green through the whole two-day stretch in which nothing zaxon sent got
an answer. Each case below is a state where the port is open and the
channel is not working.
"""
import importlib.util
import os
import sqlite3
import sys
import tempfile
import time
import unittest

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "provision", "dexter", "zaxon", "zaxon-status-collect.py")
spec = importlib.util.spec_from_file_location("zaxon_status_collect", SRC)
zsc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(zsc)

UP = {"answers": True, "url": "http://127.0.0.1:8643/mcp", "ms": 3}


def _ago(hours):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - hours * 3600))


class VerdictLadder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        zsc.DB = os.path.join(self.tmp.name, "tickets.db")
        conn = sqlite3.connect(zsc.DB)
        conn.execute("CREATE TABLE tickets (id TEXT PRIMARY KEY, from_agent TEXT, "
                     "question TEXT, wa_message_id TEXT, status TEXT, answer TEXT, "
                     "created_at TEXT, answered_at TEXT, options TEXT)")
        conn.commit()
        self.conn = conn

    def add(self, status, hours_ago=1.0, agent="a", answered_at=None):
        self.conn.execute(
            "INSERT INTO tickets (id, from_agent, question, status, created_at, answered_at) "
            "VALUES (?,?,?,?,?,?)",
            (f"t{time.time_ns()}", agent, "q?", status, _ago(hours_ago), answered_at))
        self.conn.commit()

    def verdict(self, relay=UP):
        return zsc.verdict(zsc.collect(), relay)[0]

    def test_relay_silent_is_DOWN(self):
        self.add("answered", answered_at=_ago(0.5))
        self.assertEqual(self.verdict({"answers": False}), "DOWN")

    def test_unreadable_ledger_is_BLIND_not_OK(self):
        # The port answers and the store is gone: the page knows nothing about
        # whether questions land, and must not round that up to healthy.
        zsc.DB = os.path.join(self.tmp.name, "nope", "tickets.db")
        self.assertEqual(self.verdict(), "BLIND")

    def test_failed_send_is_DOWN(self):
        # The failure that looks fine from every caller's side: ask_zach returns
        # a ticket whether or not WhatsApp took the message.
        self.add("failed")
        self.assertEqual(self.verdict(), "DOWN")

    def test_sent_and_none_answered_is_UNANSWERED(self):
        for _ in range(3):
            self.add("stale")
        self.assertEqual(self.verdict(), "UNANSWERED")

    def test_pending_past_its_TTL_is_WEDGED(self):
        # sweep_and_promote() should have staled this and released the slot.
        # Still pending hours later means the queue is stuck, not just ignored.
        self.add("pending", hours_ago=5)
        self.assertEqual(self.verdict(), "WEDGED")

    def test_empty_window_is_QUIET_not_OK(self):
        self.add("answered", hours_ago=100, answered_at=_ago(99))
        self.assertEqual(self.verdict(), "QUIET")

    def test_answered_is_OK(self):
        self.add("answered", answered_at=_ago(0.5))
        self.assertEqual(self.verdict(), "OK")


class SlotCost(unittest.TestCase):
    """The single slot (crt#67) is the resource an ignored question spends.
    stale_slot_hours is what it cost every OTHER caller, which is the number
    a miss-rate percentage hides."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        zsc.DB = os.path.join(self.tmp.name, "tickets.db")
        conn = sqlite3.connect(zsc.DB)
        conn.execute("CREATE TABLE tickets (id TEXT PRIMARY KEY, from_agent TEXT, "
                     "question TEXT, wa_message_id TEXT, status TEXT, answer TEXT, "
                     "created_at TEXT, answered_at TEXT, options TEXT)")
        for i in range(6):
            conn.execute("INSERT INTO tickets (id, from_agent, question, status, created_at) "
                         "VALUES (?,?,?,?,?)",
                         (f"s{i}", "ausculte-cadence", "q?", "stale", _ago(i + 1)))
        # Outside the 24h window: must not be counted.
        conn.execute("INSERT INTO tickets (id, from_agent, question, status, created_at) "
                     "VALUES ('old','x','q?','stale',?)", (_ago(48),))
        conn.commit()

    def test_counts_only_the_window(self):
        led = zsc.collect()
        self.assertEqual(led["window_sent"], 6)
        self.assertEqual(led["totals"]["stale"], 7)
        self.assertEqual(led["stale_slot_hours"], 6.0)

    def test_names_the_sender_holding_the_channel(self):
        top = zsc.collect()["senders"][0]
        self.assertEqual((top["from"], top["sent"], top["answered"]),
                         ("ausculte-cadence", 6, 0))


class InboxLedger(unittest.TestCase):  # crt#87's inbox has no consumed_by yet: read-only count+age

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        zsc.DB = os.path.join(self.tmp.name, "tickets.db")
        self.conn = sqlite3.connect(zsc.DB)
        self.conn.execute("CREATE TABLE tickets (id TEXT PRIMARY KEY, from_agent TEXT, "
                          "question TEXT, wa_message_id TEXT, status TEXT, answer TEXT, "
                          "created_at TEXT, answered_at TEXT, options TEXT)")
        self.conn.commit()

    def add_inbox(self, entry_id, hours_ago):
        self.conn.execute(
            "INSERT INTO inbox (id, message, reply_to_id, received_at, via) "
            "VALUES (?,?,?,?,?)",
            (entry_id, "m", None, _ago(hours_ago), "text"))
        self.conn.commit()

    def test_no_inbox_table_is_None_not_a_failed_collect(self):
        led = zsc.collect()
        self.assertTrue(led["readable"])
        self.assertIsNone(led["inbox"])

    def test_empty_inbox_table_is_zero_not_None(self):
        self.conn.execute("CREATE TABLE inbox (id TEXT PRIMARY KEY, message TEXT NOT NULL, "
                          "reply_to_id TEXT, received_at TEXT NOT NULL, via TEXT)")
        self.conn.commit()
        inbox = zsc.collect()["inbox"]
        self.assertEqual(inbox, {"count": 0, "window_count": 0, "oldest_age_hours": None})

    def test_counts_and_windows_and_oldest_age(self):
        self.conn.execute("CREATE TABLE inbox (id TEXT PRIMARY KEY, message TEXT NOT NULL, "
                          "reply_to_id TEXT, received_at TEXT NOT NULL, via TEXT)")
        self.conn.commit()
        self.add_inbox("a", 1.0)
        self.add_inbox("b", 5.0)
        self.add_inbox("c", 48.0)   # outside the 24h window, still in count
        inbox = zsc.collect()["inbox"]
        self.assertEqual(inbox["count"], 3)
        self.assertEqual(inbox["window_count"], 2)
        self.assertEqual(inbox["oldest_age_hours"], 48.0)


if __name__ == "__main__":
    unittest.main()
