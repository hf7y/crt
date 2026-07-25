#!/usr/bin/env python3
# Tests for bin/crt-window-switcher.py's decision logic -- the idle half
# of "switch back to book game on idle, or by command" (2026-07-21,
# Zach's direct ask). No live tmux; should_return_to_book_game() is pure.
import importlib.util
import os
import subprocess
import tempfile
import time
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


class TestAnExchangeIsReturnedFromOnlyOnce(unittest.TestCase):
    # 2026-07-25: "never yank focus away from something someone chose by
    # hand" only ever covered windows OTHER than mono. Window 1 is the one
    # background window CLAUDE.md says is meant to be looked at, and every
    # honest-failure line the last ten cycles added lands there.
    def test_returning_by_hand_to_mono_later_is_not_bounced(self):
        self.assertFalse(ws.should_return_to_book_game(
            active_window="mono", last_active=100.0, now=4000.0, idle_secs=30,
            claude_view_window="mono", returned_from=100.0))

    def test_a_fresh_exchange_re_arms_the_auto_return(self):
        # crt-secretary.py's touch_claude_active() writes time.time(), so a
        # real new escalation always lands a different value.
        self.assertTrue(ws.should_return_to_book_game(
            active_window="mono", last_active=3900.0, now=4000.0, idle_secs=30,
            claude_view_window="mono", returned_from=100.0))

    def test_still_waits_out_the_idle_window_after_re_arming(self):
        self.assertFalse(ws.should_return_to_book_game(
            active_window="mono", last_active=3990.0, now=4000.0, idle_secs=30,
            claude_view_window="mono", returned_from=100.0))

    def test_omitting_returned_from_keeps_the_original_behaviour(self):
        self.assertTrue(ws.should_return_to_book_game(
            active_window="mono", last_active=100.0, now=4000.0, idle_secs=30,
            claude_view_window="mono"))


FAKE_TMUX = """#!/usr/bin/env python3
import sys
with open(%r, "a") as f:
    f.write(" ".join(sys.argv[1:]) + "\\n")
if sys.argv[1] == "display-message":
    sys.stdout.write("mono\\n")
    sys.exit(0)
if sys.argv[1] == "select-window":
    %s
sys.exit(0)
"""

SELECT_OK = "sys.exit(0)"
SELECT_FAILS = "sys.stderr.write(\"can't find window: claude:book\\\\n\"); sys.exit(1)"


class SwitcherLoop(unittest.TestCase):
    """Runs the real loop as a child process against a fake tmux. The two
    things this cycle changed both live in main()'s state, not in a pure
    function -- asserting them from inside this process would be asserting
    a reimplementation of the loop rather than the loop."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        d = self.dir.name
        self.calls = os.path.join(d, "tmux-calls.log")
        self.state = os.path.join(d, "claude-active.state")
        self.thoughts = os.path.join(d, "thoughts.log")

    def start(self, select_branch, poll="0.05", idle="0"):
        tmux = os.path.join(self.dir.name, "tmux")
        with open(tmux, "w") as f:
            f.write(FAKE_TMUX % (self.calls, select_branch))
        os.chmod(tmux, 0o755)
        with open(self.state, "w") as f:
            f.write("100.0")
        env = dict(os.environ)
        env.update({
            "PATH": self.dir.name + os.pathsep + env.get("PATH", ""),
            "CRT_WINDOW_SWITCHER_POLL_SECS": poll,
            "CRT_WINDOW_SWITCHER_IDLE_SECS": idle,
            "CRT_CLAUDE_ACTIVE_STATE": self.state,
            "CRT_THOUGHT_LOG": self.thoughts,
        })
        proc = subprocess.Popen(
            ["python3", os.path.join(BIN_DIR, "crt-window-switcher.py")],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        self.addCleanup(self.stop, proc)
        return proc

    @staticmethod
    def stop(proc):
        proc.kill()
        proc.wait(timeout=10)
        if proc.stderr is not None:
            proc.stderr.close()

    def selects(self):
        try:
            with open(self.calls) as f:
                return [ln for ln in f if ln.startswith("select-window")]
        except OSError:
            return []

    def lines(self, path):
        try:
            with open(path) as f:
                return [ln for ln in f.read().splitlines() if ln.strip()]
        except OSError:
            return []


class TestSwitcherLoopStopsAfterOneReturn(SwitcherLoop):
    def test_one_exchange_produces_one_select_window(self):
        # The fake tmux keeps reporting `mono` as the displayed window --
        # i.e. the person switched back by hand and is sitting there. Over
        # ~20 polls the old loop issued ~20 select-windows, one every two
        # seconds on the real console, and there was no way to read window
        # 1 at all.
        self.start(SELECT_OK)
        time.sleep(1.0)
        self.assertEqual(len(self.selects()), 1, self.selects())

    def test_a_new_escalation_re_arms_it(self):
        self.start(SELECT_OK)
        time.sleep(0.6)
        self.assertEqual(len(self.selects()), 1, self.selects())
        with open(self.state, "w") as f:
            f.write("500.0")          # crt-secretary.py touched it again
        time.sleep(0.6)
        self.assertEqual(len(self.selects()), 2, self.selects())


class TestSwitcherLoopSaysWhenItCannotSwitch(SwitcherLoop):
    def test_a_failing_select_window_is_reported_once_and_keeps_trying(self):
        proc = self.start(SELECT_FAILS)
        time.sleep(1.0)
        reported = self.lines(self.thoughts)
        self.assertEqual(len(reported), 1, reported)
        self.assertIn("can't find window", reported[0])
        # Not marked spent on a failure: one bad tmux call must not end the
        # auto-return for the rest of the console's uptime.
        self.assertGreater(len(self.selects()), 1, self.selects())
        self.assertIsNone(proc.poll(), "the loop should still be running")


class TestSwitchFailureReport(unittest.TestCase):
    def test_names_the_window_and_the_cause(self):
        line = ws.switch_failure_report("claude:book", "can't find window: claude:book")
        self.assertIn("claude:book", line)
        self.assertIn("can't find window", line)
        self.assertTrue(line.startswith("[!]"))


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
