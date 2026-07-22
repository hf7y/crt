#!/usr/bin/env python3
# Tests for bin/crt-wake-pool.py -- the growing wake-word pool
# (2026-07-21, Zach's direct ask: a second, non-"claude" way to address
# the console, sourced from a hand-seeded dict plus cached book titles).
import importlib.util
import os
import tempfile
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")

_bg_spec = importlib.util.spec_from_file_location("crt_book_game", os.path.join(BIN_DIR, "crt-book-game.py"))
bg = importlib.util.module_from_spec(_bg_spec)
_bg_spec.loader.exec_module(bg)

_wp_spec = importlib.util.spec_from_file_location("crt_wake_pool", os.path.join(BIN_DIR, "crt-wake-pool.py"))
wp = importlib.util.module_from_spec(_wp_spec)
_wp_spec.loader.exec_module(wp)


def _register(conn, isbn, title, timestamp):
    book = {"isbn": isbn, "title": title, "authors": [], "year": None, "subjects": [], "raw": {}}
    bg.register_book(conn, book, questions=[], question_source="template", timestamp=timestamp)


class TestLoadDictWords(unittest.TestCase):
    def test_missing_file_returns_empty_set(self):
        self.assertEqual(wp.load_dict_words("/nonexistent/wake-pool-dict.txt"), set())

    def test_reads_one_word_per_line_lowercased(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "dict.txt")
            with open(path, "w") as f:
                f.write("Monitor\nSCREEN\n\n")
            self.assertEqual(wp.load_dict_words(path), {"monitor", "screen"})

    def test_ignores_comment_lines(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "dict.txt")
            with open(path, "w") as f:
                f.write("# a comment\nmonitor\n")
            self.assertEqual(wp.load_dict_words(path), {"monitor"})


class TestTitleWords(unittest.TestCase):
    def test_excludes_short_filler_words(self):
        self.assertEqual(wp.title_words("The Lord of the Rings"), {"lord", "rings"})

    def test_lowercases_and_strips_punctuation(self):
        # "Web" (3 letters) is filtered by the 4+ length rule -- only
        # "Charlotte's" survives.
        self.assertEqual(wp.title_words("Charlotte's Web!"), {"charlotte's"})


class TestLoadBookTitleWords(unittest.TestCase):
    def test_empty_catalog_returns_empty_set(self):
        with tempfile.TemporaryDirectory() as d:
            conn = bg.get_db(os.path.join(d, "books.db"))
            self.assertEqual(wp.load_book_title_words(conn), set())

    def test_pulls_words_from_registered_titles(self):
        with tempfile.TemporaryDirectory() as d:
            conn = bg.get_db(os.path.join(d, "books.db"))
            _register(conn, "1", "Dune", "2026-07-21T10:00:00")
            self.assertIn("dune", wp.load_book_title_words(conn))

    def test_respects_max_titles_cap(self):
        with tempfile.TemporaryDirectory() as d:
            conn = bg.get_db(os.path.join(d, "books.db"))
            _register(conn, "1", "Foundation", "2026-07-21T10:00:00")
            _register(conn, "2", "Neuromancer", "2026-07-21T11:00:00")
            words = wp.load_book_title_words(conn, max_titles=1)
            self.assertIn("neuromancer", words)  # most recent
            self.assertNotIn("foundation", words)


class TestLoadPool(unittest.TestCase):
    def test_combines_dict_and_book_titles(self):
        with tempfile.TemporaryDirectory() as d:
            dict_path = os.path.join(d, "dict.txt")
            with open(dict_path, "w") as f:
                f.write("monitor\n")
            conn = bg.get_db(os.path.join(d, "books.db"))
            _register(conn, "1", "Dune", "2026-07-21T10:00:00")
            pool = wp.load_pool(dict_path=dict_path, db_conn=conn)
            self.assertEqual(pool, {"monitor", "dune"})

    def test_none_conn_skips_book_titles(self):
        with tempfile.TemporaryDirectory() as d:
            dict_path = os.path.join(d, "dict.txt")
            with open(dict_path, "w") as f:
                f.write("monitor\n")
            self.assertEqual(wp.load_pool(dict_path=dict_path, db_conn=None), {"monitor"})


class TestCheckPoolMatch(unittest.TestCase):
    def test_whole_word_match(self):
        self.assertTrue(wp.check_pool_match("hey monitor show me", {"monitor"}))

    def test_no_match(self):
        self.assertFalse(wp.check_pool_match("what time is it", {"monitor", "dune"}))

    def test_substring_does_not_false_positive(self):
        self.assertFalse(wp.check_pool_match("monitoring the levels", {"monitor"}))

    def test_empty_pool_never_matches(self):
        self.assertFalse(wp.check_pool_match("monitor", set()))


class TestClosestPoolWord(unittest.TestCase):
    def test_finds_closest_match(self):
        word, ratio = wp.closest_pool_word("monitr", {"monitor", "zebra"})
        self.assertEqual(word, "monitor")
        self.assertGreater(ratio, 0.9)

    def test_empty_pool_returns_none_and_zero(self):
        word, ratio = wp.closest_pool_word("anything", set())
        self.assertIsNone(word)
        self.assertEqual(ratio, 0.0)

    def test_exact_match_has_ratio_one(self):
        word, ratio = wp.closest_pool_word("monitor", {"monitor"})
        self.assertEqual(ratio, 1.0)


class TestFuzzyClusterMatch(unittest.TestCase):
    def test_single_close_word_below_cluster_min_does_not_match(self):
        # "monitr" is close to "monitor" but only ONE word is close --
        # cluster_min defaults to 2, so this alone shouldn't pass.
        self.assertFalse(wp.fuzzy_cluster_match("monitr please", {"monitor"}))

    def test_two_close_words_meets_cluster_min(self):
        pool = {"monitor", "screen"}
        # "monitr" ~ "monitor", "screan" ~ "screen" -- two distinct close
        # hits against two distinct pool words.
        self.assertTrue(wp.fuzzy_cluster_match("monitr and screan please", pool))

    def test_cluster_min_one_lets_a_single_close_word_pass(self):
        self.assertTrue(wp.fuzzy_cluster_match("monitr please", {"monitor"}, cluster_min=1))

    def test_empty_pool_never_matches(self):
        self.assertFalse(wp.fuzzy_cluster_match("monitor screen", set()))

    def test_unrelated_words_do_not_match(self):
        self.assertFalse(wp.fuzzy_cluster_match("what a nice day outside", {"monitor", "screen"}))

    def test_short_words_are_excluded_from_consideration(self):
        # "and"/"the" etc (under 4 letters) shouldn't count toward the
        # cluster even if they happen to be textually close to something.
        self.assertFalse(wp.fuzzy_cluster_match("and the", {"and"}, cluster_min=1))

    def test_stricter_close_ratio_rejects_weaker_matches(self):
        pool = {"monitor"}
        # A stricter ratio than the default should reject a weaker match
        # that the default threshold would accept.
        self.assertFalse(wp.fuzzy_cluster_match("mnitr please", pool, close_ratio=0.99, cluster_min=1))


class TestPickSuggestion(unittest.TestCase):
    def test_deterministic_first_word_at_index_zero(self):
        self.assertEqual(wp.pick_suggestion({"zebra", "apple", "monitor"}, index=0), "apple")

    def test_rotates_with_index(self):
        pool = {"apple", "monitor", "zebra"}  # sorted: apple, monitor, zebra
        self.assertEqual(wp.pick_suggestion(pool, index=1), "monitor")
        self.assertEqual(wp.pick_suggestion(pool, index=2), "zebra")
        self.assertEqual(wp.pick_suggestion(pool, index=3), "apple")  # wraps

    def test_empty_pool_returns_none(self):
        self.assertIsNone(wp.pick_suggestion(set()))

    def test_exclude_set_is_respected(self):
        self.assertEqual(wp.pick_suggestion({"apple", "banana"}, exclude={"apple"}), "banana")


if __name__ == "__main__":
    unittest.main()
