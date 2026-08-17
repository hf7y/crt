#!/usr/bin/env python3
# A book can be answered more than once (2026-07-25, twelfth nightly cycle).
#
# The Book Game funnel is idle-bait -> scan -> question -> SPOKEN ANSWER ->
# STT training log, and its whole premise is a shelf of books someone picks
#   [rest: vault:crt/header-archaeology-20260817.md]
import importlib.util
import json
import os
import tempfile
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, os.path.join(BIN_DIR, path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bg = _load("crt_book_game_rescan", "crt-book-game.py")
al = _load("crt_book_answer_listen_rescan", "crt-book-answer-listen.py")
console = _load("crt_book_console_rescan", "crt-book-console.py")

DUNE = {"isbn": "1", "title": "Dune", "authors": ["H"], "year": 1965,
        "subjects": [], "raw": {}}
OTHER = {"isbn": "2", "title": "Emma", "authors": ["A"], "year": 1815,
         "subjects": [], "raw": {}}
DUNE_Q = {"text": "Fiction or nonfiction?",
          "options": ["fiction", "nonfiction"], "correct": "fiction"}
OTHER_Q = {"text": "1815 or 1915?", "options": ["1815", "1915"],
           "correct": "1815"}


class RescanTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.d = self._tmp.name
        self.conn = bg.get_db(os.path.join(self.d, "books.db"))
        self.training_log = os.path.join(self.d, "training.jsonl")
        bg.TRAINING_LOG = self.training_log
        al.bg.TRAINING_LOG = self.training_log

    def register(self, book, question, timestamp):
        return bg.register_book(self.conn, book, questions=[question],
                                question_source="template", timestamp=timestamp)

    def at(self, iso):
        return al._parse_iso_utc(iso)

    def training_rows(self):
        if not os.path.exists(self.training_log):
            return []
        with open(self.training_log) as f:
            return [json.loads(line) for line in f if line.strip()]


class TestTouchScan(RescanTestCase):
    def test_touch_scan_records_a_rescan_without_disturbing_the_row(self):
        self.register(DUNE, DUNE_Q, "2026-07-21T12:00:00")
        row = bg.touch_scan(self.conn, "1", timestamp="2026-07-25T09:00:00")
        self.assertEqual(row["first_scanned"], "2026-07-21T12:00:00")
        self.assertEqual(row["last_scanned"], "2026-07-25T09:00:00")
        # The cache is the point of register_book's re-scan branch: the
        # question, quote and LCC must survive a touch untouched.
        self.assertEqual(json.loads(row["questions_json"]), [DUNE_Q])
        self.assertEqual(row["title"], "Dune")

    def test_touch_scan_on_an_unregistered_isbn_is_a_no_op(self):
        self.assertIsNone(bg.touch_scan(self.conn, "9780000000000"))

    def test_a_first_registration_sets_both_timestamps(self):
        row = self.register(DUNE, DUNE_Q, "2026-07-21T12:00:00")
        self.assertEqual(row["last_scanned"], "2026-07-21T12:00:00")


class TestRescannedBookIsPending(RescanTestCase):
    def test_a_rescanned_book_is_pending_again(self):
        self.register(DUNE, DUNE_Q, "2026-07-21T12:00:00")   # days ago
        bg.touch_scan(self.conn, "1", timestamp="2026-07-25T09:00:00")
        pending = al.get_pending_question(self.conn, window_secs=20,
                                          now=self.at("2026-07-25T09:00:05"))
        self.assertIsNotNone(pending)
        self.assertEqual(pending["isbn"], "1")

    def test_a_rescan_that_has_gone_stale_is_not_pending(self):
        # The window still closes -- re-scanning must not mean "pending
        # forever", or every later utterance in the room gets graded.
        self.register(DUNE, DUNE_Q, "2026-07-21T12:00:00")
        bg.touch_scan(self.conn, "1", timestamp="2026-07-25T09:00:00")
        self.assertIsNone(al.get_pending_question(
            self.conn, window_secs=20, now=self.at("2026-07-25T09:05:00")))

    def test_a_row_predating_the_column_still_answers_for_its_first_scan(self):
        # potato's real books.db has rows with last_scanned NULL. COALESCE,
        # not a backfill: those must behave exactly as they did before.
        self.register(DUNE, DUNE_Q, "2026-07-21T12:00:00")
        self.conn.execute("UPDATE books SET last_scanned = NULL")
        self.conn.commit()
        pending = al.get_pending_question(self.conn, window_secs=20,
                                          now=self.at("2026-07-21T12:00:10"))
        self.assertIsNotNone(pending)
        self.assertEqual(pending["isbn"], "1")

    def test_the_rescanned_book_wins_over_a_newer_registration(self):
        # The failure that corrupts data rather than losing it: Emma was
        # registered more recently, so before last_scanned existed she was
        # the only book this query could ever return.
        self.register(DUNE, DUNE_Q, "2026-07-21T12:00:00")
        self.register(OTHER, OTHER_Q, "2026-07-25T08:59:50")
        bg.touch_scan(self.conn, "1", timestamp="2026-07-25T09:00:00")
        pending = al.get_pending_question(self.conn, window_secs=20,
                                          now=self.at("2026-07-25T09:00:05"))
        self.assertEqual(pending["isbn"], "1")
        self.assertEqual(pending["question"], DUNE_Q)


class TestGradingThroughTheLivePath(RescanTestCase):
    """Everything here goes through crt-book-console.py's real handle_scan --
    the `book` tmux window's own scan handler -- so each failure against the
    parent is the symptom someone standing at the console would get, not an
    AttributeError about a function that does not exist there yet. The clock
    is real, because handle_scan stamps _now_iso(); the answer window is
    widened instead, which is what a test can honestly control."""

    def rescan(self, isbn):
        def fetcher(*a, **kw):
            raise AssertionError("a re-scan must not re-query Open Library")

        return console.handle_scan(self.conn, isbn, fetcher=fetcher,
                                   quote_fetcher=fetcher,
                                   training_log_path=self.training_log)

    def test_rescanning_makes_the_question_pending_again(self):
        self.register(DUNE, DUNE_Q, "2026-07-21T12:00:00")   # days ago
        row = self.rescan("1")
        self.assertEqual(row["title"], "Dune")
        self.assertEqual(json.loads(row["questions_json"]), [DUNE_Q])
        pending = al.get_pending_question(self.conn, window_secs=60)
        self.assertIsNotNone(pending)
        self.assertEqual(pending["isbn"], "1")

    def test_the_spoken_answer_to_a_rescan_is_graded_and_logged(self):
        self.register(DUNE, DUNE_Q, "2026-07-21T12:00:00")
        self.rescan("1")
        grade = al.grade_pending_answer(self.conn, "fiction", window_secs=60)
        self.assertIsNotNone(grade)
        self.assertTrue(grade["correct_content"])
        self.assertEqual(grade["title"], "Dune")
        self.assertEqual([r["isbn"] for r in self.training_rows()], ["1"])

    def test_an_answer_is_never_graded_against_a_different_books_question(self):
        # The corrupted-training-row case, end to end: Emma was registered a
        # moment ago, Dune is re-scanned, "fiction" is spoken. Against the
        # parent the re-scan leaves no timestamp, Emma is the most recent
        # thing this query can see, and "fiction" is logged as a wrong answer
        # to "1815 or 1915?" under Emma's ISBN -- then announced on the tube
        # as "nope, it was 1815" for a question nobody was asked.
        self.register(DUNE, DUNE_Q, "2026-07-21T12:00:00")
        self.register(OTHER, OTHER_Q, bg._now_iso())
        self.rescan("1")
        grade = al.grade_pending_answer(self.conn, "fiction", window_secs=60)
        self.assertEqual(grade["expected"], "fiction")
        self.assertTrue(grade["correct_content"])
        self.assertEqual([r["isbn"] for r in self.training_rows()], ["1"])


if __name__ == "__main__":
    unittest.main()
