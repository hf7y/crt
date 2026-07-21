#!/usr/bin/env python3
# Tests for bin/crt-book-game.py's offline-safe slice (BOOK-GAME.md,
# .claude/FOCUS.md 2026-07-21). No hardware, no live network -- HTTP is
# mocked via the injectable `fetcher` param.
import importlib.util
import json
import os
import random
import sqlite3
import sys
import tempfile
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")
spec = importlib.util.spec_from_file_location("crt_book_game", os.path.join(BIN_DIR, "crt-book-game.py"))
bg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bg)


SAMPLE = {
    "title": "The Left Hand of Darkness",
    "author_names": ["Ursula K. Le Guin"],
    "publish_date": "1969",
    "subjects": ["Science fiction", "Gender"],
}


class TestMetadataLookup(unittest.TestCase):
    def test_fetch_parses_fields(self):
        book = bg.fetch_book_metadata("9780441478125", fetcher=lambda url: SAMPLE)
        self.assertEqual(book["title"], "The Left Hand of Darkness")
        self.assertEqual(book["authors"], ["Ursula K. Le Guin"])
        self.assertEqual(book["year"], 1969)
        self.assertIn("Science fiction", book["subjects"])

    def test_fetch_handles_missing_fields(self):
        book = bg.fetch_book_metadata("000", fetcher=lambda url: {})
        self.assertEqual(book["title"], "Unknown title")
        self.assertEqual(book["authors"], ["Unknown"])
        self.assertIsNone(book["year"])


class TestQuestionGeneration(unittest.TestCase):
    def setUp(self):
        self.book = bg.fetch_book_metadata("x", fetcher=lambda url: SAMPLE)
        self.rng = random.Random(1)

    def test_template_question_has_two_options(self):
        q = bg.generate_template_question(self.book, rng=self.rng)
        self.assertEqual(len(q["options"]), 2)
        self.assertIn(q["correct"], q["options"] + [None])

    def test_fallback_question_when_no_facts(self):
        bare = {"title": "Mystery Book", "authors": ["Unknown"], "year": None, "subjects": []}
        q = bg.generate_template_question(bare, rng=self.rng)
        self.assertEqual(len(q["options"]), 2)

    def test_source_coin_flip_respects_rate(self):
        rng = random.Random(42)
        self.assertEqual(bg.pick_question_source(rng=rng, claude_rate=0.0), "template")
        rng = random.Random(42)
        self.assertEqual(bg.pick_question_source(rng=rng, claude_rate=1.0), "claude")

    def test_batch_prompt_includes_all_books(self):
        payload = bg.build_claude_batch_prompt([self.book, {"isbn": "y", "title": "Other"}])
        isbns = [b["isbn"] for b in payload["books"]]
        self.assertIn(self.book["isbn"], isbns)
        self.assertIn("y", isbns)

    def test_parse_batch_response_filters_malformed(self):
        resp = {"123": [{"text": "q1", "options": ["a", "b"], "correct": "a"}, {"text": "bad"}]}
        questions = bg.parse_claude_batch_response(resp, "123")
        self.assertEqual(len(questions), 1)

    def test_parse_batch_response_missing_isbn(self):
        self.assertEqual(bg.parse_claude_batch_response({}, "nope"), [])


class TestGrading(unittest.TestCase):
    def test_exact_match_both_correct(self):
        g = bg.grade_answer(expected="fiction", heard="fiction", correct_option="fiction")
        self.assertTrue(g["correct_stt"])
        self.assertTrue(g["correct_content"])

    def test_mismatch_flagged_not_fuzzy(self):
        g = bg.grade_answer(expected="fiction", heard="friction", correct_option="fiction")
        self.assertFalse(g["correct_stt"])
        self.assertFalse(g["correct_content"])

    def test_normalize_ignores_case_and_punctuation(self):
        g = bg.grade_answer(expected="Fiction!", heard="fiction", correct_option="Fiction!")
        self.assertTrue(g["correct_stt"])

    def test_ungradeable_when_no_correct_option(self):
        g = bg.grade_answer(expected="yes", heard="yes", correct_option=None)
        self.assertIsNone(g["correct_content"])
        self.assertTrue(g["correct_stt"])

    def test_log_training_row_writes_jsonl(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "training.jsonl")
            g = bg.grade_answer(expected="fiction", heard="friction", correct_option="fiction")
            bg.log_training_row("123", g, log_path=log_path, timestamp="2026-07-21T00:00:00")
            with open(log_path) as f:
                row = json.loads(f.readline())
            self.assertEqual(row["isbn"], "123")
            self.assertFalse(row["correct_stt"])


class TestLCC(unittest.TestCase):
    def test_fiction_maps_to_ps_pr(self):
        self.assertEqual(bg.compute_lcc(["Science fiction"]), "PS/PR")

    def test_history_maps_to_d(self):
        self.assertEqual(bg.compute_lcc(["World history"]), "D")

    def test_unknown_subject_returns_none(self):
        self.assertIsNone(bg.compute_lcc(["Unclassifiable nonsense subject"]))

    def test_empty_subjects_returns_none(self):
        self.assertIsNone(bg.compute_lcc([]))


class TestRegistry(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "books.db")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_register_and_fetch_book(self):
        conn = bg.get_db(self.db_path)
        book = bg.fetch_book_metadata("x", fetcher=lambda url: SAMPLE)
        book["isbn"] = "9780441478125"
        row = bg.register_book(conn, book, questions=[{"text": "q", "options": ["a", "b"], "correct": "a"}],
                                question_source="template", timestamp="2026-07-21T00:00:00")
        self.assertEqual(row["title"], "The Left Hand of Darkness")
        self.assertEqual(row["lcc"], "PS/PR")

    def test_reregister_is_cached_not_overwritten(self):
        conn = bg.get_db(self.db_path)
        book = {"isbn": "1", "title": "First", "authors": ["A"], "year": 2000, "subjects": [], "raw": {}}
        bg.register_book(conn, book, questions=[{"text": "q1"}], question_source="template")
        book2 = {"isbn": "1", "title": "Should Not Overwrite", "authors": ["B"], "year": 2001, "subjects": [], "raw": {}}
        row = bg.register_book(conn, book2, questions=[{"text": "q2"}], question_source="claude")
        self.assertEqual(row["title"], "First")

    def test_get_missing_book_returns_none(self):
        conn = bg.get_db(self.db_path)
        self.assertIsNone(bg.get_book(conn, "nope"))


class TestScreenLayout(unittest.TestCase):
    def test_center_text_pads_both_sides(self):
        self.assertEqual(bg.center_text("hi", 6), "  hi  ")

    def test_center_text_truncates_overlength(self):
        self.assertEqual(bg.center_text("this is way too long", 5), "this ")

    def test_render_question_screen_dimensions(self):
        q = {"text": "Fiction or nonfiction?", "options": ["fiction", "nonfiction"]}
        lines = bg.render_question_screen("Dune", q, width=40, height=15)
        self.assertEqual(len(lines), 15)
        self.assertTrue(all(len(l) == 40 for l in lines))

    def test_render_question_screen_title_on_top(self):
        q = {"text": "Fiction or nonfiction?", "options": ["fiction", "nonfiction"]}
        lines = bg.render_question_screen("Dune", q, width=40, height=15)
        self.assertIn("Dune", lines[0])

    def test_render_question_screen_options_centered_somewhere(self):
        q = {"text": "Q?", "options": ["yes", "no"]}
        lines = bg.render_question_screen("T", q, width=20, height=10)
        self.assertTrue(any("yes / no" in l for l in lines))


class TestColorAndArt(unittest.TestCase):
    def test_wrap_color_adds_reset(self):
        wrapped = bg.wrap_color("hi", bg.COLOR_QUESTION)
        self.assertTrue(wrapped.startswith(bg.COLOR_QUESTION))
        self.assertTrue(wrapped.endswith(bg.COLOR_RESET))

    def test_no_bright_ansi_codes_in_palette(self):
        # 91/92/93/94 etc (bright primaries) are exactly the CRT-bleed
        # colors this palette is designed to avoid -- see the flag
        # comment above the palette in crt-book-game.py and in CLAUDE.md.
        palette = [bg.COLOR_QUESTION, bg.COLOR_CORRECT, bg.COLOR_WRONG, bg.COLOR_QUOTE, bg.COLOR_TITLE]
        for code in palette:
            self.assertNotRegex(code, r"\033\[9\d")

    def test_get_ascii_art_known_name(self):
        art = bg.get_ascii_art("book")
        self.assertIsNotNone(art)
        self.assertLessEqual(max(len(l) for l in art.splitlines()), 40)

    def test_get_ascii_art_unknown_name(self):
        self.assertIsNone(bg.get_ascii_art("nonexistent"))


class TestIdleQuotes(unittest.TestCase):
    def test_extract_quote_from_dict_form(self):
        self.assertEqual(bg.extract_quote({"first_sentence": {"value": "It was a dark night."}}),
                          "It was a dark night.")

    def test_extract_quote_from_string_form(self):
        self.assertEqual(bg.extract_quote({"first_sentence": "Call me Ishmael."}), "Call me Ishmael.")

    def test_extract_quote_missing(self):
        self.assertIsNone(bg.extract_quote({}))
        self.assertIsNone(bg.extract_quote(None))

    def test_pick_idle_quote_empty_registry(self):
        with tempfile.TemporaryDirectory() as d:
            conn = bg.get_db(os.path.join(d, "books.db"))
            self.assertIsNone(bg.pick_idle_quote(conn))

    def test_pick_idle_quote_uses_cached_first_sentence(self):
        with tempfile.TemporaryDirectory() as d:
            conn = bg.get_db(os.path.join(d, "books.db"))
            book = {"isbn": "1", "title": "Moby Dick", "authors": ["H"], "year": 1851,
                    "subjects": [], "raw": {"first_sentence": "Call me Ishmael."}}
            bg.register_book(conn, book, questions=[], question_source="template")
            title, quote = bg.pick_idle_quote(conn)
            self.assertEqual(title, "Moby Dick")
            self.assertEqual(quote, "Call me Ishmael.")

    def test_pick_idle_quote_falls_back_deterministically(self):
        with tempfile.TemporaryDirectory() as d:
            conn = bg.get_db(os.path.join(d, "books.db"))
            book = {"isbn": "2", "title": "No Quote Book", "authors": ["H"], "year": 2000,
                    "subjects": [], "raw": {}}
            bg.register_book(conn, book, questions=[], question_source="template")
            title1, quote1 = bg.pick_idle_quote(conn)
            title2, quote2 = bg.pick_idle_quote(conn)
            self.assertIn(quote1, bg.FALLBACK_QUOTES)
            self.assertEqual(quote1, quote2)  # deterministic per-isbn, not re-randomized


class TestScanLineParsing(unittest.TestCase):
    def test_parses_valid_scan_line(self):
        self.assertEqual(bg.parse_scan_line("[scan] 9780141439518"), "9780141439518")

    def test_parses_10_digit_isbn_with_check_x(self):
        self.assertEqual(bg.parse_scan_line("[scan] 123456789X"), "123456789X")

    def test_rejects_non_scan_line(self):
        self.assertIsNone(bg.parse_scan_line("hello there"))

    def test_rejects_scan_line_with_non_isbn_text(self):
        self.assertIsNone(bg.parse_scan_line("[scan] not an isbn"))

    def test_strips_whitespace(self):
        self.assertEqual(bg.parse_scan_line("  [scan] 9780141439518  \n"), "9780141439518")

    def test_is_isbn_like_accepts_bare_isbn(self):
        self.assertTrue(bg.is_isbn_like("9780141439518"))
        self.assertTrue(bg.is_isbn_like("123456789X"))

    def test_is_isbn_like_rejects_garbage(self):
        self.assertFalse(bg.is_isbn_like("not an isbn"))
        self.assertFalse(bg.is_isbn_like(""))


if __name__ == "__main__":
    unittest.main()
