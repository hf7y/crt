#!/usr/bin/env python3
"""Tests for zaxon_relay_filer.py: crt#154's ruling is that a tagged inbox
note gets filed as a pointer issue, and the issue never carries the
transcript -- that split is what makes auto-filing into a public repo safe."""
import os
import sys
import unittest

RELAY_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "provision", "dexter", "zaxon", "relay",
)
sys.path.insert(0, RELAY_DIR)

import zaxon_relay_filer as filer  # noqa: E402


class TestIssueContent(unittest.TestCase):
    def test_title_never_carries_the_message_text(self):
        title = filer.issue_title("abc12345", "2026-09-06T21:00:00Z")
        self.assertIn("abc12345", title)
        self.assertNotIn("route the transcript", title)

    def test_body_carries_the_pointer_not_the_transcript(self):
        body = filer.issue_body("abc12345", "voice", "2026-09-06T21:00:00Z")
        self.assertIn("abc12345", body)
        self.assertIn("voice", body)
        self.assertIn("fetch_inbox", body)


class TestRepoFromIssueUrl(unittest.TestCase):
    def test_parses_the_repo_out_of_a_real_gh_url(self):
        self.assertEqual(
            filer.repo_from_issue_url("https://github.com/hf7y/realisateur/issues/42"),
            "realisateur",
        )

    def test_tolerates_a_trailing_slash(self):
        self.assertEqual(
            filer.repo_from_issue_url("https://github.com/hf7y/crt/issues/9/"),
            "crt",
        )


class TestFileEntry(unittest.TestCase):
    def test_creator_is_called_with_the_target_repo(self):
        calls = []
        creator = lambda repo, title, body: calls.append((repo, title, body)) or "https://github.com/hf7y/crt/issues/1"
        url = filer.file_entry("e1", "crt", "voice", "2026-09-06T00:00:00Z", creator=creator)
        self.assertEqual(url, "https://github.com/hf7y/crt/issues/1")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "crt")

    def test_creator_never_receives_the_transcript(self):
        seen = {}

        def creator(repo, title, body):
            seen["title"] = title
            seen["body"] = body
            return "https://github.com/hf7y/crt/issues/2"

        filer.file_entry("e2", "crt", "voice", "2026-09-06T00:00:00Z", creator=creator)
        for field in seen.values():
            self.assertNotIn("meet me at", field)  # a transcript the creator was never handed


class TestRefileEntry(unittest.TestCase):
    def test_files_fresh_under_the_new_repo(self):
        creator = lambda repo, title, body: f"https://github.com/hf7y/{repo}/issues/9"
        url = filer.refile_entry("e3", "https://github.com/hf7y/crt/issues/1", "realisateur",
                                  "voice", "2026-09-06T00:00:00Z", creator=creator)
        self.assertEqual(url, "https://github.com/hf7y/realisateur/issues/9")

    def test_closes_the_superseded_issue(self):
        closed = []
        creator = lambda repo, title, body: f"https://github.com/hf7y/{repo}/issues/9"
        closer = lambda url, comment: closed.append((url, comment))
        filer.refile_entry("e4", "https://github.com/hf7y/crt/issues/1", "realisateur",
                            "voice", "2026-09-06T00:00:00Z", creator=creator, closer=closer)
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0][0], "https://github.com/hf7y/crt/issues/1")
        self.assertIn("realisateur", closed[0][1])

    def test_no_old_issue_means_no_close_attempt(self):
        closed = []
        creator = lambda repo, title, body: f"https://github.com/hf7y/{repo}/issues/9"
        closer = lambda url, comment: closed.append((url, comment))
        filer.refile_entry("e5", None, "realisateur", "voice", "2026-09-06T00:00:00Z",
                            creator=creator, closer=closer)
        self.assertEqual(closed, [])

    def test_a_closer_that_raises_still_returns_the_new_url(self):
        def closer(url, comment):
            raise RuntimeError("gh: issue already closed")

        creator = lambda repo, title, body: f"https://github.com/hf7y/{repo}/issues/9"
        url = filer.refile_entry("e6", "https://github.com/hf7y/crt/issues/1", "realisateur",
                                  "voice", "2026-09-06T00:00:00Z", creator=creator, closer=closer)
        self.assertEqual(url, "https://github.com/hf7y/realisateur/issues/9")


if __name__ == "__main__":
    unittest.main()
