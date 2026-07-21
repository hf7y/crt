#!/usr/bin/env python3
# Tests for bin/crt-book-console.py's pure functions (parsing, rendering,
# scan-handling) -- see BOOK-GAME-STYLE.md. No tmux, no live terminal;
# the tail-follow loop / draw() itself is exercised only by inspection,
# same acceptance bar as every other crt-console.sh window.
import importlib.util
import json
import os
import tempfile
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")

_bg_spec = importlib.util.spec_from_file_location("crt_book_game", os.path.join(BIN_DIR, "crt-book-game.py"))
bg = importlib.util.module_from_spec(_bg_spec)
_bg_spec.loader.exec_module(bg)

_bc_spec = importlib.util.spec_from_file_location("crt_book_console", os.path.join(BIN_DIR, "crt-book-console.py"))
bc = importlib.util.module_from_spec(_bc_spec)
_bc_spec.loader.exec_module(bc)


class TestParseScannerLogLine(unittest.TestCase):
    def test_parses_valid_line(self):
        self.assertEqual(bc.parse_scanner_log_line("2026-07-21T12:00:00\t9780141439518\n"), "9780141439518")

    def test_rejects_no_tab(self):
        self.assertIsNone(bc.parse_scanner_log_line("no tab here"))

    def test_rejects_non_isbn_text(self):
        self.assertIsNone(bc.parse_scanner_log_line("2026-07-21T12:00:00\tnot an isbn"))


class TestRenderIdleScreen(unittest.TestCase):
    def test_dimensions(self):
        lines = bc.render_idle_screen(3, 40, 15)
        self.assertEqual(len(lines), 15)

    def test_mentions_book_count(self):
        lines = bc.render_idle_screen(5, 40, 15)
        self.assertTrue(any("5 book(s)" in l for l in lines))

    def test_colored_with_title_register(self):
        lines = bc.render_idle_screen(0, 40, 15)
        self.assertTrue(all(l.startswith(bg.COLOR_TITLE) for l in lines))


class TestRenderScanResult(unittest.TestCase):
    def test_renders_question_from_row(self):
        row = {"title": "Dune", "questions_json": json.dumps(
            [{"text": "Fiction or nonfiction?", "options": ["fiction", "nonfiction"], "correct": "fiction"}])}
        lines = bc.render_scan_result(row, 40, 15)
        self.assertTrue(any("Dune" in l for l in lines))
        self.assertTrue(any("fiction" in l for l in lines))

    def test_handles_missing_questions(self):
        row = {"title": "Mystery", "questions_json": json.dumps([])}
        lines = bc.render_scan_result(row, 40, 15)
        self.assertTrue(any("no question on file" in l for l in lines))


class TestHandleScan(unittest.TestCase):
    def test_fresh_scan_registers_book(self):
        with tempfile.TemporaryDirectory() as d:
            conn = bg.get_db(os.path.join(d, "books.db"))
            fetcher = lambda url: {"title": "Test Book", "author_names": ["A B"], "publish_date": "1999"}
            row = bc.handle_scan(conn, "123", fetcher=fetcher)
            self.assertEqual(row["title"], "Test Book")

    def test_rescan_reuses_cached_row(self):
        with tempfile.TemporaryDirectory() as d:
            conn = bg.get_db(os.path.join(d, "books.db"))
            fetcher = lambda url: {"title": "Test Book"}
            row1 = bc.handle_scan(conn, "123", fetcher=fetcher)
            row2 = bc.handle_scan(conn, "123", fetcher=lambda url: (_ for _ in ()).throw(AssertionError("should not refetch")))
            self.assertEqual(row1["title"], row2["title"])


if __name__ == "__main__":
    unittest.main()
