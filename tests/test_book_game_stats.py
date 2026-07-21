#!/usr/bin/env python3
# Tests for bin/crt-book-game-stats.py -- summarizes Book Game progress
# toward its actual end-goal (STT training data), see that file's own
# header for why STT accuracy gets top billing over trivia correctness.
import importlib.util
import json
import os
import tempfile
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")

_bg_spec = importlib.util.spec_from_file_location("crt_book_game", os.path.join(BIN_DIR, "crt-book-game.py"))
bg = importlib.util.module_from_spec(_bg_spec)
_bg_spec.loader.exec_module(bg)

_st_spec = importlib.util.spec_from_file_location("crt_book_game_stats", os.path.join(BIN_DIR, "crt-book-game-stats.py"))
st = importlib.util.module_from_spec(_st_spec)
_st_spec.loader.exec_module(st)


class TestLoadTrainingRows(unittest.TestCase):
    def test_missing_file_returns_empty_list(self):
        self.assertEqual(st.load_training_rows("/nonexistent/training.jsonl"), [])

    def test_reads_valid_rows(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "training.jsonl")
            with open(path, "w") as f:
                f.write(json.dumps({"isbn": "1", "correct_stt": True}) + "\n")
                f.write(json.dumps({"isbn": "2", "correct_stt": False}) + "\n")
            rows = st.load_training_rows(path)
            self.assertEqual(len(rows), 2)

    def test_skips_malformed_lines(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "training.jsonl")
            with open(path, "w") as f:
                f.write("not json\n")
                f.write(json.dumps({"isbn": "1", "correct_stt": True}) + "\n")
            rows = st.load_training_rows(path)
            self.assertEqual(len(rows), 1)


class TestSummarizeBooks(unittest.TestCase):
    def test_counts_by_question_source(self):
        with tempfile.TemporaryDirectory() as d:
            conn = bg.get_db(os.path.join(d, "books.db"))
            bg.register_book(conn, {"isbn": "1", "title": "A", "authors": [], "year": None,
                                     "subjects": [], "raw": {}}, questions=[], question_source="template")
            bg.register_book(conn, {"isbn": "2", "title": "B", "authors": [], "year": None,
                                     "subjects": [], "raw": {}}, questions=[], question_source="claude")
            stats = st.summarize_books(conn)
            self.assertEqual(stats["total"], 2)
            self.assertEqual(stats["template_questions"], 1)
            self.assertEqual(stats["claude_questions"], 1)

    def test_empty_registry(self):
        with tempfile.TemporaryDirectory() as d:
            conn = bg.get_db(os.path.join(d, "books.db"))
            stats = st.summarize_books(conn)
            self.assertEqual(stats["total"], 0)


class TestSummarizeTraining(unittest.TestCase):
    def test_empty_rows(self):
        stats = st.summarize_training([])
        self.assertEqual(stats["total_rounds"], 0)
        self.assertIsNone(stats["stt_accuracy"])
        self.assertIsNone(stats["content_accuracy"])

    def test_computes_stt_accuracy(self):
        rows = [
            {"correct_stt": True, "correct_content": True},
            {"correct_stt": False, "correct_content": False},
            {"correct_stt": True, "correct_content": None},
        ]
        stats = st.summarize_training(rows)
        self.assertEqual(stats["total_rounds"], 3)
        self.assertEqual(stats["stt_correct"], 2)
        self.assertAlmostEqual(stats["stt_accuracy"], 2 / 3)

    def test_content_accuracy_ignores_ungradeable_rows(self):
        rows = [
            {"correct_stt": True, "correct_content": True},
            {"correct_stt": True, "correct_content": None},  # ungradeable, excluded
        ]
        stats = st.summarize_training(rows)
        self.assertEqual(stats["content_known"], 1)
        self.assertEqual(stats["content_correct"], 1)
        self.assertEqual(stats["content_accuracy"], 1.0)

    def test_mismatches_collected(self):
        rows = [
            {"isbn": "1", "expected": "fiction", "heard": "friction", "correct_stt": False},
            {"isbn": "2", "expected": "yes", "heard": "yes", "correct_stt": True},
        ]
        stats = st.summarize_training(rows)
        self.assertEqual(len(stats["mismatches"]), 1)
        self.assertEqual(stats["mismatches"][0]["isbn"], "1")


class TestRenderScreenSummary(unittest.TestCase):
    def test_no_data_yet(self):
        book_stats = {"total": 0}
        training_stats = st.summarize_training([])
        lines = st.render_screen_summary(book_stats, training_stats, width=40)
        self.assertTrue(any("No spoken answers" in l for l in lines))

    def test_with_data(self):
        book_stats = {"total": 3}
        training_stats = st.summarize_training([{"correct_stt": True, "correct_content": True}])
        lines = st.render_screen_summary(book_stats, training_stats, width=40)
        self.assertTrue(any("3 book(s)" in l for l in lines))
        self.assertTrue(any("STT accuracy" in l for l in lines))

    def test_lines_never_exceed_width(self):
        book_stats = {"total": 999}
        training_stats = st.summarize_training([{"correct_stt": True, "correct_content": True}] * 50)
        lines = st.render_screen_summary(book_stats, training_stats, width=20)
        self.assertTrue(all(len(l) <= 20 for l in lines))


class TestGenerateCandidateFixups(unittest.TestCase):
    def test_single_occurrence_not_surfaced(self):
        mismatches = [{"heard": "friction", "expected": "fiction"}]
        self.assertEqual(st.generate_candidate_fixups(mismatches), {})

    def test_repeated_pair_surfaced_as_candidate(self):
        mismatches = [
            {"heard": "friction", "expected": "fiction"},
            {"heard": "friction", "expected": "fiction"},
        ]
        candidates = st.generate_candidate_fixups(mismatches)
        self.assertIn("friction", candidates)
        self.assertEqual(candidates["friction"]["intent"], "fiction")
        self.assertEqual(candidates["friction"]["confidence"], "candidate")

    def test_min_repeats_is_tunable(self):
        mismatches = [{"heard": "x", "expected": "y"}]
        self.assertEqual(st.generate_candidate_fixups(mismatches, min_repeats=1), {"x": {
            "intent": "y", "type": "book-game-observed", "confidence": "candidate",
            "note": st.generate_candidate_fixups(mismatches, min_repeats=1)["x"]["note"],
        }})

    def test_ignores_missing_or_identical_fields(self):
        mismatches = [
            {"heard": "", "expected": "fiction"},
            {"heard": "fiction", "expected": ""},
            {"heard": "same", "expected": "same"},
        ]
        self.assertEqual(st.generate_candidate_fixups(mismatches, min_repeats=1), {})

    def test_case_insensitive_grouping(self):
        mismatches = [
            {"heard": "Friction", "expected": "Fiction"},
            {"heard": "friction", "expected": "fiction"},
        ]
        candidates = st.generate_candidate_fixups(mismatches)
        self.assertIn("friction", candidates)
        self.assertEqual(len(candidates), 1)


class TestRenderFullReport(unittest.TestCase):
    def test_includes_mismatches(self):
        book_stats = {"total": 1, "template_questions": 1, "claude_questions": 0}
        rows = [{"isbn": "1", "expected": "fiction", "heard": "friction", "correct_stt": False, "correct_content": False}]
        training_stats = st.summarize_training(rows)
        report = st.render_full_report(book_stats, training_stats)
        self.assertIn("friction", report)
        self.assertIn("fiction", report)

    def test_nothing_graded_yet_message(self):
        book_stats = {"total": 0, "template_questions": 0, "claude_questions": 0}
        report = st.render_full_report(book_stats, st.summarize_training([]))
        self.assertIn("Nothing graded yet", report)


if __name__ == "__main__":
    unittest.main()
