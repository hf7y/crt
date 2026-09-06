#!/usr/bin/env python3
"""Tests for zaxon_relay_filer.py: a tagged inbox entry gets a pointer issue
in its target repo, not the transcript (crt#154). filer= is injected so
none of this ever shells out to a real `gh`."""
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
import zaxon_relay_filer as filer  # noqa: E402
import zaxon_relay_inbox as inbox  # noqa: E402


class FakeFiler:
    def __init__(self, url="https://github.com/hf7y/realisateur/issues/9", raises=None):
        self.calls = []
        self.url = url
        self.raises = raises

    def __call__(self, repo, title, body):
        self.calls.append((repo, title, body))
        if self.raises:
            raise self.raises
        return self.url


class TestFileIssue(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = Path(self._tmp.name) / "tickets.db"

    def tearDown(self):
        self._tmp.cleanup()

    def test_an_untagged_entry_is_not_filed(self):
        eid = inbox.record_unclassified("water the plants", None, "voice")
        fake = FakeFiler()
        self.assertIsNone(filer.file_issue(eid, filer=fake))
        self.assertEqual(fake.calls, [])

    def test_a_tagged_entry_is_filed_against_its_repo(self):
        eid = inbox.record_unclassified("fix the thing", None, "voice", for_agent="realisateur")
        fake = FakeFiler()
        url = filer.file_issue(eid, filer=fake)
        self.assertEqual(url, fake.url)
        self.assertEqual(len(fake.calls), 1)
        repo, title, body = fake.calls[0]
        self.assertEqual(repo, "realisateur")

    def test_the_transcript_never_reaches_the_title_or_body(self):
        secret = "my social is nine oh two one four"
        eid = inbox.record_unclassified(secret, None, "voice", for_agent="realisateur")
        fake = FakeFiler()
        filer.file_issue(eid, filer=fake)
        _, title, body = fake.calls[0]
        self.assertNotIn(secret, title)
        self.assertNotIn(secret, body)

    def test_the_pointer_names_the_entry_id(self):
        eid = inbox.record_unclassified("fix the thing", None, "voice", for_agent="realisateur")
        fake = FakeFiler()
        filer.file_issue(eid, filer=fake)
        _, _, body = fake.calls[0]
        self.assertIn(eid, body)

    def test_filing_records_the_url_on_the_row(self):
        eid = inbox.record_unclassified("fix the thing", None, "voice", for_agent="realisateur")
        filer.file_issue(eid, filer=FakeFiler())
        row = inbox.fetch_inbox()[0]
        self.assertEqual(row["id"], eid)
        conn = db.get_conn()
        try:
            filed = conn.execute("SELECT filed_issue FROM inbox WHERE id=?", (eid,)).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(filed, FakeFiler().url)

    def test_an_already_filed_entry_is_not_filed_twice(self):
        eid = inbox.record_unclassified("fix the thing", None, "voice", for_agent="realisateur")
        first = FakeFiler()
        filer.file_issue(eid, filer=first)
        second = FakeFiler()
        self.assertIsNone(filer.file_issue(eid, filer=second))
        self.assertEqual(second.calls, [])

    def test_an_unknown_entry_id_is_a_noop(self):
        self.assertIsNone(filer.file_issue("no-such-id", filer=FakeFiler()))

    def test_a_bad_repo_tag_is_not_filed(self):
        eid = inbox.record_unclassified("fix the thing", None, "voice", for_agent="has a space")
        fake = FakeFiler()
        self.assertIsNone(filer.file_issue(eid, filer=fake))
        self.assertEqual(fake.calls, [])

    def test_gh_failure_leaves_the_row_unfiled_for_a_retry(self):
        eid = inbox.record_unclassified("fix the thing", None, "voice", for_agent="realisateur")
        self.assertIsNone(filer.file_issue(eid, filer=FakeFiler(raises=RuntimeError("gh: 404"))))
        conn = db.get_conn()
        try:
            filed = conn.execute("SELECT filed_issue FROM inbox WHERE id=?", (eid,)).fetchone()[0]
        finally:
            conn.close()
        self.assertIsNone(filed)
        retry = FakeFiler()
        self.assertEqual(filer.file_issue(eid, filer=retry), retry.url)


class TestFilePending(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = Path(self._tmp.name) / "tickets.db"

    def tearDown(self):
        self._tmp.cleanup()

    def test_sweeps_every_tagged_unfiled_entry(self):
        a = inbox.record_unclassified("first", None, "voice", for_agent="realisateur")
        b = inbox.record_unclassified("second", None, "voice", for_agent="crt")
        inbox.record_unclassified("untagged", None, "voice")
        fake = FakeFiler()
        filed = filer.file_pending(filer=fake)
        self.assertEqual(set(filed), {a, b})
        self.assertEqual(len(fake.calls), 2)

    def test_does_not_refile_what_is_already_filed(self):
        a = inbox.record_unclassified("first", None, "voice", for_agent="realisateur")
        filer.file_issue(a, filer=FakeFiler())
        fake = FakeFiler()
        self.assertEqual(filer.file_pending(filer=fake), [])
        self.assertEqual(fake.calls, [])

    def test_nothing_pending_is_a_noop(self):
        self.assertEqual(filer.file_pending(filer=FakeFiler()), [])


if __name__ == "__main__":
    unittest.main()
