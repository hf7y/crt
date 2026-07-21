#!/usr/bin/env python3
# Tests for bin/crt-speculate.py -- PARKING-LOT.md's speculative/
# optimistic-response filler line.
import importlib.util
import os
import random
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")
spec = importlib.util.spec_from_file_location("crt_speculate", os.path.join(BIN_DIR, "crt-speculate.py"))
spec_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(spec_mod)


class TestPickFillerLine(unittest.TestCase):
    def test_returns_nonempty_string(self):
        line = spec_mod.pick_filler_line(rng=random.Random(1))
        self.assertIsInstance(line, str)
        self.assertGreater(len(line), 0)

    def test_only_from_known_pool(self):
        for seed in range(10):
            self.assertIn(spec_mod.pick_filler_line(rng=random.Random(seed)), spec_mod.FILLER_LINES)

    def test_default_rng_works_without_argument(self):
        line = spec_mod.pick_filler_line()
        self.assertIn(line, spec_mod.FILLER_LINES)


if __name__ == "__main__":
    unittest.main()
