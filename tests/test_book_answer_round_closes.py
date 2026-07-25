#!/usr/bin/env python3
# A scan opens ONE graded round, not a 20-second grading window
# (2026-07-25, thirteenth nightly cycle).
#
# crt-book-answer-listen.py derives "a question is pending" from the scan
# timestamp alone: any utterance within CRT_BOOK_ANSWER_WINDOW_SECS (20s)
# of the most recent scan gets graded against that book's question, logged
# as a training row, and announced on the tube. Nothing recorded that the
# round had already been answered, so the window kept grading for its full
# 20 seconds.
#
# That is not a hypothetical "second answer". crt-stt-solo.py writes EVERY
# recognized utterance to ~/.crt/stt.log (crt-stt-solo.py:1332), BEFORE the
# wake gate -- this window is the one consumer in the project that sees
# unaddressed room speech, and CLAUDE.md's whole premise is a room with
# ambient chatter in it. So the utterance that got graded second was
# whatever anyone said next:
#
#   scan -> "fiction" -> tube says "got it!" -> "nice, next one"
#     -> graded -> tube says "nope, it was fiction"
#     -> {"expected": "fiction", "heard": "nice next one"} in
#        book-game-training.jsonl
#
# The 2026-07-21 fix caught the case where that next utterance is a
# recognized voice COMMAND (find_playbook). Ordinary speech is not a
# command, and ordinary speech is most of what a room contains.
#
# book-game-training.jsonl is the artifact this entire subsystem exists to
# produce (.claude/FOCUS.md's 2026-07-21 end-goal statement), so a row whose
# "heard" was never an answer attempt is worse than a missing row: it is
# labelled training data that is mislabelled.
#
# Every test here fails against the parent commit. The load-bearing one is
# test_the_next_utterance_after_a_graded_answer_is_not_graded_again, which
# fails there by finding two rows in the training log where a person gave
# one answer.
import importlib.util
import json
import os
import tempfile
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")

_bg_spec = importlib.util.spec_from_file_location(
    "crt_book_game_round", os.path.join(BIN_DIR, "crt-book-game.py"))
bg = importlib.util.module_from_spec(_bg_spec)
_bg_spec.loader.exec_module(bg)

_al_spec = importlib.util.spec_from_file_location(
    "crt_book_answer_listen_round", os.path.join(BIN_DIR, "crt-book-answer-listen.py"))
al = importlib.util.module_from_spec(_al_spec)
_al_spec.loader.exec_module(al)

QUESTION = {"text": "Fiction or nonfiction?",
            "options": ["fiction", "nonfiction"], "correct": "fiction"}


def _book(isbn, title):
    return {"isbn": isbn, "title": title, "authors": ["H"], "year": 1965,
            "subjects": [], "raw": {}}


class RoundClosesTestCase(unittest.TestCase):
    """Shared fixture: one registered book, a temp training log, and a
    clock we control so 'within the window' is exact rather than timed."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.d = self._tmp.name
        self.conn = bg.get_db(os.path.join(self.d, "books.db"))
        self.log_path = os.path.join(self.d, "training.jsonl")
        # al loads its OWN crt-book-game module object (spec_from_file_location,
        # not import), so al.bg is not this file's bg -- the grading path
        # writes through al.bg.TRAINING_LOG. Patch both so it does not matter
        # which module object a given assertion goes through.
        for mod in (bg, al.bg):
            self.addCleanup(setattr, mod, "TRAINING_LOG", mod.TRAINING_LOG)
            mod.TRAINING_LOG = self.log_path

    def register(self, isbn="1", title="Dune", timestamp="2026-07-21T12:00:00"):
        return bg.register_book(self.conn, _book(isbn, title), questions=[QUESTION],
                                question_source="template", timestamp=timestamp)

    def at(self, iso):
        return al._parse_iso_utc(iso)

    def rows(self):
        if not os.path.exists(self.log_path):
            return []
        with open(self.log_path) as f:
            return [json.loads(l) for l in f if l.strip()]


class TestOneScanIsOneRound(RoundClosesTestCase):
    def test_the_first_utterance_after_a_scan_is_still_graded(self):
        """The fix must not close the round before anyone answers."""
        self.register()
        grade = al.grade_pending_answer(self.conn, "fiction", window_secs=20,
                                        now=self.at("2026-07-21T12:00:05"))
        self.assertIsNotNone(grade)
        self.assertTrue(grade["correct_content"])
        self.assertEqual(len(self.rows()), 1)

    def test_the_next_utterance_after_a_graded_answer_is_not_graded_again(self):
        """The headline case. Someone answers, the tube says 'got it!', and
        then they say something ordinary -- not a command, so the 2026-07-21
        find_playbook() guard does not catch it. Against the parent this
        finds two rows, the second reading heard='nice next one'."""
        self.register()
        al.grade_pending_answer(self.conn, "fiction", window_secs=20,
                                now=self.at("2026-07-21T12:00:05"))
        second = al.grade_pending_answer(self.conn, "nice next one", window_secs=20,
                                         now=self.at("2026-07-21T12:00:09"))
        self.assertIsNone(second, "a closed round must not grade the next utterance")
        rows = self.rows()
        self.assertEqual(len(rows), 1,
                         "one answer must produce one training row, got %r"
                         % [r.get("heard") for r in rows])
        self.assertEqual(rows[0]["heard"], "fiction")

    def test_a_wrong_answer_also_closes_the_round(self):
        """A wrong answer is still an answer -- and the announcement has
        already revealed the correct one ('nope, it was fiction'), so a
        retry would be grading someone reading the answer off the screen."""
        self.register()
        first = al.grade_pending_answer(self.conn, "nonfiction", window_secs=20,
                                        now=self.at("2026-07-21T12:00:05"))
        self.assertFalse(first["correct_content"])
        self.assertIsNone(al.grade_pending_answer(self.conn, "fiction", window_secs=20,
                                                  now=self.at("2026-07-21T12:00:07")))
        self.assertEqual(len(self.rows()), 1)

    def test_get_pending_question_reports_the_round_closed(self):
        """The consumption is visible at the layer that decides, not only as
        a side effect of grading."""
        self.register()
        now = self.at("2026-07-21T12:00:05")
        self.assertIsNotNone(al.get_pending_question(self.conn, 20, now=now))
        al.grade_pending_answer(self.conn, "fiction", window_secs=20, now=now)
        self.assertIsNone(al.get_pending_question(self.conn, 20,
                                                  now=self.at("2026-07-21T12:00:06")))

    def test_a_command_does_not_close_a_round_it_was_never_graded_against(self):
        """find_playbook() utterances return None WITHOUT grading, so they
        must leave the round open for the answer that follows -- otherwise
        this fix would swallow the answer the 2026-07-21 fix protected."""
        self.register()
        self.assertIsNone(al.grade_pending_answer(self.conn, "book game stats",
                                                  window_secs=20,
                                                  now=self.at("2026-07-21T12:00:03")))
        grade = al.grade_pending_answer(self.conn, "fiction", window_secs=20,
                                        now=self.at("2026-07-21T12:00:06"))
        self.assertIsNotNone(grade, "a command must not consume the round")
        self.assertTrue(grade["correct_content"])


class TestRescanReopensTheRound(RoundClosesTestCase):
    """The twelfth cycle made a re-scanned book answerable at all. Closing
    the round must not undo that."""

    def test_a_rescan_after_an_answer_is_pending_again(self):
        self.register()
        al.grade_pending_answer(self.conn, "fiction", window_secs=20,
                                now=self.at("2026-07-21T12:00:05"))
        bg.touch_scan(self.conn, "1", timestamp="2026-07-21T14:00:00")
        pending = al.get_pending_question(self.conn, 20,
                                          now=self.at("2026-07-21T14:00:05"))
        self.assertIsNotNone(pending, "re-scanning must re-open the round")
        self.assertEqual(pending["isbn"], "1")

    def test_the_answer_to_a_rescan_is_graded_and_logged(self):
        self.register()
        al.grade_pending_answer(self.conn, "fiction", window_secs=20,
                                now=self.at("2026-07-21T12:00:05"))
        bg.touch_scan(self.conn, "1", timestamp="2026-07-21T14:00:00")
        grade = al.grade_pending_answer(self.conn, "nonfiction", window_secs=20,
                                        now=self.at("2026-07-21T14:00:04"))
        self.assertIsNotNone(grade)
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual([r["heard"] for r in rows], ["fiction", "nonfiction"])

    def test_a_rescan_closed_again_by_its_own_answer(self):
        """And the re-opened round closes the same way the first one did."""
        self.register()
        al.grade_pending_answer(self.conn, "fiction", window_secs=20,
                                now=self.at("2026-07-21T12:00:05"))
        bg.touch_scan(self.conn, "1", timestamp="2026-07-21T14:00:00")
        al.grade_pending_answer(self.conn, "nonfiction", window_secs=20,
                                now=self.at("2026-07-21T14:00:04"))
        self.assertIsNone(al.grade_pending_answer(self.conn, "and anyway", window_secs=20,
                                                  now=self.at("2026-07-21T14:00:08")))
        self.assertEqual(len(self.rows()), 2)


class TestClosedRoundDoesNotFallThroughToAnotherBook(RoundClosesTestCase):
    """The answered check runs AFTER `LIMIT 1` on purpose. Filtering it in
    SQL would make a closed round fall through to the previously-scanned
    book, if that one is still inside its own window -- grading an utterance
    against a book that is not the one on the tube, which is precisely the
    corrupted row the twelfth cycle fixed."""

    def test_a_closed_round_does_not_grade_against_the_previous_book(self):
        self.register(isbn="1", title="Dune", timestamp="2026-07-21T12:00:00")
        self.register(isbn="2", title="Emma", timestamp="2026-07-21T12:00:04")
        al.grade_pending_answer(self.conn, "fiction", window_secs=20,
                                now=self.at("2026-07-21T12:00:06"))
        rows = self.rows()
        self.assertEqual(rows[0]["isbn"], "2", "graded against the book on the tube")
        self.assertIsNone(
            al.grade_pending_answer(self.conn, "just talking", window_secs=20,
                                    now=self.at("2026-07-21T12:00:08")),
            "must not fall through to the earlier book still inside its window")
        self.assertEqual(len(self.rows()), 1)


class TestMarkAnswered(unittest.TestCase):
    """mark_answered() itself -- the counterpart to touch_scan()."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.conn = bg.get_db(os.path.join(self._tmp.name, "books.db"))

    def test_stamps_last_answered_and_returns_the_row(self):
        bg.register_book(self.conn, _book("1", "Dune"), questions=[QUESTION],
                         question_source="template", timestamp="2026-07-21T12:00:00")
        row = bg.mark_answered(self.conn, "1", timestamp="2026-07-21T12:00:05")
        self.assertEqual(row["last_answered"], "2026-07-21T12:00:05")

    def test_unknown_isbn_returns_none_rather_than_raising(self):
        self.assertIsNone(bg.mark_answered(self.conn, "nope"))

    def test_a_fresh_book_has_never_been_answered(self):
        row = bg.register_book(self.conn, _book("1", "Dune"), questions=[QUESTION],
                               question_source="template", timestamp="2026-07-21T12:00:00")
        self.assertIsNone(row["last_answered"])


class TestExistingDatabasesMigrate(unittest.TestCase):
    """potato's books.db predates this column. Opening it must add the
    column and leave every existing row answerable -- NULL means the round
    is open, which is exactly the pre-column behaviour."""

    def test_a_db_without_the_column_gains_it_and_stays_pending(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "books.db")
            import sqlite3
            legacy = sqlite3.connect(path)
            legacy.execute("CREATE TABLE books (isbn TEXT PRIMARY KEY, title TEXT, "
                           "authors TEXT, year INTEGER, subjects TEXT, raw_json TEXT, "
                           "questions_json TEXT, question_source TEXT, lcc TEXT, "
                           "quote TEXT, label_printed INTEGER DEFAULT 0, "
                           "first_scanned TEXT)")
            legacy.execute("INSERT INTO books (isbn, title, questions_json, first_scanned) "
                           "VALUES (?, ?, ?, ?)",
                           ("1", "Dune", json.dumps([QUESTION]), "2026-07-21T12:00:00"))
            legacy.commit()
            legacy.close()

            conn = bg.get_db(path)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(books)")}
            self.assertIn("last_answered", cols)
            self.assertIn("last_scanned", cols)
            pending = al.get_pending_question(conn, 20,
                                              now=al._parse_iso_utc("2026-07-21T12:00:05"))
            self.assertIsNotNone(pending, "a legacy row must still be answerable")
            self.assertEqual(pending["isbn"], "1")


class TestIsoUtcRoundTrip(unittest.TestCase):
    """_iso_utc/_parse_iso_utc have to agree, or a round closed at an
    explicit `now` would stamp a time that does not compare against the
    scan it closed."""

    def test_round_trips_through_parse(self):
        iso = "2026-07-21T12:00:05"
        self.assertEqual(al._iso_utc(al._parse_iso_utc(iso)), iso)

    def test_closing_uses_the_passed_clock_not_the_wall_clock(self):
        with tempfile.TemporaryDirectory() as d:
            conn = bg.get_db(os.path.join(d, "books.db"))
            real_log, al.bg.TRAINING_LOG = al.bg.TRAINING_LOG, os.path.join(d, "t.jsonl")
            try:
                bg.register_book(conn, _book("1", "Dune"), questions=[QUESTION],
                                 question_source="template",
                                 timestamp="2026-07-21T12:00:00")
                al.grade_pending_answer(conn, "fiction", window_secs=20,
                                        now=al._parse_iso_utc("2026-07-21T12:00:05"))
            finally:
                al.bg.TRAINING_LOG = real_log
            self.assertEqual(bg.get_book(conn, "1")["last_answered"],
                             "2026-07-21T12:00:05")


if __name__ == "__main__":
    unittest.main()
