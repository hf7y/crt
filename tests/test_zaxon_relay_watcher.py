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


def setUpModule():  # crt#154: a tag fires w.file_issue() -> real `gh`; keep every test but TestFilesOnTag inert
    global _MODULE_FILE_ISSUE_GUARD
    _MODULE_FILE_ISSUE_GUARD = w.file_issue
    w.file_issue = lambda entry_id, **kwargs: None


def tearDownModule():
    w.file_issue = _MODULE_FILE_ISSUE_GUARD


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


class TestForAgentTag(unittest.TestCase):  # crt#130
    def test_a_leading_repo_tag_is_split_out(self):
        for_agent, body = w._split_for_agent("realisateur: the vault notation needs a second example")
        self.assertEqual(for_agent, "realisateur")
        self.assertEqual(body, "the vault notation needs a second example")

    def test_an_untagged_message_splits_to_none(self):
        for_agent, body = w._split_for_agent("remember to water the plants")
        self.assertIsNone(for_agent)
        self.assertEqual(body, "remember to water the plants")

    def test_a_colon_mid_sentence_is_not_mistaken_for_a_tag(self):
        for_agent, body = w._split_for_agent("one thing to note: bring the charger")
        self.assertIsNone(for_agent)
        self.assertEqual(body, "one thing to note: bring the charger")


class TestUnclassifiedInboundAddressing(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = Path(self._tmp.name) / "tickets.db"

    def tearDown(self):
        self._tmp.cleanup()

    def test_record_unclassified_stores_for_agent(self):
        inbox.record_unclassified("bring the charger", None, "text", for_agent="crt")
        entries = inbox.fetch_inbox()
        self.assertEqual(entries[0]["for_agent"], "crt")

    def test_fetch_inbox_hides_a_note_tagged_for_someone_else(self):
        inbox.record_unclassified("bring the charger", None, "text", for_agent="crt")
        self.assertEqual(inbox.fetch_inbox(for_agent="realisateur"), [])

    def test_fetch_inbox_shows_a_note_tagged_for_this_repo(self):
        inbox.record_unclassified("bring the charger", None, "text", for_agent="crt")
        entries = inbox.fetch_inbox(for_agent="crt")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["message"], "bring the charger")

    def test_fetch_inbox_still_shows_untagged_notes_to_anyone(self):
        inbox.record_unclassified("remember to water the plants", None, "text")
        entries = inbox.fetch_inbox(for_agent="crt")
        self.assertEqual(len(entries), 1)

    def test_fetch_inbox_with_no_for_agent_returns_everything(self):
        inbox.record_unclassified("bring the charger", None, "text", for_agent="crt")
        inbox.record_unclassified("water the plants", None, "text")
        self.assertEqual(len(inbox.fetch_inbox()), 2)


class TestClaim(unittest.TestCase):  # crt#129
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = Path(self._tmp.name) / "tickets.db"
        self.entry_id = inbox.record_unclassified("water the plants", None, "text")

    def tearDown(self):
        self._tmp.cleanup()

    def test_the_first_claim_wins(self):
        self.assertTrue(inbox.claim(self.entry_id, "crt"))

    def test_a_second_agent_cannot_claim_what_is_already_held(self):
        inbox.claim(self.entry_id, "crt")
        self.assertFalse(inbox.claim(self.entry_id, "realisateur"))

    def test_claiming_your_own_claim_again_succeeds(self):
        inbox.claim(self.entry_id, "crt")
        self.assertTrue(inbox.claim(self.entry_id, "crt"))

    def test_claiming_an_unknown_entry_reports_false(self):
        self.assertFalse(inbox.claim("no-such-id", "crt"))

    def test_a_claimed_note_is_hidden_from_someone_else(self):
        inbox.claim(self.entry_id, "crt")
        self.assertEqual(inbox.fetch_inbox(for_agent="realisateur"), [])

    def test_a_claimed_note_still_shows_to_the_agent_that_claimed_it(self):
        inbox.claim(self.entry_id, "crt")
        entries = inbox.fetch_inbox(for_agent="crt")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["claimed_by"], "crt")

    def test_include_claimed_shows_it_to_anyone_anyway(self):
        inbox.claim(self.entry_id, "crt")
        entries = inbox.fetch_inbox(for_agent="realisateur", include_claimed=True)
        self.assertEqual(len(entries), 1)

    def test_an_expired_claim_can_be_re_claimed_by_someone_else(self):
        inbox.claim(self.entry_id, "crt")
        old_saved_ttl = inbox.CLAIM_TTL_SECS
        inbox.CLAIM_TTL_SECS = -3600  # a negative TTL puts the threshold in the future, so a claim made THIS second still reads as expired
        try:
            self.assertTrue(inbox.claim(self.entry_id, "realisateur"))
        finally:
            inbox.CLAIM_TTL_SECS = old_saved_ttl

    def test_an_expired_claim_is_visible_to_someone_else_again(self):
        inbox.claim(self.entry_id, "crt")
        old_saved_ttl = inbox.CLAIM_TTL_SECS
        inbox.CLAIM_TTL_SECS = -3600  # a negative TTL puts the threshold in the future, so a claim made THIS second still reads as expired
        try:
            entries = inbox.fetch_inbox(for_agent="realisateur")
            self.assertEqual(len(entries), 1)
        finally:
            inbox.CLAIM_TTL_SECS = old_saved_ttl



class TestRetag(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = Path(self._tmp.name) / "tickets.db"
        self.conn = db.get_conn()

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def _note(self, msg, for_agent=None, claimed_by=None):
        eid = inbox.record_unclassified(msg, None, "voice", for_agent=for_agent)
        if claimed_by:
            inbox.claim(eid, claimed_by)
        return eid

    def test_retag_addresses_the_newest_untagged_note(self):
        old = self._note("first")
        new = self._note("second")
        self.assertTrue(w._retag("tag realisateur"))
        rows = {r["id"]: r["for_agent"] for r in inbox.fetch_inbox()}
        self.assertEqual(rows[new], "realisateur")
        self.assertIsNone(rows[old])

    def test_a_colon_form_is_a_retag_not_a_note_addressed_to_repo_tag(self):
        eid = self._note("a voice note")
        self.assertTrue(w._retag("tag: realisateur"))
        self.assertEqual(inbox.fetch_inbox()[0]["for_agent"], "realisateur")
        self.assertEqual(inbox.fetch_inbox()[0]["id"], eid)

    def test_an_entry_id_addresses_that_one_and_not_the_newest(self):
        first = self._note("first")
        self._note("second")
        self.assertTrue(w._retag("tag %s realisateur" % first))
        rows = {r["id"]: r["for_agent"] for r in inbox.fetch_inbox()}
        self.assertEqual(rows[first], "realisateur")

    def test_an_ordinary_tagged_note_is_not_a_retag(self):
        self.assertFalse(w._retag("realisateur: fix the sweep"))

    def test_a_retag_with_nothing_to_tag_falls_through_and_is_recorded(self):
        self.assertFalse(w._retag("tag realisateur"))

    def test_a_claimed_note_is_not_readdressed_under_the_agent_working_it(self):
        self._note("being worked", claimed_by="musc")
        self.assertFalse(w._retag("tag realisateur"))


class TestFilesOnTag(unittest.TestCase):  # crt#154: a tag, on arrival or by retag, must reach the filer
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = Path(self._tmp.name) / "tickets.db"
        self.filed = []
        self._orig_file_issue = w.file_issue
        w.file_issue = lambda entry_id, **kwargs: self.filed.append(entry_id)

    def tearDown(self):
        w.file_issue = self._orig_file_issue
        self._tmp.cleanup()

    def test_retag_files_the_entry_it_tagged(self):
        eid = inbox.record_unclassified("fix the thing", None, "voice")
        w._retag("tag realisateur")
        self.assertEqual(self.filed, [eid])

    def test_a_retag_that_finds_nothing_files_nothing(self):
        w._retag("tag realisateur")
        self.assertEqual(self.filed, [])

    def test_an_on_arrival_tag_is_filed_via_handle_message(self):
        w._handle_message("None", "realisateur: fix the thing", "voice")
        entries = inbox.fetch_inbox()
        self.assertEqual(len(entries), 1)
        self.assertEqual(self.filed, [entries[0]["id"]])

    def test_an_untagged_arrival_is_never_filed(self):
        w._handle_message("None", "remember to water the plants", "voice")
        self.assertEqual(self.filed, [])

    def test_a_filing_exception_does_not_propagate(self):
        def boom(entry_id, **kwargs):
            raise RuntimeError("defere: BLIND")

        w.file_issue = boom
        eid = inbox.record_unclassified("fix the thing", None, "voice")
        w._retag("tag realisateur")  # must not raise
        self.assertEqual(inbox.fetch_inbox()[0]["id"], eid)


if __name__ == "__main__":
    unittest.main()
