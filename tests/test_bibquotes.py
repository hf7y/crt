#!/usr/bin/env python3
# Tests for the bibliothecaire "bibquotes" idle-bait integration
# (2026-07-28, Zach-directed): "idlebait also show page92 excerpts via
# \\192.168.0.27\bibquotes". bin/crt-book-game.py's parse_bibquotes_line/
# load_bibquotes/pick_bibquotes_line, plus bin/crt-book-idle-bait.py's
# mixing logic. No network -- these only ever read a LOCAL cached file
# (bin/crt-bibquotes-sync.sh's job), same NON-API-AT-IDLE-TIME rule
# pick_idle_quote() already follows.
import importlib.util
import os
import random
import tempfile
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")

_bg_spec = importlib.util.spec_from_file_location("crt_book_game_bibquotes", os.path.join(BIN_DIR, "crt-book-game.py"))
bg = importlib.util.module_from_spec(_bg_spec)
_bg_spec.loader.exec_module(bg)

_ib_spec = importlib.util.spec_from_file_location("crt_book_idle_bait_bibquotes", os.path.join(BIN_DIR, "crt-book-idle-bait.py"))
ib = importlib.util.module_from_spec(_ib_spec)
_ib_spec.loader.exec_module(ib)

# The exact separator the real live bibquotes share uses (confirmed via
# hexdump of the actual fetched quotes.txt, 2026-07-28): U+2014 EM DASH,
# padded with spaces on both sides -- not a hyphen, not an en-dash.
EM_DASH_LINE = (
    "To put it more picturesquely: only variety in R can force down the "
    "variety due to D; only variety can destroy variety. \u2014 W. Ross Ashby, "
    "An Introduction to Cybernetics"
)


class TestParseBibquotesLine(unittest.TestCase):
    def test_parses_real_live_format(self):
        result = bg.parse_bibquotes_line(EM_DASH_LINE)
        self.assertIsNotNone(result)
        quote, attribution = result
        self.assertTrue(quote.startswith("To put it more picturesquely"))
        self.assertEqual(attribution, "W. Ross Ashby, An Introduction to Cybernetics")

    def test_blank_line_returns_none(self):
        self.assertIsNone(bg.parse_bibquotes_line(""))
        self.assertIsNone(bg.parse_bibquotes_line("   \n"))

    def test_no_separator_returns_none(self):
        self.assertIsNone(bg.parse_bibquotes_line("just some text with no attribution"))

    def test_does_not_split_on_a_bare_hyphen(self):
        # Real risk in this corpus's actual content (philosophy/
        # cybernetics prose uses hyphens constantly) -- a bare ' - '
        # must never be treated as the separator.
        line = "Self-organization is not self-explanatory - it requires a model. \u2014 Someone, A Book"
        quote, attribution = bg.parse_bibquotes_line(line)
        self.assertIn("requires a model", quote)
        self.assertEqual(attribution, "Someone, A Book")

    def test_empty_quote_or_attribution_returns_none(self):
        self.assertIsNone(bg.parse_bibquotes_line(" \u2014 Attribution Only"))
        self.assertIsNone(bg.parse_bibquotes_line("Quote Only \u2014 "))


class TestLoadBibquotes(unittest.TestCase):
    def test_missing_file_returns_empty_list_not_raises(self):
        self.assertEqual(bg.load_bibquotes("/no/such/bibquotes.txt"), [])

    def test_loads_multiple_valid_lines(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "bibquotes.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(EM_DASH_LINE + "\n")
                f.write("Another real quote here. \u2014 Someone Else, Another Book\n")
            pairs = bg.load_bibquotes(path)
            self.assertEqual(len(pairs), 2)

    def test_skips_malformed_lines_without_failing_the_whole_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "bibquotes.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write("no separator here at all\n")
                f.write(EM_DASH_LINE + "\n")
                f.write("\n")
            pairs = bg.load_bibquotes(path)
            self.assertEqual(len(pairs), 1)


class TestPickBibquotesLine(unittest.TestCase):
    def test_missing_file_returns_none(self):
        self.assertIsNone(bg.pick_bibquotes_line("/no/such/bibquotes.txt"))

    def test_picks_from_available_lines(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "bibquotes.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(EM_DASH_LINE + "\n")
            picked = bg.pick_bibquotes_line(path, rng=random.Random(1))
            self.assertIsNotNone(picked)
            self.assertEqual(picked[1], "W. Ross Ashby, An Introduction to Cybernetics")


class TestIdleBaitMixesInBibquotes(unittest.TestCase):
    def test_bibquotes_line_can_appear_when_available(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "bibquotes.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(EM_DASH_LINE + "\n")
            conn = bg.get_db(os.path.join(d, "books.db"))
            # Force the bibquotes branch: entice rate 0, bibquotes rate 1.
            old_entice, old_biq = ib.ENTICE_RATE, ib.BIBQUOTES_RATE
            old_path = ib.bg.BIBQUOTES_LOCAL_PATH
            ib.ENTICE_RATE = 0.0
            ib.BIBQUOTES_RATE = 1.0
            ib.bg.BIBQUOTES_LOCAL_PATH = path
            try:
                line = ib.pick_and_format_line(conn, rng=random.Random(1))
            finally:
                ib.ENTICE_RATE, ib.BIBQUOTES_RATE = old_entice, old_biq
                ib.bg.BIBQUOTES_LOCAL_PATH = old_path
            self.assertIn("Ross Ashby", line)

    def test_no_bibquotes_file_falls_back_cleanly(self):
        with tempfile.TemporaryDirectory() as d:
            conn = bg.get_db(os.path.join(d, "books.db"))
            old_entice, old_biq = ib.ENTICE_RATE, ib.BIBQUOTES_RATE
            old_path = ib.bg.BIBQUOTES_LOCAL_PATH
            ib.ENTICE_RATE = 0.0
            ib.BIBQUOTES_RATE = 1.0
            ib.bg.BIBQUOTES_LOCAL_PATH = "/no/such/bibquotes.txt"
            try:
                line = ib.pick_and_format_line(conn, rng=random.Random(1))
            finally:
                ib.ENTICE_RATE, ib.BIBQUOTES_RATE = old_entice, old_biq
                ib.bg.BIBQUOTES_LOCAL_PATH = old_path
            self.assertIsNotNone(line)  # never crashes, never returns nothing


if __name__ == "__main__":
    unittest.main()
