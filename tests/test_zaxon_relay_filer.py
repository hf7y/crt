#!/usr/bin/env python3
"""Tests for zaxon_relay_filer.py: a tagged voice note gets a pointer issue
in its target repo, never the transcript itself (crt#154)."""
import os
import sys
import unittest
from unittest.mock import patch

RELAY_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "provision", "dexter", "zaxon", "relay",
)
sys.path.insert(0, RELAY_DIR)

import zaxon_relay_filer as filer  # noqa: E402


class TestPointerContent(unittest.TestCase):
    def test_title_never_carries_the_transcript(self):
        title = filer.issue_title("crt", "2026-09-06T21:00:00Z")
        self.assertNotIn("water the plants", title)
        self.assertIn("crt", title)
        self.assertIn("2026-09-06T21:00:00Z", title)

    def test_body_never_carries_the_transcript(self):
        body = filer.issue_body("ab12cd34", "crt", "2026-09-06T21:00:00Z")
        self.assertIn("ab12cd34", body)
        self.assertIn("crt", body)
        self.assertIn("fetch_inbox", body)


class TestFileIssue(unittest.TestCase):
    def test_file_issue_returns_the_creator_result(self):
        calls = []

        def fake_creator(repo, title, body):
            calls.append((repo, title, body))
            return "hf7y/crt#200"

        ref = filer.file_issue("ab12cd34", "crt", "2026-09-06T21:00:00Z", creator=fake_creator)
        self.assertEqual(ref, "hf7y/crt#200")
        self.assertEqual(len(calls), 1)
        repo, title, body = calls[0]
        self.assertEqual(repo, "crt")
        self.assertNotIn("ab12cd34", title)  # id belongs in the body, not the visible title
        self.assertIn("ab12cd34", body)

    def test_file_issue_propagates_creator_failure(self):
        def fake_creator(repo, title, body):
            raise RuntimeError("gh unavailable")

        with self.assertRaises(RuntimeError):
            filer.file_issue("ab12cd34", "crt", "2026-09-06T21:00:00Z", creator=fake_creator)


class TestCloseForRetag(unittest.TestCase):
    def test_close_for_retag_names_the_new_issue_in_the_comment(self):
        """gh-sign's close_check refuses a close comment that names nothing
        a check could go and look at -- a bare repo name would not survive
        it, so the comment must carry the new issue's own owner/repo#N."""
        calls = []
        filer.close_for_retag(
            "hf7y/crt#200", "hf7y/realisateur#9",
            closer=lambda ref, comment: calls.append((ref, comment)),
        )
        self.assertEqual(len(calls), 1)
        ref, comment = calls[0]
        self.assertEqual(ref, "hf7y/crt#200")
        self.assertIn("hf7y/realisateur#9", comment)


class TestDefaultCreator(unittest.TestCase):
    @patch("zaxon_relay_filer.subprocess.run")
    def test_default_creator_routes_through_defere(self, mock_run):
        """Not a raw `gh issue create`: this estate's `gh` refuses an
        agent-written body that skips lib/body-grammar.sh's DECISION/
        DEFERRED/DELIVERS shape, and `defere --project` already produces
        one that satisfies it."""
        mock_run.return_value.stdout = "defere: filed https://github.com/hf7y/crt/issues/42  [deferred]\n"
        ref = filer._default_creator("crt", "voice note tagged crt (t)", "body")
        self.assertEqual(ref, "hf7y/crt#42")
        args = mock_run.call_args[0][0]
        self.assertEqual(args[0], "defere")
        self.assertIn("--project", args)
        self.assertEqual(args[args.index("--project") + 1], "crt")

    @patch("zaxon_relay_filer.subprocess.run")
    def test_default_creator_raises_if_defere_gives_no_url(self, mock_run):
        mock_run.return_value.stdout = "defere: something unexpected\n"
        with self.assertRaises(RuntimeError):
            filer._default_creator("crt", "voice note tagged crt (t)", "body")


class TestDefaultCloser(unittest.TestCase):
    @patch("zaxon_relay_filer.subprocess.run")
    def test_default_closer_splits_owner_repo_and_number(self, mock_run):
        filer._default_closer("hf7y/crt#42", "retagged")
        args = mock_run.call_args[0][0]
        self.assertIn("42", args)
        self.assertIn("hf7y/crt", args)


if __name__ == "__main__":
    unittest.main()
