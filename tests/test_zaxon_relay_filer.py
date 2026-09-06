#!/usr/bin/env python3
"""Tests for zaxon_relay_filer.py: a tagged inbox note becomes a GitHub issue
in its target repo, but the issue is a POINTER, never a paste (crt#154) --
title and body must carry only the inbox id and metadata, never the
message. Retagging a filed note must move the pointer, not leave a stale
issue open in the wrong repo.

No test here shells out to a real `gh` -- every case stubs
zaxon_relay_filer._run_gh."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

RELAY_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "provision", "dexter", "zaxon", "relay",
)
sys.path.insert(0, RELAY_DIR)

import zaxon_relay_db as db  # noqa: E402
import zaxon_relay_inbox as inbox  # noqa: E402
import zaxon_relay_filer as filer  # noqa: E402


class TestRepoNwo(unittest.TestCase):
    def test_a_bare_repo_name_gets_the_default_owner(self):
        self.assertEqual(filer._repo_nwo("realisateur"), "hf7y/realisateur")

    def test_an_already_qualified_name_is_left_alone(self):
        self.assertEqual(filer._repo_nwo("someoneelse/thing"), "someoneelse/thing")


class TestPointerContent(unittest.TestCase):
    def test_the_title_never_contains_the_message(self):
        title = filer._title("abc12345", "voice", "2026-09-06T21:00:00Z")
        self.assertNotIn("secret plan", title)
        self.assertIn("abc12345", title)

    def test_the_body_never_contains_the_message(self):
        body = filer._body("abc12345", "wa1")
        self.assertIn("abc12345", body)
        self.assertIn("fetch_inbox", body)

    def test_the_body_handles_no_reply_to_id(self):
        body = filer._body("abc12345", None)
        self.assertIn("none", body)


class TestCreatePointerIssue(unittest.TestCase):
    @patch("zaxon_relay_filer._run_gh")
    def test_creates_against_the_qualified_repo_and_returns_a_ref(self, run_gh):
        run_gh.return_value = "https://github.com/hf7y/realisateur/issues/42"
        ref = filer.create_pointer_issue("abc12345", "realisateur", "voice", "2026-09-06T21:00:00Z")
        self.assertEqual(ref, "hf7y/realisateur#42")
        args = run_gh.call_args[0][0]
        self.assertEqual(args[:3], ["issue", "create", "--repo"])
        self.assertIn("hf7y/realisateur", args)

    @patch("zaxon_relay_filer._run_gh")
    def test_the_message_never_reaches_the_gh_call(self, run_gh):
        run_gh.return_value = "https://github.com/hf7y/realisateur/issues/1"
        filer.create_pointer_issue("abc12345", "realisateur", "voice", "2026-09-06T21:00:00Z")
        args = run_gh.call_args[0][0]
        joined = " ".join(args)
        self.assertNotIn("secret plan", joined)


class TestClosePointerIssue(unittest.TestCase):
    @patch("zaxon_relay_filer._run_gh")
    def test_closes_by_number_against_the_right_repo(self, run_gh):
        filer.close_pointer_issue("hf7y/realisateur#42", "moved")
        args = run_gh.call_args[0][0]
        self.assertEqual(args, ["issue", "close", "42", "--repo", "hf7y/realisateur", "--comment", "moved"])

    @patch("zaxon_relay_filer._run_gh")
    def test_a_malformed_ref_is_a_noop(self, run_gh):
        filer.close_pointer_issue("garbage", "moved")
        run_gh.assert_not_called()


class TestFileIfTagged(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = Path(self._tmp.name) / "tickets.db"

    def tearDown(self):
        self._tmp.cleanup()

    @patch("zaxon_relay_filer._run_gh")
    def test_an_untagged_note_is_not_filed(self, run_gh):
        eid = inbox.record_unclassified("water the plants", None, "text")
        self.assertIsNone(filer.file_if_tagged(eid))
        run_gh.assert_not_called()

    @patch("zaxon_relay_filer._run_gh")
    def test_an_unknown_entry_is_a_noop(self, run_gh):
        self.assertIsNone(filer.file_if_tagged("no-such-id"))
        run_gh.assert_not_called()

    @patch("zaxon_relay_filer._run_gh")
    def test_a_tagged_note_gets_filed_and_recorded(self, run_gh):
        run_gh.return_value = "https://github.com/hf7y/realisateur/issues/7"
        eid = inbox.record_unclassified("bring the charger", None, "voice", for_agent="realisateur")
        ref = filer.file_if_tagged(eid)
        self.assertEqual(ref, "hf7y/realisateur#7")
        self.assertEqual(inbox.fetch_inbox()[0]["id"], eid)
        row = db.get_conn().execute("SELECT filed_issue FROM inbox WHERE id=?", (eid,)).fetchone()
        self.assertEqual(row[0], "hf7y/realisateur#7")

    @patch("zaxon_relay_filer._run_gh")
    def test_filing_the_same_repo_twice_does_not_refile(self, run_gh):
        run_gh.return_value = "https://github.com/hf7y/realisateur/issues/7"
        eid = inbox.record_unclassified("bring the charger", None, "voice", for_agent="realisateur")
        filer.file_if_tagged(eid)
        run_gh.reset_mock()
        ref = filer.file_if_tagged(eid)
        self.assertEqual(ref, "hf7y/realisateur#7")
        run_gh.assert_not_called()

    @patch("zaxon_relay_filer._run_gh")
    def test_a_retag_to_a_different_repo_closes_the_old_and_files_a_new_one(self, run_gh):
        run_gh.return_value = "https://github.com/hf7y/realisateur/issues/7"
        eid = inbox.record_unclassified("bring the charger", None, "voice", for_agent="realisateur")
        filer.file_if_tagged(eid)

        inbox.assign("crt", eid)
        run_gh.reset_mock()
        run_gh.return_value = "https://github.com/hf7y/crt/issues/9"
        ref = filer.file_if_tagged(eid)

        self.assertEqual(ref, "hf7y/crt#9")
        close_call, create_call = run_gh.call_args_list
        self.assertEqual(close_call[0][0][:2], ["issue", "close"])
        self.assertEqual(close_call[0][0][2:5], ["7", "--repo", "hf7y/realisateur"])
        self.assertEqual(create_call[0][0][:3], ["issue", "create", "--repo"])
        self.assertIn("hf7y/crt", create_call[0][0])

    @patch("zaxon_relay_filer._run_gh")
    def test_the_close_comment_names_the_new_repo_not_the_message(self, run_gh):
        run_gh.return_value = "https://github.com/hf7y/realisateur/issues/7"
        eid = inbox.record_unclassified("a secret plan", None, "voice", for_agent="realisateur")
        filer.file_if_tagged(eid)

        inbox.assign("crt", eid)
        run_gh.reset_mock()
        run_gh.return_value = "https://github.com/hf7y/crt/issues/9"
        filer.file_if_tagged(eid)

        close_call = run_gh.call_args_list[0]
        comment = close_call[0][0][-1]
        self.assertNotIn("a secret plan", comment)
        self.assertIn("crt", comment)


if __name__ == "__main__":
    unittest.main()
