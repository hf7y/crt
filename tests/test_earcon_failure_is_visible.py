#!/usr/bin/env python3
# Offline test: a chime that never sounded must leave a trace (2026-07-25).
#
# play_earcon() is fire-and-forget by design -- it runs inside the sole mic
# reader's capture loop (crt-stt-solo.py) and in front of a wait the person is
# already sitting through (crt-secretary.py), so nothing may wait on its exit
# status. But both call sites also sent its stderr to /dev/null, and
# crt-earcon.sh is silent on success: it writes to stderr only to say sox is
# missing, the name is unknown, or (via `set -e`) that aplay failed. So the
# combination discarded the only evidence that existed, for free.
#
# EARCON_ON_ADDRESSED defaults on, which makes the earcon the console's only
# "I heard you". The secretary's "oops" is worse: an inaudible apology for an
# inaudible answer.
#
# Verified across a real process boundary -- the child's stderr has to reach
# the PARENT's, which cannot be asserted from inside one process.
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

BIN_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))

MARKER = "[crt-earcon] sox not installed"

DRIVER = """
import importlib.util, os, sys, time
spec = importlib.util.spec_from_file_location("m", %(module)r)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.BIN_DIR = %(fakebin)r
m.play_earcon("bait")
time.sleep(1.0)   # fire-and-forget: nothing waits, so this test must
"""


class TestEarconFailureIsVisible(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir, True)
        self.fakebin = os.path.join(self.tmpdir, "bin")
        os.makedirs(self.fakebin)
        earcon = os.path.join(self.fakebin, "crt-earcon.sh")
        with open(earcon, "w") as f:
            f.write("#!/bin/sh\necho '%s' >&2\nexit 1\n" % MARKER)
        os.chmod(earcon, os.stat(earcon).st_mode | stat.S_IXUSR | stat.S_IXGRP
                 | stat.S_IXOTH)

    def _drive(self, module_filename):
        r = subprocess.run(
            [sys.executable, "-c", DRIVER % {
                "module": os.path.join(BIN_DIR, module_filename),
                "fakebin": self.fakebin}],
            capture_output=True, text=True, timeout=120,
            env=dict(os.environ, CRT_STT_LOG=os.path.join(self.tmpdir, "stt.log")))
        return r

    def test_stt_solo_earcon_failure_reaches_the_pane(self):
        r = self._drive("crt-stt-solo.py")
        self.assertIn(MARKER, r.stderr,
                      "a chime that never sounded left no trace anywhere")

    def test_secretary_earcon_failure_reaches_the_pane(self):
        r = self._drive("crt-secretary.py")
        self.assertIn(MARKER, r.stderr,
                      "a chime that never sounded left no trace anywhere")

    def test_a_missing_earcon_script_does_not_kill_the_caller(self):
        # play_earcon runs inside the sole mic reader's loop. An OSError here
        # must never take capture down with it.
        os.unlink(os.path.join(self.fakebin, "crt-earcon.sh"))
        r = self._drive("crt-stt-solo.py")
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
