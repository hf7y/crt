#!/usr/bin/env python3
# Tests for bin/crt-book-idle-bait.py's pure formatting function -- see
# BOOK-GAME-STYLE.md's "Idle-bait quotes" section.
import importlib.util
import os
import random
import tempfile
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")

_bg_spec = importlib.util.spec_from_file_location("crt_book_game", os.path.join(BIN_DIR, "crt-book-game.py"))
bg = importlib.util.module_from_spec(_bg_spec)
_bg_spec.loader.exec_module(bg)

_ib_spec = importlib.util.spec_from_file_location("crt_book_idle_bait", os.path.join(BIN_DIR, "crt-book-idle-bait.py"))
ib = importlib.util.module_from_spec(_ib_spec)
_ib_spec.loader.exec_module(ib)


class TestIdleBaitFormatting(unittest.TestCase):
    def test_empty_registry_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            conn = bg.get_db(os.path.join(d, "books.db"))
            self.assertIsNone(ib.pick_and_format_quote_line(conn))

    def test_line_includes_title_and_quote_colors(self):
        with tempfile.TemporaryDirectory() as d:
            conn = bg.get_db(os.path.join(d, "books.db"))
            book = {"isbn": "1", "title": "Dune", "authors": ["H"], "year": 1965,
                    "subjects": [], "raw": {"first_sentence": "In the week before their departure..."}}
            bg.register_book(conn, book, questions=[], question_source="template")
            line = ib.pick_and_format_quote_line(conn, rng=random.Random(1))
            self.assertIn("Dune", line)
            self.assertIn("In the week before their departure...", line)
            self.assertTrue(line.startswith(bg.COLOR_QUOTE))
            self.assertTrue(line.endswith(bg.COLOR_RESET))


if __name__ == "__main__":
    unittest.main()
