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

    def test_bundled_question_is_refused_even_under_the_char_budget(self):
        with self.assertRaises(ValueError):
            q.validate_message("musc", "Coffee or tea? And also, pizza tonight?")


class TestValidateSingleQuestion(unittest.TestCase):
    def test_a_single_question_is_accepted(self):
        q.validate_single_question("Coffee or tea?")

    def test_a_question_with_no_question_mark_is_accepted(self):
        q.validate_single_question("Send the invoice by Friday")

    def test_two_question_marks_are_refused(self):
        with self.assertRaises(ValueError):
            q.validate_single_question("Coffee or tea? Pizza tonight?")

    def test_two_enumerated_items_are_refused(self):
        with self.assertRaises(ValueError):
            q.validate_single_question("Pick one:\n1. coffee\n2. tea")

    def test_one_enumerated_item_alone_is_accepted(self):
        q.validate_single_question("1. is this the only option that matters?")

    def test_at_the_line_budget_is_accepted(self):
        q.validate_single_question("line one\nline two\nline three")

    def test_a_question_spanning_too_many_lines_is_refused(self):
        with self.assertRaises(ValueError):
            q.validate_single_question("line one\nline two\nline three\nline four")

    def test_the_sanctioned_options_poll_is_not_bundling(self):
        q.validate_message("musc", "Coffee or tea?", ["coffee", "tea"])


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


class TestRecoverFromGatewayCache(unittest.TestCase):
    def _overdue(self, conn, ticket_id="t1"):
        old_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - q.QUESTION_TTL_SECS - 10))
        _insert(conn, ticket_id, "Q1", "pending", created_at=old_ts)
        return old_ts

    def test_audio_cached_after_delivery_resolves_the_ticket_instead_of_expiring(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as cache:
            conn = _fresh_conn(tmp)
            self._overdue(conn)
            (Path(cache) / "aud_123.ogg").write_bytes(b"audio")
            q.sweep_and_promote(
                conn, sender=lambda text: {"success": True},
                cache_dir=Path(cache), transcribe=lambda path: "coffee please",
            )
            row = conn.execute(
                "SELECT status, answer, via FROM tickets WHERE id='t1'"
            ).fetchone()
            self.assertEqual(row, ("answered", "coffee please", "voice"))

    def test_recovered_answer_still_frees_the_slot_for_the_next_queued(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as cache:
            conn = _fresh_conn(tmp)
            self._overdue(conn)
            _insert(conn, "t2", "Q2", "queued")
            (Path(cache) / "aud_123.ogg").write_bytes(b"audio")
            sent = []
            q.sweep_and_promote(
                conn, sender=lambda text: sent.append(text) or {"success": True, "message_id": "wa2"},
                cache_dir=Path(cache), transcribe=lambda path: "coffee please",
            )
            self.assertEqual(len(sent), 1)
            t2_status = conn.execute("SELECT status FROM tickets WHERE id='t2'").fetchone()[0]
            self.assertEqual(t2_status, "pending")

    def test_audio_older_than_the_ticket_is_not_mistaken_for_its_reply(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as cache:
            conn = _fresh_conn(tmp)
            self._overdue(conn)
            stale_audio = Path(cache) / "aud_old.ogg"
            stale_audio.write_bytes(b"audio")
            old_mtime = time.time() - q.QUESTION_TTL_SECS - 3600
            os.utime(stale_audio, (old_mtime, old_mtime))
            q.sweep_and_promote(
                conn, sender=lambda text: {"success": True},
                cache_dir=Path(cache), transcribe=lambda path: self.fail("should not transcribe stale audio"),
            )
            status = conn.execute("SELECT status FROM tickets WHERE id='t1'").fetchone()[0]
            self.assertEqual(status, "stale")

    def test_no_cached_audio_falls_back_to_the_old_stale_behavior(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as cache:
            conn = _fresh_conn(tmp)
            self._overdue(conn)
            q.sweep_and_promote(
                conn, sender=lambda text: {"success": True}, cache_dir=Path(cache),
            )
            status = conn.execute("SELECT status FROM tickets WHERE id='t1'").fetchone()[0]
            self.assertEqual(status, "stale")

    def test_a_transcription_failure_still_falls_back_to_stale(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as cache:
            conn = _fresh_conn(tmp)
            self._overdue(conn)
            (Path(cache) / "aud_123.ogg").write_bytes(b"audio")

            def _raise(path):
                raise OSError("whisper still down")

            q.sweep_and_promote(
                conn, sender=lambda text: {"success": True},
                cache_dir=Path(cache), transcribe=_raise,
            )
            status = conn.execute("SELECT status FROM tickets WHERE id='t1'").fetchone()[0]
            self.assertEqual(status, "stale")

    def test_missing_cache_dir_falls_back_to_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = _fresh_conn(tmp)
            self._overdue(conn)
            q.sweep_and_promote(
                conn, sender=lambda text: {"success": True},
                cache_dir=Path(tmp) / "no-such-dir",
            )
            status = conn.execute("SELECT status FROM tickets WHERE id='t1'").fetchone()[0]
            self.assertEqual(status, "stale")


class TestMessageReuse(unittest.TestCase):
    def test_first_ever_ticket_has_nothing_to_edit_so_it_sends_fresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = _fresh_conn(tmp)
            _insert(conn, "t1", "Q1", "queued")
            sent, edited = [], []
            q.sweep_and_promote(
                conn,
                sender=lambda text: sent.append(text) or {"success": True, "message_id": "wa1"},
                editor=lambda *a: edited.append(a) or {"success": True},
            )
            self.assertEqual(len(sent), 1)
            self.assertEqual(len(edited), 0)

    def test_second_promoted_ticket_edits_the_first_message_instead_of_sending(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = _fresh_conn(tmp)
            old_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - q.QUESTION_TTL_SECS - 10))
            _insert(conn, "t1", "Q1", "pending", created_at=old_ts)
            conn.execute(
                "UPDATE tickets SET wa_message_id='wa1', chat_id='chat1' WHERE id='t1'"
            )
            conn.commit()
            _insert(conn, "t2", "Q2", "queued")

            sent, edited = [], []
            q.sweep_and_promote(
                conn,
                sender=lambda text: sent.append(text) or {"success": True, "message_id": "wa2"},
                editor=lambda chat_id, message_id, text: edited.append((chat_id, message_id, text)) or {"success": True},
            )

            self.assertEqual(len(sent), 0, "reused the prior message instead of sending a new one")
            self.assertEqual(len(edited), 1)
            self.assertEqual(edited[0][:2], ("chat1", "wa1"))
            row = conn.execute("SELECT status, wa_message_id, chat_id FROM tickets WHERE id='t2'").fetchone()
            self.assertEqual(row, ("pending", "wa1", "chat1"))

    def test_a_closed_edit_window_falls_back_to_a_fresh_send(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = _fresh_conn(tmp)
            old_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - q.QUESTION_TTL_SECS - 10))
            _insert(conn, "t1", "Q1", "pending", created_at=old_ts)
            conn.execute(
                "UPDATE tickets SET wa_message_id='wa1', chat_id='chat1' WHERE id='t1'"
            )
            conn.commit()
            _insert(conn, "t2", "Q2", "queued")

            sent = []
            q.sweep_and_promote(
                conn,
                sender=lambda text: sent.append(text) or {"success": True, "message_id": "wa2"},
                editor=lambda *a: {"success": False, "error": "edit window closed"},
            )

            self.assertEqual(len(sent), 1)
            row = conn.execute("SELECT status, wa_message_id FROM tickets WHERE id='t2'").fetchone()
            self.assertEqual(row, ("pending", "wa2"))

    def test_an_editor_exception_falls_back_to_a_fresh_send(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = _fresh_conn(tmp)
            old_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - q.QUESTION_TTL_SECS - 10))
            _insert(conn, "t1", "Q1", "pending", created_at=old_ts)
            conn.execute(
                "UPDATE tickets SET wa_message_id='wa1', chat_id='chat1' WHERE id='t1'"
            )
            conn.commit()
            _insert(conn, "t2", "Q2", "queued")

            def _raise(*a):
                raise RuntimeError("bridge unreachable")

            sent = []
            q.sweep_and_promote(
                conn,
                sender=lambda text: sent.append(text) or {"success": True, "message_id": "wa2"},
                editor=_raise,
            )
            self.assertEqual(len(sent), 1)

    def test_three_tickets_in_a_row_only_ever_send_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = _fresh_conn(tmp)
            sent, edited = [], []
            sender = lambda text: sent.append(text) or {"success": True, "message_id": "wa1"}
            editor = lambda *a: edited.append(a) or {"success": True}

            for i in range(3):
                _insert(conn, f"t{i}", f"Q{i}", "queued")
                q.sweep_and_promote(conn, sender=sender, editor=editor)
                old_ts = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - q.QUESTION_TTL_SECS - 10)
                )
                # Staleness is measured from delivered_at (crt#231), not
                # created_at -- backdate both to force expiry.
                conn.execute(
                    "UPDATE tickets SET created_at=?, delivered_at=? WHERE id=?",
                    (old_ts, old_ts, f"t{i}"),
                )
                conn.commit()

            self.assertEqual(len(sent), 1)
            self.assertEqual(len(edited), 2)


class TestPerAgentSlot(unittest.TestCase):
    """crt#230/crt#232: the slot is keyed on from_agent, not global. 172
    tickets from four different agents used to land in one WhatsApp
    message, each overwriting the last."""

    def _insert_agent(self, conn, ticket_id, from_agent, question, status, created_at=None):
        conn.execute(
            "INSERT INTO tickets (id, from_agent, question, status, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (ticket_id, from_agent, question, status, created_at or q._iso_now()),
        )
        conn.commit()

    def test_two_different_agents_both_promote_in_the_same_sweep(self):
        """A chatty repo occupying its own slot must not block a different
        repo's question -- the old global slot let exactly one ticket,
        from any agent, be pending at a time."""
        with tempfile.TemporaryDirectory() as tmp:
            conn = _fresh_conn(tmp)
            self._insert_agent(conn, "t1", "monkey-watch", "flap alert", "queued")
            self._insert_agent(conn, "t2", "groc-mangr", "deliver window ok?", "queued")
            sent = []
            q.sweep_and_promote(
                conn, sender=lambda text: sent.append(text) or {"success": True, "message_id": f"wa{len(sent)}"}
            )
            statuses = dict(conn.execute("SELECT from_agent, status FROM tickets").fetchall())
            self.assertEqual(statuses, {"monkey-watch": "pending", "groc-mangr": "pending"})
            self.assertEqual(len(sent), 2, "each agent should get its own fresh message")

    def test_a_second_question_from_the_same_agent_still_queues(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = _fresh_conn(tmp)
            self._insert_agent(conn, "t1", "monkey-watch", "Q1", "pending")
            self._insert_agent(conn, "t2", "monkey-watch", "Q2", "queued")
            q.sweep_and_promote(conn, sender=lambda text: self.fail("should not send yet"))
            status = conn.execute("SELECT status FROM tickets WHERE id='t2'").fetchone()[0]
            self.assertEqual(status, "queued")

    def test_deliver_only_edits_this_agents_own_prior_message_not_a_different_agents(self):
        """The exact shape of crt#232: a monkey-watch ticket must not edit
        groc-mangr's message just because it was delivered most recently."""
        with tempfile.TemporaryDirectory() as tmp:
            conn = _fresh_conn(tmp)
            self._insert_agent(conn, "t0", "groc-mangr", "Q0", "answered")
            conn.execute(
                "UPDATE tickets SET wa_message_id='wa-groc', chat_id='chat1' WHERE id='t0'"
            )
            conn.commit()
            self._insert_agent(conn, "t1", "monkey-watch", "Q1", "queued")

            sent, edited = [], []
            q.sweep_and_promote(
                conn,
                sender=lambda text: sent.append(text) or {"success": True, "message_id": "wa-monkey"},
                editor=lambda *a: edited.append(a) or {"success": True},
            )
            self.assertEqual(len(edited), 0, "must not reuse a different agent's message")
            self.assertEqual(len(sent), 1)
            row = conn.execute("SELECT wa_message_id FROM tickets WHERE id='t1'").fetchone()
            self.assertEqual(row[0], "wa-monkey")
            groc_message_id = conn.execute(
                "SELECT wa_message_id FROM tickets WHERE id='t0'"
            ).fetchone()[0]
            self.assertEqual(groc_message_id, "wa-groc", "the other agent's message must be untouched")

    def test_a_stale_agent_frees_only_its_own_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = _fresh_conn(tmp)
            old_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - q.QUESTION_TTL_SECS - 10))
            self._insert_agent(conn, "t1", "monkey-watch", "Q1", "pending", created_at=old_ts)
            self._insert_agent(conn, "t2", "groc-mangr", "Q2", "pending")
            self._insert_agent(conn, "t3", "monkey-watch", "Q3", "queued")
            q.sweep_and_promote(
                conn, sender=lambda text: {"success": True, "message_id": "wa3"}
            )
            statuses = dict(conn.execute("SELECT id, status FROM tickets").fetchall())
            self.assertEqual(statuses["t1"], "stale")
            self.assertEqual(statuses["t2"], "pending", "unrelated agent's fresh slot must be untouched")
            self.assertEqual(statuses["t3"], "pending")


class TestDeliveredAtTTL(unittest.TestCase):
    """crt#231: a ticket's TTL is spent while it waits in the queue, not
    while it is actually on the phone -- the clock must start at delivery,
    not at filing."""

    def test_deliver_stamps_delivered_at(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = _fresh_conn(tmp)
            _insert(conn, "t1", "Q1", "queued")
            q.sweep_and_promote(conn, sender=lambda text: {"success": True, "message_id": "wa1"})
            delivered_at = conn.execute(
                "SELECT delivered_at FROM tickets WHERE id='t1'"
            ).fetchone()[0]
            self.assertIsNotNone(delivered_at)

    def test_a_ticket_that_waited_almost_a_full_ttl_in_queue_still_gets_a_fresh_ttl_once_delivered(self):
        """Before crt#231: a ticket promoted after waiting most of a TTL in
        the queue inherited the old created_at clock and expired almost
        immediately. Now the clock restarts at delivery."""
        with tempfile.TemporaryDirectory() as tmp:
            conn = _fresh_conn(tmp)
            old_ts = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - q.QUESTION_TTL_SECS + 30)
            )
            _insert(conn, "t1", "Q1", "queued", created_at=old_ts)
            q.sweep_and_promote(conn, sender=lambda text: {"success": True, "message_id": "wa1"})
            # A second sweep right after promotion must not immediately
            # mark it stale, even though created_at is nearly TTL-old.
            q.sweep_and_promote(conn, sender=lambda text: self.fail("should not need to resend"))
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
        """The pending ticket must still be within its TTL to count as
        ahead (crt#231) -- use recent, not long-decayed, timestamps."""
        now = time.time()
        ts = lambda offset: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + offset))
        _insert(self.conn, "a", "q", "pending", created_at=ts(-120))
        _insert(self.conn, "b", "q", "queued", created_at=ts(-60))
        _insert(self.conn, "c", "q", "queued", created_at=ts(0))
        self.assertEqual(q.slot_report(self.conn, "c")["queued_ahead"], 2)

    def test_the_wait_is_the_worst_case_every_one_ahead_expiring(self):
        now = time.time()
        ts = lambda offset: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + offset))
        _insert(self.conn, "a", "q", "pending", created_at=ts(-60))
        _insert(self.conn, "b", "q", "queued", created_at=ts(0))
        r = q.slot_report(self.conn, "b")
        self.assertEqual(r["est_wait_hours"],
                         round(r["queued_ahead"] * q.QUESTION_TTL_SECS / 3600, 1))

    def test_an_unknown_ticket_reports_nothing_rather_than_zero(self):
        self.assertEqual(q.slot_report(self.conn, "nope"), {})


class TestSendNow(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.conn = _fresh_conn(self._tmp.name)

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def test_nothing_delivered_yet_sends_fresh(self):
        sent = []
        result = q.send_now(self.conn, "crt", "order placed",
                             sender=lambda text: sent.append(text) or {"success": True, "message_id": "wa1"})
        self.assertEqual(sent, ["*crt* order placed"])
        self.assertEqual(result, {"success": True, "message_id": "wa1"})

    def test_over_length_raises_and_never_calls_the_sender(self):
        with self.assertRaises(ValueError):
            q.send_now(self.conn, "crt", "x" * 200, sender=lambda text: self.fail("sender should not run"))

    def test_send_exception_is_reported_not_raised(self):
        def _raise(text):
            raise RuntimeError("no network")

        result = q.send_now(self.conn, "crt", "order placed", sender=_raise)
        self.assertEqual(result, {"success": False, "error": "no network"})

    def test_reuses_the_last_delivered_message_instead_of_sending_fresh(self):
        _insert(self.conn, "t1", "Q1", "stale")
        self.conn.execute(
            "UPDATE tickets SET wa_message_id=?, chat_id=? WHERE id='t1'", ("wa1", "chat1")
        )
        self.conn.commit()

        edits = []
        result = q.send_now(
            self.conn, "crt", "order placed",
            sender=lambda text: self.fail("a fresh send happened when an edit should have"),
            editor=lambda chat_id, message_id, text: edits.append((chat_id, message_id, text))
            or {"success": True},
        )
        self.assertEqual(edits, [("chat1", "wa1", "*crt* order placed")])
        self.assertEqual(result, {"success": True, "message_id": "wa1", "chat_id": "chat1"})

    def test_a_currently_pending_ticket_is_never_overwritten(self):
        _insert(self.conn, "t1", "Q1", "pending")
        self.conn.execute(
            "UPDATE tickets SET wa_message_id=?, chat_id=? WHERE id='t1'", ("wa1", "chat1")
        )
        self.conn.commit()

        sent = []
        result = q.send_now(
            self.conn, "crt", "order placed",
            sender=lambda text: sent.append(text) or {"success": True, "message_id": "wa2"},
            editor=lambda *a: self.fail("editing a live pending question"),
        )
        self.assertEqual(sent, ["*crt* order placed"])
        self.assertEqual(result, {"success": True, "message_id": "wa2"})

    def test_falls_back_to_a_fresh_send_when_the_edit_is_refused(self):
        _insert(self.conn, "t1", "Q1", "stale")
        self.conn.execute(
            "UPDATE tickets SET wa_message_id=?, chat_id=? WHERE id='t1'", ("wa1", "chat1")
        )
        self.conn.commit()

        result = q.send_now(
            self.conn, "crt", "order placed",
            sender=lambda text: {"success": True, "message_id": "wa2"},
            editor=lambda *a: {"success": False},
        )
        self.assertEqual(result, {"success": True, "message_id": "wa2"})
