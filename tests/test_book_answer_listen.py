#!/usr/bin/env python3
# Tests for bin/crt-book-answer-listen.py -- closes the "spoken answer"
# link in the Book Game funnel (.claude/FOCUS.md's 2026-07-21 end-goal).
# No live STT/tmux; pure functions + real sqlite against a temp db.
import importlib.util
import json
import os
import tempfile
import time
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")

_bg_spec = importlib.util.spec_from_file_location("crt_book_game", os.path.join(BIN_DIR, "crt-book-game.py"))
bg = importlib.util.module_from_spec(_bg_spec)
_bg_spec.loader.exec_module(bg)

_al_spec = importlib.util.spec_from_file_location("crt_book_answer_listen", os.path.join(BIN_DIR, "crt-book-answer-listen.py"))
al = importlib.util.module_from_spec(_al_spec)
_al_spec.loader.exec_module(al)


class TestParseSttLogLine(unittest.TestCase):
    def test_parses_valid_line(self):
        self.assertEqual(al.parse_stt_log_line("12:34:56  fiction\n"), "fiction")

    def test_rejects_malformed_line(self):
        self.assertIsNone(al.parse_stt_log_line("not a log line"))

    def test_rejects_empty_text(self):
        self.assertIsNone(al.parse_stt_log_line("12:34:56  \n"))


class TestParseIsoUtc(unittest.TestCase):
    def test_parses_valid_timestamp(self):
        self.assertIsInstance(al._parse_iso_utc("2026-07-21T12:00:00"), (int, float))

    def test_none_for_missing(self):
        self.assertIsNone(al._parse_iso_utc(None))
        self.assertIsNone(al._parse_iso_utc(""))

    def test_none_for_malformed(self):
        self.assertIsNone(al._parse_iso_utc("not a timestamp"))


class TestGetPendingQuestion(unittest.TestCase):
    def _register(self, conn, isbn, timestamp):
        book = {"isbn": isbn, "title": "Dune", "authors": ["H"], "year": 1965, "subjects": [], "raw": {}}
        q = {"text": "Fiction or nonfiction?", "options": ["fiction", "nonfiction"], "correct": "fiction"}
        return bg.register_book(conn, book, questions=[q], question_source="template", timestamp=timestamp)

    def test_empty_registry_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            conn = bg.get_db(os.path.join(d, "books.db"))
            self.assertIsNone(al.get_pending_question(conn, window_secs=20))

    def test_recent_scan_is_pending(self):
        with tempfile.TemporaryDirectory() as d:
            conn = bg.get_db(os.path.join(d, "books.db"))
            self._register(conn, "1", "2026-07-21T12:00:00")
            now = al._parse_iso_utc("2026-07-21T12:00:10")  # 10s later
            pending = al.get_pending_question(conn, window_secs=20, now=now)
            self.assertIsNotNone(pending)
            self.assertEqual(pending["isbn"], "1")

    def test_stale_scan_is_not_pending(self):
        with tempfile.TemporaryDirectory() as d:
            conn = bg.get_db(os.path.join(d, "books.db"))
            self._register(conn, "1", "2026-07-21T12:00:00")
            now = al._parse_iso_utc("2026-07-21T12:05:00")  # 5 minutes later
            self.assertIsNone(al.get_pending_question(conn, window_secs=20, now=now))

    def test_no_questions_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            conn = bg.get_db(os.path.join(d, "books.db"))
            book = {"isbn": "1", "title": "Dune", "authors": [], "year": None, "subjects": [], "raw": {}}
            bg.register_book(conn, book, questions=[], question_source="template", timestamp="2026-07-21T12:00:00")
            now = al._parse_iso_utc("2026-07-21T12:00:05")
            self.assertIsNone(al.get_pending_question(conn, window_secs=20, now=now))


class TestGradePendingAnswer(unittest.TestCase):
    def _register(self, conn, timestamp):
        book = {"isbn": "1", "title": "Dune", "authors": ["H"], "year": 1965, "subjects": [], "raw": {}}
        q = {"text": "Fiction or nonfiction?", "options": ["fiction", "nonfiction"], "correct": "fiction"}
        bg.register_book(conn, book, questions=[q], question_source="template", timestamp=timestamp)

    def test_grades_and_logs_when_pending(self):
        with tempfile.TemporaryDirectory() as d:
            conn = bg.get_db(os.path.join(d, "books.db"))
            self._register(conn, "2026-07-21T12:00:00")
            log_path = os.path.join(d, "training.jsonl")
            al.bg.TRAINING_LOG = log_path
            now = al._parse_iso_utc("2026-07-21T12:00:05")
            grade = al.grade_pending_answer(conn, "fiction", window_secs=20, now=now)
            self.assertIsNotNone(grade)
            self.assertTrue(grade["correct_content"])
            with open(log_path) as f:
                rows = [json.loads(l) for l in f if l.strip()]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["isbn"], "1")

    def test_returns_none_when_nothing_pending(self):
        with tempfile.TemporaryDirectory() as d:
            conn = bg.get_db(os.path.join(d, "books.db"))
            self.assertIsNone(al.grade_pending_answer(conn, "fiction", window_secs=20))

    def test_mismatch_still_logged_not_silently_dropped(self):
        with tempfile.TemporaryDirectory() as d:
            conn = bg.get_db(os.path.join(d, "books.db"))
            self._register(conn, "2026-07-21T12:00:00")
            log_path = os.path.join(d, "training.jsonl")
            al.bg.TRAINING_LOG = log_path
            now = al._parse_iso_utc("2026-07-21T12:00:05")
            grade = al.grade_pending_answer(conn, "nonfiction", window_secs=20, now=now)
            self.assertFalse(grade["correct_content"])
            with open(log_path) as f:
                rows = [json.loads(l) for l in f if l.strip()]
            self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()
