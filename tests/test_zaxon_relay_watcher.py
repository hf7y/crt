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

# crt#154 wired _file_for_tag() behind every retag and every initial tag, and
# its default file_entry/refile_entry shell out to the real `gh` binary --
# which, on a box where `gh` is already logged in (this one), would file a
# REAL issue against a REAL repo every time an unrelated test tags a note.
# Every test in this module gets a network-free stub by default; only
# TestFileForTag below swaps in its own per-test doubles to examine the call.
_REAL_FILE_ENTRY = w.file_entry
_REAL_REFILE_ENTRY = w.refile_entry


def _stub_file_entry(entry_id, repo, via, received_at, creator=None):
    return f"https://github.com/hf7y/{repo}/issues/0"


def _stub_refile_entry(entry_id, old_issue_url, new_repo, via, received_at, creator=None, closer=None):
    return f"https://github.com/hf7y/{new_repo}/issues/0"


def setUpModule():
    w.file_entry = _stub_file_entry
    w.refile_entry = _stub_refile_entry


def tearDownModule():
    w.file_entry = _REAL_FILE_ENTRY
    w.refile_entry = _REAL_REFILE_ENTRY

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


class TestFileForTag(unittest.TestCase):  # crt#154: a tagged note owes its target repo a pointer issue
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = Path(self._tmp.name) / "tickets.db"
        self._orig_file_entry = w.file_entry
        self._orig_refile_entry = w.refile_entry

    def tearDown(self):
        w.file_entry = self._orig_file_entry
        w.refile_entry = self._orig_refile_entry
        self._tmp.cleanup()

    def test_a_freshly_tagged_note_gets_filed(self):
        calls = []
        w.file_entry = lambda *a, **k: calls.append(a) or "https://github.com/hf7y/crt/issues/1"
        eid = inbox.record_unclassified("bring the charger", None, "voice", for_agent="crt")
        w._file_for_tag(eid)
        self.assertEqual(len(calls), 1)
        self.assertEqual(inbox.get_entry(eid)["filed_issue"], "https://github.com/hf7y/crt/issues/1")

    def test_an_untagged_note_is_not_filed(self):
        w.file_entry = lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not file an untagged note"))
        eid = inbox.record_unclassified("water the plants", None, "voice")
        w._file_for_tag(eid)  # must not raise
        self.assertIsNone(inbox.get_entry(eid)["filed_issue"])

    def test_retagging_to_a_different_repo_refiles(self):
        refile_calls = []
        w.refile_entry = lambda *a, **k: refile_calls.append(a) or "https://github.com/hf7y/realisateur/issues/9"
        eid = inbox.record_unclassified("bring the charger", None, "voice", for_agent="crt")
        inbox.set_filed_issue(eid, "https://github.com/hf7y/crt/issues/1")
        inbox.assign("realisateur", eid)
        w._file_for_tag(eid)
        self.assertEqual(len(refile_calls), 1)
        self.assertEqual(refile_calls[0][1], "https://github.com/hf7y/crt/issues/1")
        self.assertEqual(inbox.get_entry(eid)["filed_issue"], "https://github.com/hf7y/realisateur/issues/9")

    def test_retagging_to_the_same_repo_is_a_noop(self):
        w.file_entry = lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not re-file"))
        w.refile_entry = lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not re-file"))
        eid = inbox.record_unclassified("bring the charger", None, "voice", for_agent="crt")
        inbox.set_filed_issue(eid, "https://github.com/hf7y/crt/issues/1")
        w._file_for_tag(eid)  # must not raise -- already filed under this same repo

    def test_a_filing_failure_does_not_crash_and_leaves_it_unfiled(self):
        def boom(*a, **k):
            raise RuntimeError("gh: not authenticated")

        w.file_entry = boom
        eid = inbox.record_unclassified("bring the charger", None, "voice", for_agent="crt")
        w._file_for_tag(eid)  # must not raise
        self.assertIsNone(inbox.get_entry(eid)["filed_issue"])

    def test_a_retag_command_files_the_newly_tagged_note(self):
        calls = []
        w.file_entry = lambda *a, **k: calls.append(a) or "https://github.com/hf7y/realisateur/issues/2"
        self._note = lambda msg: inbox.record_unclassified(msg, None, "voice")
        eid = self._note("second")
        self.assertTrue(w._retag("tag realisateur"))
        self.assertEqual(len(calls), 1)
        self.assertEqual(inbox.get_entry(eid)["filed_issue"], "https://github.com/hf7y/realisateur/issues/2")


if __name__ == "__main__":
    unittest.main()
