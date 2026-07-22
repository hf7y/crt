#!/usr/bin/env python3
# Tests for bin/crt-wake-pool-tally.py -- the offline "which wake-pool
# near-misses keep recurring" surfacer (2026-07-21, Zach's direct ask:
# "record those wake word mismatches as data for later").
import importlib.util
import os
import tempfile
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")
spec = importlib.util.spec_from_file_location("crt_wake_pool_tally", os.path.join(BIN_DIR, "crt-wake-pool-tally.py"))
tally = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tally)


class TestLoadNearmissLines(unittest.TestCase):
    def test_missing_file_returns_empty_list(self):
        self.assertEqual(tally.load_nearmiss_lines("/nonexistent/nearmiss.log"), [])

    def test_reads_lines_skips_blank(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "nearmiss.log")
            with open(path, "w") as f:
                f.write("hey there\n\ncoulter\n")
            self.assertEqual(tally.load_nearmiss_lines(path), ["hey there", "coulter"])


class TestTallyNearmisses(unittest.TestCase):
    def test_below_min_repeats_not_surfaced(self):
        lines = ["coulter", "coulter", "monitor"]
        self.assertEqual(tally.tally_nearmisses(lines, min_repeats=3), [])

    def test_repeated_text_surfaced_with_count(self):
        lines = ["coulter", "coulter", "coulter", "monitor"]
        surfaced = tally.tally_nearmisses(lines, min_repeats=2)
        self.assertEqual(surfaced, [("coulter", 3)])

    def test_sorted_most_frequent_first(self):
        lines = ["a", "a", "b", "b", "b"]
        surfaced = tally.tally_nearmisses(lines, min_repeats=2)
        self.assertEqual(surfaced, [("b", 3), ("a", 2)])

    def test_empty_lines_returns_empty(self):
        self.assertEqual(tally.tally_nearmisses([], min_repeats=2), [])


if __name__ == "__main__":
    unittest.main()
