#!/usr/bin/env python3
# Offline test: the console must not report an unanswered call when the phone
# never rang (2026-07-25).
#
# bin/crt-stt-solo.py's ring path had the same shape as the TTS one fixed
# alongside it, one layer worse:
#
#   - ring_tone_path() ignored sox's exit status AND its stderr, then cached
#     `path` regardless. mkstemp has already created that file, so with no sox
#     installed the cache held a real, existing, ZERO-BYTE wav -- and
#     os.path.exists() said yes for the rest of the process's life. Every ring
#     thereafter handed aplay an empty file.
#   - the ring itself was subprocess.Popen(..., stderr=DEVNULL) and its exit
#     status was never read, only poll()'d to decide whether to terminate.
#
# So a console with no working sound output printed "[ring] ringing (4)",
# waited out four silent cycles, and printed "[ring] no answer" -- blaming the
# person for not picking up a phone that had never made a sound.
#
# Injected at PATH: `sox` and `aplay` here are real executables that really
# exit with the status under test, found the way the real code finds them.
import importlib.util
import os
import shutil
import stat
import tempfile
import unittest

BIN_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))


def write_exe(path, body):
    with open(path, "w") as f:
        f.write("#!/bin/sh\n" + body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class RingBase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir, True)
        self.binstub = os.path.join(self.tmpdir, "bin")
        os.makedirs(self.binstub)
        self.orig_path = os.environ["PATH"]
        os.environ["PATH"] = self.binstub + os.pathsep + self.orig_path
        self.addCleanup(os.environ.__setitem__, "PATH", self.orig_path)
        # A fresh module per test: _ring_tone_path is a module global whose
        # caching behaviour is exactly what is under test here.
        spec = importlib.util.spec_from_file_location(
            "crt_stt_ring", os.path.join(BIN_DIR, "crt-stt-solo.py"))
        self.stt = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.stt)

    def good_sox(self):
        write_exe(os.path.join(self.binstub, "sox"), """
prev=""
for a in "$@"; do
  case "$a" in *.wav) prev="$a";; esac
done
printf 'RIFFfakewav' > "$prev"
exit 0
""")

    def broken_sox(self, exit_code=1, stderr="sox FAIL formats: no such file"):
        write_exe(os.path.join(self.binstub, "sox"),
                  "printf '%s\\n' >&2\nexit %d\n" % (stderr, exit_code))

    def aplay(self, exit_code=0, stderr=""):
        write_exe(os.path.join(self.binstub, "aplay"),
                  ("printf '%s\\n' >&2\n" % stderr if stderr else "")
                  + "exit %d\n" % exit_code)


class TestRingToneSynthesis(RingBase):
    def test_a_working_sox_gives_a_playable_tone(self):
        self.good_sox()
        path = self.stt.ring_tone_path()
        self.assertIsNotNone(path)
        self.assertGreater(os.path.getsize(path), 0)

    def test_a_broken_sox_is_not_a_tone(self):
        self.broken_sox()
        self.assertIsNone(self.stt.ring_tone_path())

    def test_no_sox_at_all_is_not_a_tone(self):
        os.environ["PATH"] = os.path.join(self.tmpdir, "nonexistent-bin")
        self.assertIsNone(self.stt.ring_tone_path())

    def test_an_empty_wav_is_not_a_tone_even_when_sox_exits_zero(self):
        # sox can exit 0 and leave nothing usable; the size is the witness
        # that matters, because it is what aplay would choke on.
        write_exe(os.path.join(self.binstub, "sox"), "exit 0\n")
        self.assertIsNone(self.stt.ring_tone_path())

    def test_a_failed_tone_is_never_cached(self):
        # The heart of the bug: mkstemp's zero-byte file existed, so the
        # `os.path.exists(_ring_tone_path)` cache check passed forever after
        # and no later call could ever recover, even once sox worked.
        self.broken_sox()
        self.assertIsNone(self.stt.ring_tone_path())
        self.good_sox()
        path = self.stt.ring_tone_path()
        self.assertIsNotNone(path, "a ring that failed once could never ring again")
        self.assertGreater(os.path.getsize(path), 0)

    def test_a_failed_tone_leaves_no_temp_file_behind(self):
        before = len(os.listdir(tempfile.gettempdir()))
        self.broken_sox()
        for _ in range(5):
            self.stt.ring_tone_path()
        self.assertLessEqual(len(os.listdir(tempfile.gettempdir())), before + 1)


class TestRingFailureWording(RingBase):
    """Pure string builders -- the wording is the whole point, and it is
    testable without a sound card."""

    def test_it_does_not_read_as_an_unanswered_call(self):
        hud, line = self.stt.ring_unplayable_report("sox exited 1: no such file")
        self.assertNotIn("no answer", line.lower())
        self.assertNotIn("no answer", hud.lower())

    def test_it_says_the_fault_is_here(self):
        hud, line = self.stt.ring_unplayable_report("sox exited 1: no such file")
        self.assertIn("never rang", hud.lower())
        self.assertIn("sox exited 1", line)

    def test_the_hud_line_fits_the_tube(self):
        hud, _ = self.stt.ring_unplayable_report("x" * 500)
        self.assertLessEqual(len(hud), 40)

    def test_last_line_picks_the_cause_not_the_preamble(self):
        self.assertEqual(
            self.stt.last_line("ALSA lib pcm.c: preamble\nDevice or resource busy\n"),
            "Device or resource busy")
        self.assertTrue(self.stt.last_line("").strip())


class TestRingBurst(RingBase):
    def test_a_burst_that_plays_reports_no_failure(self):
        self.good_sox(); self.aplay(0)
        ring = self.stt.start_ring_tone()
        self.assertIsNotNone(ring)
        ring.wait(timeout=10)
        self.assertIsNone(ring.failure())

    def test_a_burst_whose_aplay_fails_says_why(self):
        self.good_sox()
        self.aplay(1, "aplay: main:834: audio open error: Device or resource busy")
        ring = self.stt.start_ring_tone()
        self.assertIsNotNone(ring)
        ring.wait(timeout=10)
        fault = ring.failure()
        self.assertIsNotNone(fault, "a ring nobody could hear reported success")
        self.assertIn("Device or resource busy", fault)

    def test_a_burst_we_stopped_ourselves_is_not_a_failure(self):
        # The answered case: the ring is terminated on purpose, which shows up
        # as a negative exit code. Reporting that as a fault would turn every
        # successfully answered call into an error.
        self.good_sox()
        write_exe(os.path.join(self.binstub, "aplay"), "sleep 30\n")
        ring = self.stt.start_ring_tone()
        ring.terminate()
        ring.wait(timeout=10)
        self.assertIsNone(ring.failure())

    def test_a_burst_still_playing_is_not_yet_a_failure(self):
        self.good_sox()
        write_exe(os.path.join(self.binstub, "aplay"), "sleep 30\n")
        ring = self.stt.start_ring_tone()
        self.assertIsNone(ring.failure())
        ring.kill(); ring.wait(timeout=10)

    def test_no_tone_means_no_burst(self):
        self.broken_sox(); self.aplay(0)
        self.assertIsNone(self.stt.start_ring_tone())

    def test_no_aplay_binary_means_no_burst(self):
        self.good_sox()
        self.stt.ring_tone_path()          # synthesize while sox is reachable
        os.environ["PATH"] = os.path.join(self.tmpdir, "nonexistent-bin")
        self.assertIsNone(self.stt.start_ring_tone())


if __name__ == "__main__":
    unittest.main()
