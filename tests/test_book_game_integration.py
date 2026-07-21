#!/usr/bin/env python3
# End-to-end offline integration test for the Book Game funnel
# (.claude/FOCUS.md's 2026-07-21 end-goal: idle-bait -> scan -> question
# -> spoken answer -> STT training log -> actionable fixup). Every piece
# already has its own unit tests against synthetic fixtures; this file's
# job is different -- it runs SEVERAL of those pieces together against
# one shared books.db + training.jsonl, the way they'd actually interact
# live, to catch data-shape mismatches unit tests (each mocking its own
# neighbor) can't see. No mic/tmux/network -- pure sqlite + JSONL, same
# offline-safe bar as everything else in this project.
#
# Covers: crt-book-game.py (registration/quote/lcc) -> crt-book-console.py
# (scan handling) -> crt-book-answer-listen.py (grading against a
# pending question) -> crt-book-game-stats.py (summarizing the result and
# exporting a candidate fixup from a repeated mismatch).
import importlib.util
import json
import os
import tempfile
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(BIN_DIR, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bg = _load("crt_book_game", "crt-book-game.py")
bc = _load("crt_book_console", "crt-book-console.py")
al = _load("crt_book_answer_listen", "crt-book-answer-listen.py")
st = _load("crt_book_game_stats", "crt-book-game-stats.py")


class TestFullFunnelOfflineIntegration(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "books.db")
        self.training_log = os.path.join(self.tmpdir, "training.jsonl")
        # All four modules loaded their own module-level TRAINING_LOG/
        # DB_PATH default from env at import time -- point each one's
        # relevant globals at this test's shared temp files directly,
        # same pattern individual test files already use.
        bg.TRAINING_LOG = self.training_log
        al.bg.TRAINING_LOG = self.training_log
        st.TRAINING_LOG = self.training_log

    def _fetcher(self, title="Dune", year="1965", subjects=None):
        return lambda url: {
            "title": title, "author_names": ["Frank Herbert"],
            "publish_date": year, "subjects": subjects or ["Science fiction"],
        }

    def _quote_fetcher_no_results(self, url):
        return {"query": {"search": []}}

    def test_scan_then_correct_answer_flows_through_every_stage(self):
        conn = bg.get_db(self.db_path)

        # Stage 1: a scan arrives (crt-book-console.py's handle_scan --
        # the same path both the scanner.log tail and stdin reader use).
        row = bc.handle_scan(conn, "9780441013593",
                              fetcher=self._fetcher(), quote_fetcher=self._quote_fetcher_no_results)
        self.assertEqual(row["title"], "Dune")
        question = bg.render_question_screen(row["title"], json.loads(row["questions_json"])[0])
        self.assertEqual(len(question), 15)  # renders a real 40x15 screen, doesn't crash

        # Stage 2: a spoken answer arrives (crt-book-answer-listen.py),
        # graded against the book scanned within the answer window.
        grade = al.grade_pending_answer(conn, "fiction", window_secs=20, now=al._parse_iso_utc(row["first_scanned"]))
        self.assertIsNotNone(grade)
        self.assertEqual(grade["title"], "Dune")

        # Stage 3: the announcement (personality voice) renders without
        # crashing on a real grade dict from stage 2 (not a synthetic one).
        line = al.format_result_line(grade)
        self.assertIn("Dune", line)

        # Stage 4: stats/export see the real logged row.
        rows = st.load_training_rows(self.training_log)
        self.assertEqual(len(rows), 1)
        training_stats = st.summarize_training(rows)
        self.assertEqual(training_stats["total_rounds"], 1)

        # Stage 5: a re-scan of the same ISBN must be a pure cache hit --
        # no second network call, no duplicate question/quote generation.
        boom = lambda url: (_ for _ in ()).throw(AssertionError("must not refetch"))
        row2 = bc.handle_scan(conn, "9780441013593", fetcher=boom, quote_fetcher=boom)
        self.assertEqual(row2["title"], "Dune")

    def test_repeated_mismatch_surfaces_as_candidate_fixup(self):
        conn = bg.get_db(self.db_path)
        isbns = ["1111111111", "2222222222", "3333333333"]
        for isbn in isbns:
            book = {"isbn": isbn, "title": "Book " + isbn, "authors": ["A"], "year": 2000,
                    "subjects": ["Science fiction"], "raw": {}}
            q = {"text": "Fiction or nonfiction?", "options": ["fiction", "nonfiction"], "correct": "fiction"}
            row = bg.register_book(conn, book, questions=[q], question_source="template")
            grade = bg.grade_answer(expected="fiction", heard="friction", correct_option="fiction")
            bg.log_training_row(isbn, grade)

        rows = st.load_training_rows(self.training_log)
        self.assertEqual(len(rows), 3)
        mismatches = st.summarize_training(rows)["mismatches"]
        candidates = st.generate_candidate_fixups(mismatches)
        self.assertIn("friction", candidates)
        self.assertEqual(candidates["friction"]["intent"], "fiction")

    def test_ungradeable_question_path_never_crashes_downstream(self):
        # A book with no usable facts falls back to the "have you read
        # this before" question (correct=None) -- confirm grading,
        # announcing, and stats all handle that gracefully end to end.
        conn = bg.get_db(self.db_path)
        fetcher = lambda url: {"title": "Mystery Book"}  # no year/authors/subjects
        row = bc.handle_scan(conn, "9999999999", fetcher=fetcher, quote_fetcher=self._quote_fetcher_no_results)
        grade = al.grade_pending_answer(conn, "yes", window_secs=20, now=al._parse_iso_utc(row["first_scanned"]))
        self.assertIsNotNone(grade)
        self.assertIsNone(grade["correct_content"])
        line = al.format_result_line(grade)
        self.assertIn("logged your answer", line)
        stats = st.summarize_training(st.load_training_rows(self.training_log))
        self.assertEqual(stats["total_rounds"], 1)
        self.assertEqual(stats["content_known"], 0)


if __name__ == "__main__":
    unittest.main()
