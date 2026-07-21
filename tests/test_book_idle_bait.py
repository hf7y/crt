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
    def test_empty_registry_returns_enticement_not_none(self):
        # 2026-07-21: an empty registry used to mean this silently
        # produced nothing -- now it always shows a "come scan a book"
        # nudge, since that's the actual point of this feature.
        with tempfile.TemporaryDirectory() as d:
            conn = bg.get_db(os.path.join(d, "books.db"))
            line = ib.pick_and_format_line(conn, rng=random.Random(1))
            self.assertIsNotNone(line)
            self.assertTrue(line.startswith(bg.COLOR_QUESTION))

    def test_populated_registry_can_still_show_quote(self):
        with tempfile.TemporaryDirectory() as d:
            conn = bg.get_db(os.path.join(d, "books.db"))
            book = {"isbn": "1", "title": "Dune", "authors": ["H"], "year": 1965,
                    "subjects": [], "raw": {"first_sentence": "In the week before their departure..."}}
            bg.register_book(conn, book, questions=[], question_source="template")
            ib.ENTICE_RATE = 0.0  # force the quote branch for this assertion
            line = ib.pick_and_format_line(conn, rng=random.Random(1))
            self.assertIn("Dune", line)
            self.assertIn("In the week before their departure...", line)
            self.assertTrue(line.startswith(bg.COLOR_QUOTE))
            self.assertTrue(line.endswith(bg.COLOR_RESET))

    def test_populated_registry_can_still_show_enticement(self):
        with tempfile.TemporaryDirectory() as d:
            conn = bg.get_db(os.path.join(d, "books.db"))
            book = {"isbn": "1", "title": "Dune", "authors": ["H"], "year": 1965,
                    "subjects": [], "raw": {}}
            bg.register_book(conn, book, questions=[], question_source="template")
            ib.ENTICE_RATE = 1.0  # force the enticement branch for this assertion
            line = ib.pick_and_format_line(conn, rng=random.Random(1))
            self.assertTrue(line.startswith(bg.COLOR_QUESTION))


class TestAppendThoughtLine(unittest.TestCase):
    def test_writes_to_thought_log(self):
        with tempfile.TemporaryDirectory() as d:
            ib.THOUGHT_LOG = os.path.join(d, "thoughts.log")
            ib.append_thought_line("a test line")
            with open(ib.THOUGHT_LOG) as f:
                content = f.read()
            self.assertIn("a test line", content)

    def test_broken_path_does_not_raise(self):
        # Previously main()'s while-True loop wrote directly with no
        # try/except -- a single failure would have silently killed the
        # whole background idle-bait loop forever.
        blocker = os.path.join(tempfile.mkdtemp(), "not_a_dir")
        open(blocker, "w").close()
        ib.THOUGHT_LOG = os.path.join(blocker, "thoughts.log")
        ib.append_thought_line("should not crash")  # must not raise


if __name__ == "__main__":
    unittest.main()
