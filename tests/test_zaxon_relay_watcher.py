#!/usr/bin/env python3
"""Tests for zaxon_relay_watcher.py: a voice reply whisper could not hear
must not be mistaken for an answer, and its audio must outlive the sweep
that emptied cache/audio on 2026-08-17 and 2026-08-19."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

RELAY_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "provision", "dexter", "zaxon", "relay",
)
sys.path.insert(0, RELAY_DIR)

import zaxon_relay_db as db  # noqa: E402
import zaxon_relay_inbox as inbox  # noqa: E402
import zaxon_relay_watcher as w  # noqa: E402

FAILED_MSG = (
    "[voice message could not be transcribed automatically; "
    "the audio is available at: {path}]"
)


class TestRetainAudio(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        db.DB_PATH = tmp / "tickets.db"
        w.AUDIO_DIR = tmp / "audio"
        self.conn = db.get_conn()
        self.conn.execute(
            "INSERT INTO tickets (id, from_agent, question, status, created_at, "
            "wa_message_id) VALUES ('t1', 'musc', 'Q', 'pending', '2026-08-25T00:00:00Z', 'wa1')"
        )
        self.conn.commit()
        self.audio = tmp / "aud_ba0497aaa026.ogg"
        self.audio.write_bytes(b"not really ogg")

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def _status(self):
        return db.get_conn().execute(
            "SELECT status, answer, audio_path FROM tickets WHERE id='t1'"
        ).fetchone()

    def test_the_regex_finds_the_path_the_gateway_named(self):
        m = w.STT_FAILED_RE.search(FAILED_MSG.format(path="/x/aud_1.ogg"))
        self.assertIsNotNone(m)
        self.assertEqual(m.group("path"), "/x/aud_1.ogg")

    def test_failed_transcription_is_not_an_answer(self):
        self.assertTrue(w.retain_audio("wa1", str(self.audio)))
        status, answer, _ = self._status()
        self.assertEqual(status, "pending")
        self.assertIsNone(answer)

    def test_audio_is_copied_somewhere_the_sweep_does_not_reach(self):
        w.retain_audio("wa1", str(self.audio))
        _, _, audio_path = self._status()
        self.assertIsNotNone(audio_path)
        kept = Path(audio_path)
        self.assertTrue(kept.exists())
        self.assertEqual(kept.read_bytes(), b"not really ogg")
        self.assertNotEqual(kept, self.audio)

    def test_already_swept_audio_still_leaves_the_ticket_pending(self):
        """The honest state is 'not answered', not an answer invented from a
        message that only says he could not be heard."""
        self.assertTrue(w.retain_audio("wa1", "/gone/aud_missing.ogg"))
        self.assertEqual(self._status()[0], "pending")

    def test_a_reply_to_nothing_is_left_alone(self):
        self.assertFalse(w.retain_audio("wa-unknown", str(self.audio)))


class TestVia(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = Path(self._tmp.name) / "tickets.db"
        conn = db.get_conn()
        for tid, wid in (("t1", "wa1"), ("t2", "wa2")):
            conn.execute(
                "INSERT INTO tickets (id, from_agent, question, status, created_at, "
                f"wa_message_id) VALUES ('{tid}', 'musc', 'Q', 'pending', "
                f"'2026-08-25T00:00:00Z', '{wid}')"
            )
        conn.commit()
        conn.close()

    def tearDown(self):
        self._tmp.cleanup()

    def _via(self, ticket_id):
        return db.get_conn().execute(
            "SELECT status, answer, via FROM tickets WHERE id=?", (ticket_id,)
        ).fetchone()

    def test_text_reply_records_text(self):
        w.resolve_reply("wa1", "1")
        self.assertEqual(self._via("t1"), ("answered", "1", "text"))

    def test_voice_reply_records_voice(self):
        w.resolve_reply("wa2", "make it five pages", "voice")
        self.assertEqual(self._via("t2"), ("answered", "make it five pages", "voice"))

    def test_resolving_a_real_ticket_reports_true(self):
        self.assertTrue(w.resolve_reply("wa1", "1"))

    def test_a_reply_to_nothing_reports_false(self):
        self.assertFalse(w.resolve_reply("wa-unknown", "huh?"))


class TestUnclassifiedInbound(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = Path(self._tmp.name) / "tickets.db"

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_reply_to_a_stale_ticket_is_not_silently_dropped(self):
        self.assertFalse(w.resolve_reply("wa-gone", "sure, five pages"))
        entry_id = inbox.record_unclassified("sure, five pages", "wa-gone", "text")
        entries = inbox.fetch_inbox()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["id"], entry_id)
        self.assertEqual(entries[0]["message"], "sure, five pages")
        self.assertEqual(entries[0]["reply_to_id"], "wa-gone")

    def test_an_unsolicited_message_records_no_reply_to_id(self):
        inbox.record_unclassified("remember to water the plants", None, "text")
        entries = inbox.fetch_inbox()
        self.assertEqual(len(entries), 1)
        self.assertIsNone(entries[0]["reply_to_id"])

    def test_fetch_inbox_is_newest_first_and_non_destructive(self):
        inbox.record_unclassified("first", None)
        inbox.record_unclassified("second", None)
        self.assertEqual([e["message"] for e in inbox.fetch_inbox()], ["second", "first"])
        self.assertEqual(len(inbox.fetch_inbox()), 2)

    def test_fetch_inbox_respects_limit(self):
        for i in range(5):
            inbox.record_unclassified(f"msg{i}", None)
        self.assertEqual(len(inbox.fetch_inbox(limit=2)), 2)


if __name__ == "__main__":
    unittest.main()
