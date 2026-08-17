#!/usr/bin/env python3
# Offline test: when the thing that handles an utterance dies, the console has
# to say so (2026-07-25).
#
# bin/crt-console.sh boots the engine with CRT_STT_SINK=secretary, so
#   [rest: vault:crt/header-archaeology-20260817.md]
import importlib.util
import io
import os
import shutil
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout

BIN_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))


class DispatchBase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir, True)
        self.fakebin = os.path.join(self.tmpdir, "bin")
        os.makedirs(self.fakebin)
        # A fresh module per test: _dispatches and hud_msg are module globals.
        spec = importlib.util.spec_from_file_location(
            "crt_stt_dispatch", os.path.join(BIN_DIR, "crt-stt-solo.py"))
        self.stt = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.stt)
        self.stt.BIN_DIR = self.fakebin
        self.thoughts = os.path.join(self.tmpdir, "thoughts.log")
        self.stt.GATE_LOG = self.thoughts

    def fake_secretary(self, body):
        with open(os.path.join(self.fakebin, "crt-secretary.py"), "w") as f:
            f.write(body)

    def dispatch(self, text="potato what time is it"):
        """Hand one utterance over and return everything printed while doing
        it."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.stt.send_to_secretary(text)
        return buf.getvalue()

    def reap_after_exit(self, timeout=15.0):
        """Wait for every in-flight child to finish, then reap once and return
        what the reap printed. Waiting happens HERE, not in reap_dispatches --
        the capture loop must never block on a dispatch."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if all(d.proc.poll() is not None for d in self.stt._dispatches):
                break
            time.sleep(0.02)
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.stt.reap_dispatches()
        return buf.getvalue()

    def thoughts_text(self):
        if not os.path.exists(self.thoughts):
            return ""
        with open(self.thoughts) as f:
            return f.read()


class TestDeadSecretaryIsReported(DispatchBase):
    def test_import_time_death_is_reported_with_its_own_last_line(self):
        # The realistic failure: crt-secretary.py dies before main() runs, the
        # way it would if any of the three scripts it exec_module()s at import
        # time were missing or broken.
        self.fake_secretary(
            "import sys\n"
            "sys.stderr.write('Traceback (most recent call last):\\n')\n"
            "sys.stderr.write(\"FileNotFoundError: 'crt-speculate.py'\\n\")\n"
            "sys.exit(1)\n")
        self.dispatch("potato what time is it")
        out = self.reap_after_exit()
        self.assertIn("DISPATCH FAILED", out)
        self.assertIn("exited 1", out)
        # The cause, not just the fact -- the last stderr line names it.
        self.assertIn("crt-speculate.py", out)
        # And the words, so the person knows which utterance was lost.
        self.assertIn("what time is it", out)

    def test_failure_reaches_the_meter_line_and_window_one(self):
        self.fake_secretary("import sys\nsys.exit(1)\n")
        self.dispatch("potato read me the report")
        self.reap_after_exit()
        self.assertIn("nothing handled", self.stt.hud_msg)
        # window 1 renders thoughts.log; the '[you]' echo of this utterance
        # lands there too, so the bad news sits under it.
        self.assertIn("[!]", self.thoughts_text())

    def test_report_does_not_blame_the_person(self):
        self.fake_secretary("import sys\nsys.exit(1)\n")
        self.dispatch()
        out = self.reap_after_exit()
        self.assertIn("fault is here", out)

    def test_a_secretary_killed_by_a_signal_says_so(self):
        self.fake_secretary("import os, signal\nos.kill(os.getpid(), signal.SIGKILL)\n")
        self.dispatch()
        out = self.reap_after_exit()
        self.assertIn("killed by signal 9", out)

    def test_a_missing_secretary_is_reported_not_silent(self):
        # Nothing written to self.fakebin at all: python3 exists and exits
        # nonzero on a file it cannot open. Before this change that was
        # indistinguishable from a handled utterance.
        self.dispatch()
        out = self.reap_after_exit()
        self.assertIn("DISPATCH FAILED", out)


class TestSuccessStaysQuiet(DispatchBase):
    def test_a_secretary_that_worked_reports_nothing(self):
        self.fake_secretary("import sys\nsys.exit(0)\n")
        self.dispatch()
        out = self.reap_after_exit()
        self.assertEqual(out, "")
        self.assertEqual(self.stt.hud_msg, "")
        self.assertEqual(self.thoughts_text(), "")

    def test_finished_dispatches_stop_being_tracked(self):
        self.fake_secretary("import sys\nsys.exit(0)\n")
        for _ in range(3):
            self.dispatch()
        self.assertEqual(len(self.stt._dispatches), 3)
        self.reap_after_exit()
        self.assertEqual(self.stt._dispatches, [])


class TestReapNeverBlocks(DispatchBase):
    def test_a_still_running_secretary_is_neither_reported_nor_waited_for(self):
        # An unmatched request can legitimately hold crt-secretary.py for
        # CRT_SECRETARY_MAX_WAIT seconds while it waits on Claude. Reaping must
        # return immediately and say nothing about it.
        self.fake_secretary("import time\ntime.sleep(30)\n")
        self.dispatch()
        started = time.time()
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.stt.reap_dispatches()
        elapsed = time.time() - started
        self.assertLess(elapsed, 1.0)
        self.assertEqual(buf.getvalue(), "")
        self.assertEqual(len(self.stt._dispatches), 1)
        self.stt._dispatches[0].proc.kill()

    def test_dispatch_returns_promptly_even_for_a_slow_secretary(self):
        self.fake_secretary("import time\ntime.sleep(30)\n")
        started = time.time()
        self.dispatch()
        self.assertLess(time.time() - started, 2.0)
        self.stt._dispatches[0].proc.kill()


class TestSpawnFailureDoesNotDeafenTheConsole(DispatchBase):
    def refuse_to_fork(self):
        # `self.stt.subprocess` IS the real subprocess module, shared with
        # every other test in this process -- restore it, or the tests that
        # run after this one spawn nothing and pass for the wrong reason.
        real = self.stt.subprocess.Popen
        self.addCleanup(setattr, self.stt.subprocess, "Popen", real)

        def boom(*a, **k):
            raise OSError(12, "Cannot allocate memory")
        self.stt.subprocess.Popen = boom

    def test_an_oserror_from_the_spawn_is_reported_not_raised(self):
        # ENOMEM under memory pressure is the realistic trigger. This used to
        # propagate straight out of the capture loop.
        self.refuse_to_fork()
        out = self.dispatch("potato are you there")   # must not raise
        self.assertIn("DISPATCH FAILED", out)
        self.assertIn("Cannot allocate memory", out)
        self.assertEqual(self.stt._dispatches, [])

    def test_the_spawn_failure_also_reaches_window_one(self):
        self.refuse_to_fork()
        self.dispatch()
        self.assertIn("[!]", self.thoughts_text())


class TestTrackingIsBounded(DispatchBase):
    def test_beyond_the_cap_the_utterance_still_goes_through_and_says_so(self):
        # Never drop an utterance to keep a diagnostic -- but do not pretend
        # the untracked one is being watched either. Tracking only shrinks on
        # a reap, so the children here can exit at once; nothing is reaped
        # between the three dispatches.
        self.fake_secretary("import sys\nsys.exit(0)\n")
        self.stt.DISPATCH_MAX_TRACKED = 2
        self.dispatch()
        self.dispatch()
        out = self.dispatch("the third one")
        self.assertEqual(len(self.stt._dispatches), 2)
        self.assertIn("untracked", out)

    def test_open_stderr_files_stay_bounded_by_the_cap(self):
        self.fake_secretary("import sys\nsys.exit(0)\n")
        for _ in range(12):
            self.dispatch()
            self.reap_after_exit()
        self.assertLessEqual(len(self.stt._dispatches), self.stt.DISPATCH_MAX_TRACKED)


class TestReportWording(unittest.TestCase):
    """Pure string builders, no processes -- the wording is the whole point."""

    def setUp(self):
        spec = importlib.util.spec_from_file_location(
            "crt_stt_dispatch_pure", os.path.join(BIN_DIR, "crt-stt-solo.py"))
        self.stt = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.stt)

    def test_hud_fits_the_forty_column_tube(self):
        hud, _ = self.stt.dispatch_failure_report("some words", "exited 1")
        self.assertLessEqual(len(hud), 40)

    def test_a_very_long_utterance_does_not_run_away_with_the_line(self):
        hud, line = self.stt.dispatch_failure_report("word " * 400, "exited 1")
        self.assertLess(len(line), 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
