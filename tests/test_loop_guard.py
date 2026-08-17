#!/usr/bin/env python3
# Tests for bin/crt_loop_guard.py and for its four call sites.
#
# The defect these cover is not in any pure function: it is that four
# `while True` / `for line in tail` loops in bin/ had no guard at all, so
#   [rest: vault:crt/header-archaeology-20260817.md]
import contextlib
import importlib.util
import io
import os
import sys
import tempfile
import unittest
from unittest import mock

# Read by LoopGuard.__init__ at construction time, including inside the
# four scripts below -- keeps their tracebacks out of this suite's output.
os.environ["CRT_LOOP_GUARD_TRACEBACK"] = "0"

BIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(BIN_DIR, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


guard_mod = _load("crt_loop_guard", "crt_loop_guard.py")


class Boom(Exception):
    pass


class StopTheLoop(KeyboardInterrupt):
    """A BaseException, like the real Ctrl-C -- LoopGuard must let it out."""


class Collector:
    def __init__(self):
        self.lines = []

    def __call__(self, line):
        self.lines.append(line)


# --------------------------------------------------------------------------
# The guard itself
# --------------------------------------------------------------------------

class TestDescribe(unittest.TestCase):
    def test_names_type_and_message(self):
        self.assertEqual(guard_mod.describe(ValueError("bad row")), "ValueError: bad row")

    def test_collapses_whitespace(self):
        # sqlite and OSError messages arrive with embedded newlines; the
        # tube textwraps rather than truncates, so a newline would cost rows.
        self.assertEqual(guard_mod.describe(ValueError("a\n  b\tc")), "ValueError: a b c")

    def test_truncates_to_fit_the_tube(self):
        d = guard_mod.describe(ValueError("x" * 500))
        self.assertLessEqual(len(d), len("ValueError: ") + guard_mod.DETAIL_MAX)
        self.assertTrue(d.endswith("..."))

    def test_bare_type_when_no_message(self):
        self.assertEqual(guard_mod.describe(Boom()), "Boom")


class TestGuardSuppresses(unittest.TestCase):
    def test_body_that_raises_does_not_escape(self):
        g = guard_mod.LoopGuard("w", report=Collector(), verbose=False)
        for _ in range(3):
            with g:
                raise Boom("nope")
        self.assertEqual(g.failures, 3)
        self.assertEqual(g.streak, 3)

    def test_clean_body_records_nothing(self):
        rep = Collector()
        g = guard_mod.LoopGuard("w", report=rep, verbose=False)
        for _ in range(3):
            with g:
                pass
        self.assertEqual(g.failures, 0)
        self.assertEqual(rep.lines, [])

    def test_keyboardinterrupt_is_not_caught(self):
        g = guard_mod.LoopGuard("w", report=Collector(), verbose=False)
        with self.assertRaises(KeyboardInterrupt):
            with g:
                raise StopTheLoop()
        self.assertEqual(g.failures, 0)

    def test_systemexit_is_not_caught(self):
        g = guard_mod.LoopGuard("w", report=Collector(), verbose=False)
        with self.assertRaises(SystemExit):
            with g:
                raise SystemExit(2)


class TestGuardReporting(unittest.TestCase):
    def test_same_cause_reported_once(self):
        rep = Collector()
        g = guard_mod.LoopGuard("bookanswer", report=rep, verbose=False)
        for _ in range(50):
            with g:
                raise Boom("database is locked")
        self.assertEqual(len(rep.lines), 1)
        self.assertIn("bookanswer", rep.lines[0])
        self.assertIn("database is locked", rep.lines[0])
        self.assertIn("still running", rep.lines[0])

    def test_a_different_cause_is_news(self):
        rep = Collector()
        g = guard_mod.LoopGuard("w", report=rep, verbose=False)
        with g:
            raise Boom("first")
        with g:
            raise Boom("second")
        self.assertEqual(len(rep.lines), 2)

    def test_recovery_reports_how_many_were_swallowed(self):
        rep = Collector()
        g = guard_mod.LoopGuard("stttrain", report=rep, verbose=False)
        for _ in range(4):
            with g:
                raise Boom("enospc")
        with g:
            pass
        self.assertEqual(len(rep.lines), 2)
        self.assertIn("recovered after 4", rep.lines[1])
        self.assertEqual(g.streak, 0)
        self.assertEqual(g.failures, 4)

    def test_recovery_is_reported_once_not_every_clean_pass(self):
        rep = Collector()
        g = guard_mod.LoopGuard("w", report=rep, verbose=False)
        with g:
            raise Boom("x")
        for _ in range(5):
            with g:
                pass
        self.assertEqual(len(rep.lines), 2)

    def test_a_cause_that_returns_after_recovery_is_reported_again(self):
        # Otherwise an intermittent fault is announced once at 3am and
        # never again, which reads as "it was fixed".
        rep = Collector()
        g = guard_mod.LoopGuard("w", report=rep, verbose=False)
        with g:
            raise Boom("flaky")
        with g:
            pass
        with g:
            raise Boom("flaky")
        self.assertEqual(len(rep.lines), 3)


class TestGuardAnnounce(unittest.TestCase):
    def test_writes_the_line_to_the_window_1_log(self):
        with tempfile.TemporaryDirectory() as d:
            log = os.path.join(d, "sub", "thoughts.log")
            g = guard_mod.LoopGuard("w", log_path=log, verbose=False)
            with g:
                raise Boom("disk full")
            with open(log) as f:
                body = f.read()
        self.assertIn("[!] w skipped one", body)
        self.assertIn("disk full", body)

    def test_echo_writes_the_line_to_the_pane_too(self):
        buf = io.StringIO()
        with tempfile.TemporaryDirectory() as d:
            log = os.path.join(d, "thoughts.log")
            g = guard_mod.LoopGuard("w", log_path=log, verbose=False)
            with contextlib.redirect_stdout(buf):
                with g:
                    raise Boom("x")
        self.assertIn("[!] w skipped one", buf.getvalue())

    def test_echo_false_keeps_the_pane_clean_but_still_logs(self):
        # For a window whose stdout is a drawn frame, not scrollback.
        buf = io.StringIO()
        with tempfile.TemporaryDirectory() as d:
            log = os.path.join(d, "thoughts.log")
            g = guard_mod.LoopGuard("book", log_path=log, verbose=False, echo=False)
            with contextlib.redirect_stdout(buf):
                with g:
                    raise Boom("x")
            with open(log) as f:
                body = f.read()
        self.assertEqual(buf.getvalue(), "")
        self.assertIn("[!] book skipped one", body)

    def test_traceback_is_off_with_no_env_set(self):
        # The `book` pane is the tube; frames painted there outlive the
        # frame. Cleared explicitly -- this module pins the var at import
        # to keep the suite quiet, which would make this test pass for the
        # wrong reason.
        env = dict(os.environ)
        env.pop("CRT_LOOP_GUARD_TRACEBACK", None)
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertFalse(guard_mod.LoopGuard("w", report=Collector()).verbose)
            os.environ["CRT_LOOP_GUARD_TRACEBACK"] = "1"
            self.assertTrue(guard_mod.LoopGuard("w", report=Collector()).verbose)

    def test_an_unwritable_log_does_not_end_the_loop(self):
        # The guard's whole job is to not be the thing that kills the loop.
        g = guard_mod.LoopGuard("w", log_path="/proc/nope/thoughts.log", verbose=False)
        with g:
            raise Boom("x")
        self.assertEqual(g.failures, 1)


class TestGuardDoesNotPace(unittest.TestCase):
    def test_guard_never_sleeps(self):
        # A guard that quietly inserted a backoff would make a hot loop
        # look healthy and move pacing out of the caller's sight.
        with mock.patch("time.sleep", side_effect=AssertionError("guard slept")):
            g = guard_mod.LoopGuard("w", report=Collector(), verbose=False)
            with g:
                raise Boom("x")
            with g:
                pass
        self.assertEqual(g.failures, 1)


# --------------------------------------------------------------------------
# The four call sites, driven for real
# --------------------------------------------------------------------------

class Ticker:
    """Stands in for whatever paces a loop. Raises StopTheLoop on the Nth
    tick so the test terminates through a path the guard must not catch."""

    def __init__(self, limit):
        self.limit = limit
        self.ticks = 0

    def tick(self, *a, **kw):
        self.ticks += 1
        if self.ticks >= self.limit:
            raise StopTheLoop()


class CallSiteMixin:
    def load_with_log(self, name, filename, log):
        """Loads the script with CRT_THOUGHT_LOG pointed at a temp file, so
        the guard's own module-level default picks it up at import. Done
        through the environment rather than by reaching into
        `mod.loop_guard` so that against a pre-guard version of the script
        these tests fail with the real defect -- the exception escaping
        main() -- rather than with 'no attribute loop_guard'."""
        with mock.patch.dict(os.environ, {"CRT_THOUGHT_LOG": log}):
            return _load(name, filename)

    def assert_survived_and_reported(self, mod, ticker, window, log):
        self.assertGreaterEqual(ticker.ticks, 5,
                                "loop ended early -- the guard did not hold")
        with open(log) as f:
            body = f.read()
        self.assertIn("[!] %s skipped one" % window, body)
        # Reported once per distinct cause, not once per iteration: window 1
        # fades the person's own words off the top.
        self.assertEqual(body.count("[!] %s skipped one" % window), 1)


class TestBookIdleBaitSurvives(unittest.TestCase, CallSiteMixin):
    def test_a_raising_pick_does_not_end_idle_bait(self):
        with tempfile.TemporaryDirectory() as d:
            log = os.path.join(d, "thoughts.log")
            mod = self.load_with_log("crt_book_idle_bait_guarded",
                                     "crt-book-idle-bait.py", log)
            mod.STT_LOG = os.path.join(d, "no-such-stt.log")   # -> always "idle"
            mod.POLL_SECS = 0
            ticker = Ticker(6)
            with mock.patch.object(mod.bg, "get_db", return_value=None), \
                 mock.patch.object(mod, "pick_and_format_line",
                                   side_effect=Boom("no such table: books")), \
                 mock.patch.object(mod.time, "sleep", ticker.tick):
                with self.assertRaises(KeyboardInterrupt):
                    mod.main()
            self.assert_survived_and_reported(mod, ticker, "bookidle", log)


class TestBookAnswerListenSurvives(unittest.TestCase, CallSiteMixin):
    def test_a_raising_grade_does_not_end_the_funnel(self):
        with tempfile.TemporaryDirectory() as d:
            log = os.path.join(d, "thoughts.log")
            mod = self.load_with_log("crt_book_answer_listen_guarded",
                                     "crt-book-answer-listen.py", log)
            ticker = Ticker(6)

            def fake_tail(_path):
                while True:
                    ticker.tick()
                    yield "12:00:00  fiction\n"

            with mock.patch.object(mod.bg, "get_db", return_value=None), \
                 mock.patch.object(mod, "tail_new_lines", fake_tail), \
                 mock.patch.object(mod, "grade_pending_answer",
                                   side_effect=Boom("database is locked")):
                with self.assertRaises(KeyboardInterrupt):
                    mod.main()
            self.assert_survived_and_reported(mod, ticker, "bookanswer", log)


class TestBookConsoleSurvives(unittest.TestCase, CallSiteMixin):
    def test_a_raising_scan_does_not_end_the_boot_default_window(self):
        with tempfile.TemporaryDirectory() as d:
            log = os.path.join(d, "thoughts.log")
            mod = self.load_with_log("crt_book_console_guarded",
                                     "crt-book-console.py", log)
            conn = mod.bg.get_db(os.path.join(d, "books.db"))
            ticker = Ticker(6)

            def fake_tail(_path):
                while True:
                    ticker.tick()
                    yield "12:00:00  [scan] 9780000000000\n"

            class FakeTail:
                def readline(self):
                    return ""

            pane = io.StringIO()
            with mock.patch.object(mod.bg, "get_db", return_value=conn), \
                 mock.patch.object(mod, "open_training_tail", return_value=FakeTail()), \
                 mock.patch.object(mod, "tail_new_lines", fake_tail), \
                 mock.patch.object(mod, "draw", lambda *a, **kw: None), \
                 mock.patch.object(mod, "parse_scanner_log_line",
                                   side_effect=Boom("no such column: quote")), \
                 contextlib.redirect_stdout(pane):
                with self.assertRaises(KeyboardInterrupt):
                    mod.main()
            self.assert_survived_and_reported(mod, ticker, "book", log)
            # This pane is the tube, and draw() owns it. A report printed
            # here would sit in the middle of the drawn frame.
            self.assertEqual(pane.getvalue(), "")


class TestTrainingMergeLoopSurvives(unittest.TestCase, CallSiteMixin):
    def _mod(self, log=os.devnull):
        return self.load_with_log("crt_stt_training_merge_guarded",
                                  "crt-stt-training-merge.py", log)

    def test_a_raising_pass_does_not_end_the_loop(self):
        with tempfile.TemporaryDirectory() as d:
            log = os.path.join(d, "thoughts.log")
            mod = self._mod(log)
            ticker = Ticker(6)
            with mock.patch.object(sys, "argv", ["crt-stt-training-merge.py", "--loop"]), \
                 mock.patch.object(mod, "run_merge_pass",
                                   side_effect=Boom("[Errno 28] No space left on device")), \
                 mock.patch.object(mod.time, "sleep", ticker.tick):
                with self.assertRaises(KeyboardInterrupt):
                    mod.main()
            self.assert_survived_and_reported(mod, ticker, "stttrain", log)

    def test_one_shot_mode_still_fails_loud(self):
        # The opposite requirement, in the same function: a person or a
        # script running this once must get a non-zero exit, not a
        # swallowed error and exit 0.
        mod = self._mod()
        with mock.patch.object(sys, "argv", ["crt-stt-training-merge.py"]), \
             mock.patch.object(mod, "run_merge_pass", side_effect=Boom("enospc")):
            with self.assertRaises(Boom):
                mod.main()

    def test_one_shot_success_still_reports_merged_keys(self):
        mod = self._mod()
        buf = io.StringIO()
        with mock.patch.object(sys, "argv", ["crt-stt-training-merge.py"]), \
             mock.patch.object(mod, "run_merge_pass", return_value=["friction"]), \
             contextlib.redirect_stdout(buf):
            mod.main()   # must not raise
        self.assertIn("friction", buf.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
