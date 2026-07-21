#!/usr/bin/env python3
# Tests for bin/crt-window-switcher.py's decision logic -- the idle half
# of "switch back to book game on idle, or by command" (2026-07-21,
# Zach's direct ask). No live tmux; should_return_to_book_game() is pure.
import importlib.util
import os
import tempfile
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")
spec = importlib.util.spec_from_file_location("crt_window_switcher", os.path.join(BIN_DIR, "crt-window-switcher.py"))
ws = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ws)


class TestShouldReturnToBookGame(unittest.TestCase):
    def test_switches_back_when_idle_on_mono(self):
        self.assertTrue(ws.should_return_to_book_game(
            active_window="mono", last_active=100.0, now=140.0, idle_secs=30, claude_view_window="mono"))

    def test_does_not_switch_while_still_within_idle_window(self):
        self.assertFalse(ws.should_return_to_book_game(
            active_window="mono", last_active=100.0, now=110.0, idle_secs=30, claude_view_window="mono"))

    def test_never_switches_away_from_a_different_window(self):
        # Someone deliberately switched to bookanswer/calibrate/etc by
        # hand -- must never yank focus away from that.
        self.assertFalse(ws.should_return_to_book_game(
            active_window="bookanswer", last_active=100.0, now=200.0, idle_secs=30, claude_view_window="mono"))

    def test_no_known_activity_means_no_switch(self):
        self.assertFalse(ws.should_return_to_book_game(
            active_window="mono", last_active=None, now=200.0, idle_secs=30, claude_view_window="mono"))

    def test_already_on_book_window_is_a_no_op(self):
        self.assertFalse(ws.should_return_to_book_game(
            active_window="book", last_active=100.0, now=200.0, idle_secs=30, claude_view_window="mono"))


class TestReadClaudeActiveState(unittest.TestCase):
    def test_reads_a_written_timestamp(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "state")
            with open(path, "w") as f:
                f.write("12345.5")
            self.assertEqual(ws.read_claude_active_state(path), 12345.5)

    def test_missing_file_returns_none(self):
        self.assertIsNone(ws.read_claude_active_state("/nonexistent/state"))

    def test_malformed_content_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "state")
            with open(path, "w") as f:
                f.write("not a number")
            self.assertIsNone(ws.read_claude_active_state(path))


if __name__ == "__main__":
    unittest.main()
