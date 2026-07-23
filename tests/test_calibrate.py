#!/usr/bin/env python3
# Offline tests for bin/crt-calibrate.py -- had ZERO coverage before
# 2026-07-23. Covers only the pure functions (auto_safe_area, load_conf/
# save_conf); the interactive /dev/tty1-driven parts aren't testable
# without real hardware and aren't touched here.
#
# Run: python3 tests/test_calibrate.py
import importlib.util
import os
import tempfile
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")


def load_calibrate():
    spec = importlib.util.spec_from_file_location(
        "crt_calibrate_under_test", os.path.join(BIN_DIR, "crt-calibrate.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestAutoSafeArea(unittest.TestCase):
    def setUp(self):
        self.m = load_calibrate()

    def test_insets_one_cell_each_edge_by_default(self):
        # This session's own real tmux window size (39x16, window 0,
        # 2026-07-23) -- window size minus one column left, one column
        # right, one row top, one row bottom.
        self.assertEqual(self.m.auto_safe_area(16, 39), (14, 37))

    def test_matches_the_hardware_console_size_too(self):
        # The real physical CRT console (CLAUDE.md's 40x15).
        self.assertEqual(self.m.auto_safe_area(15, 40), (13, 38))

    def test_custom_margin(self):
        self.assertEqual(self.m.auto_safe_area(16, 39, margin=2), (12, 35))

    def test_floors_at_one_instead_of_going_zero_or_negative(self):
        self.assertEqual(self.m.auto_safe_area(2, 2), (1, 1))
        self.assertEqual(self.m.auto_safe_area(1, 1, margin=3), (1, 1))


class TestConf(unittest.TestCase):
    def test_load_conf_defaults_when_missing(self):
        m = load_calibrate()
        with tempfile.TemporaryDirectory() as d:
            m.CONF_PATH = os.path.join(d, "nonexistent.conf")
            state = m.load_conf()
            self.assertEqual(state, m.DEFAULTS)

    def test_save_then_load_round_trips(self):
        m = load_calibrate()
        with tempfile.TemporaryDirectory() as d:
            m.CONF_PATH = os.path.join(d, "calibrate.conf")
            state = dict(m.DEFAULTS)
            state["margin_top"] = 5
            m.save_conf(state)
            loaded = m.load_conf()
            self.assertEqual(loaded["margin_top"], 5)


if __name__ == "__main__":
    unittest.main()
