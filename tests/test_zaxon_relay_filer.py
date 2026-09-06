#!/usr/bin/env python3
"""Tests for zaxon_relay_filer.py: a tagged inbox entry gets a pointer issue
in its target repo, not the transcript (crt#154). `creator`/`closer` are
injected so none of this ever shells out to a real `defere` or `gh`."""
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


class FakeCreator:
    def __init__(self, ref="hf7y/realisateur#9", raises=None):
        self.calls = []
        self.ref = ref
        self.raises = raises

    def __call__(self, repo, title, body):
        self.calls.append((repo, title, body))
        if self.raises:
            raise self.raises
        return self.ref


class FakeCloser:
    def __init__(self, raises=None):
        self.calls = []
        self.raises = raises

    def __call__(self, issue_ref, comment):
        self.calls.append((issue_ref, comment))
        if self.raises:
            raise self.raises


class TestFileIssue(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        db.DB_PATH = Path(self._tmp.name) / "tickets.db"

    def tearDown(self):
        self._tmp.cleanup()

    def test_an_untagged_entry_is_not_filed(self):
        eid = inbox.record_unclassified("water the plants", None, "voice")
        fake = FakeCreator()
        self.assertIsNone(filer.file_issue(eid, creator=fake))
        self.assertEqual(fake.calls, [])

    def test_a_tagged_entry_is_filed_against_its_repo(self):
        eid = inbox.record_unclassified("fix the thing", None, "voice", for_agent="realisateur")
        fake = FakeCreator()
        ref = filer.file_issue(eid, creator=fake)
        self.assertEqual(ref, fake.ref)
        self.assertEqual(len(fake.calls), 1)
        repo, title, body = fake.calls[0]
        self.assertEqual(repo, "realisateur")

    def test_the_transcript_never_reaches_the_title_or_body(self):
        secret = "my social is nine oh two one four"
        eid = inbox.record_unclassified(secret, None, "voice", for_agent="realisateur")
        fake = FakeCreator()
        filer.file_issue(eid, creator=fake)
        _, title, body = fake.calls[0]
        self.assertNotIn(secret, title)
        self.assertNotIn(secret, body)

    def test_the_pointer_names_the_entry_id(self):
        eid = inbox.record_unclassified("fix the thing", None, "voice", for_agent="realisateur")
        fake = FakeCreator()
        filer.file_issue(eid, creator=fake)
        _, _, body = fake.calls[0]
        self.assertIn(eid, body)

    def test_filing_records_the_ref_on_the_row(self):
        eid = inbox.record_unclassified("fix the thing", None, "voice", for_agent="realisateur")
        filer.file_issue(eid, creator=FakeCreator())
        conn = db.get_conn()
        try:
            filed = conn.execute("SELECT filed_issue FROM inbox WHERE id=?", (eid,)).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(filed, FakeCreator().ref)

    def test_an_already_filed_entry_is_not_refiled(self):
        eid = inbox.record_unclassified("fix the thing", None, "voice", for_agent="realisateur")
        filer.file_issue(eid, creator=FakeCreator())
        second = FakeCreator()
        self.assertIsNone(filer.file_issue(eid, creator=second))
        self.assertEqual(second.calls, [])

    def test_an_unknown_entry_id_is_a_noop(self):
        self.assertIsNone(filer.file_issue("no-such-id", creator=FakeCreator()))

    def test_a_bad_repo_tag_is_not_filed(self):
        eid = inbox.record_unclassified("fix the thing", None, "voice", for_agent="has a space")
        fake = FakeCreator()
        self.assertIsNone(filer.file_issue(eid, creator=fake))
        self.assertEqual(fake.calls, [])

    def test_creation_failure_leaves_the_row_unfiled_for_a_retry(self):
        eid = inbox.record_unclassified("fix the thing", None, "voice", for_agent="realisateur")
        self.assertIsNone(filer.file_issue(eid, creator=FakeCreator(raises=RuntimeError("defere: BLIND"))))
        conn = db.get_conn()
        try:
            filed = conn.execute("SELECT filed_issue FROM inbox WHERE id=?", (eid,)).fetchone()[0]
        finally:
            conn.close()
        self.assertIsNone(filed)
        retry = FakeCreator()
        self.assertEqual(filer.file_issue(eid, creator=retry), retry.ref)

    def test_a_retag_to_a_different_repo_closes_the_old_and_files_a_new_one(self):
        eid = inbox.record_unclassified("fix the thing", None, "voice", for_agent="realisateur")
        filer.file_issue(eid, creator=FakeCreator(ref="hf7y/realisateur#7"))

        inbox.assign("crt", eid)
        new_creator = FakeCreator(ref="hf7y/crt#9")
        closer = FakeCloser()
        ref = filer.file_issue(eid, creator=new_creator, closer=closer)

        self.assertEqual(ref, "hf7y/crt#9")
        self.assertEqual(new_creator.calls[0][0], "crt")
        self.assertEqual(closer.calls, [("hf7y/realisateur#7", closer.calls[0][1])])
        self.assertIn("hf7y/crt#9", closer.calls[0][1])

    def test_a_retag_to_the_same_repo_is_a_noop(self):
        eid = inbox.record_unclassified("fix the thing", None, "voice", for_agent="realisateur")
        filer.file_issue(eid, creator=FakeCreator(ref="hf7y/realisateur#7"))

        inbox.assign("realisateur", eid)
        creator = FakeCreator()
        closer = FakeCloser()
        self.assertIsNone(filer.file_issue(eid, creator=creator, closer=closer))
        self.assertEqual(creator.calls, [])
        self.assertEqual(closer.calls, [])

    def test_a_close_failure_on_retag_does_not_lose_the_new_filing(self):
        eid = inbox.record_unclassified("fix the thing", None, "voice", for_agent="realisateur")
        filer.file_issue(eid, creator=FakeCreator(ref="hf7y/realisateur#7"))

        inbox.assign("crt", eid)
        new_creator = FakeCreator(ref="hf7y/crt#9")
        closer = FakeCloser(raises=RuntimeError("gh: 404"))
        ref = filer.file_issue(eid, creator=new_creator, closer=closer)

        self.assertEqual(ref, "hf7y/crt#9")
        conn = db.get_conn()
        try:
            filed = conn.execute("SELECT filed_issue FROM inbox WHERE id=?", (eid,)).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(filed, "hf7y/crt#9")

    def test_the_close_comment_never_carries_the_transcript(self):
        secret = "the safe combination is one two three"
        eid = inbox.record_unclassified(secret, None, "voice", for_agent="realisateur")
        filer.file_issue(eid, creator=FakeCreator(ref="hf7y/realisateur#7"))

        inbox.assign("crt", eid)
        closer = FakeCloser()
        filer.file_issue(eid, creator=FakeCreator(ref="hf7y/crt#9"), closer=closer)
        self.assertNotIn(secret, closer.calls[0][1])


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
        fake = FakeCreator()
        filed = filer.file_pending(creator=fake)
        self.assertEqual(set(filed), {a, b})
        self.assertEqual(len(fake.calls), 2)

    def test_does_not_refile_what_is_already_filed(self):
        a = inbox.record_unclassified("first", None, "voice", for_agent="realisateur")
        filer.file_issue(a, creator=FakeCreator())
        fake = FakeCreator()
        self.assertEqual(filer.file_pending(creator=fake), [])
        self.assertEqual(fake.calls, [])

    def test_nothing_pending_is_a_noop(self):
        self.assertEqual(filer.file_pending(creator=FakeCreator()), [])


if __name__ == "__main__":
    unittest.main()
