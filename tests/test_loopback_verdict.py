#!/usr/bin/env python3
# Offline test: bin/crt-earcon-loopback-test.py must not report a hardware
# finding from a run in which nothing was played or nothing was recorded
# (2026-07-25).
#
#   [rest: vault:crt/header-archaeology-20260817.md]
import importlib.util
import os
import unittest

BIN_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))
spec = importlib.util.spec_from_file_location(
    "crt_loopback", os.path.join(BIN_DIR, "crt-earcon-loopback-test.py"))
lb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lb)


class TestLoopbackVerdict(unittest.TestCase):
    def test_a_loud_tone_over_a_quiet_room_is_detected(self):
        status, _ = lb.loopback_verdict(best=100.0, base_rms=1.0)
        self.assertEqual(status, lb.DETECTED)

    def test_a_tone_lost_in_the_noise_is_not_detected(self):
        status, _ = lb.loopback_verdict(best=2.0, base_rms=1.0)
        self.assertEqual(status, lb.NOT_DETECTED)

    def test_a_tone_that_never_played_is_not_a_hardware_finding(self):
        status, detail = lb.loopback_verdict(
            best=0.0, base_rms=1.0,
            play_error="aplay exited 1 on plughw:9,0: No such file or directory")
        self.assertEqual(status, lb.INCONCLUSIVE)
        self.assertIn("nothing was played", detail)
        self.assertIn("plughw:9,0", detail)

    def test_a_recording_that_never_happened_is_not_a_hardware_finding(self):
        status, detail = lb.loopback_verdict(
            best=0.0, base_rms=0.0,
            capture_error="arecord exited 1 on plughw:0,0: Device or resource busy")
        self.assertEqual(status, lb.INCONCLUSIVE)
        self.assertIn("nothing was recorded", detail)

    def test_a_dead_capture_device_does_not_make_everything_detected(self):
        # The old arithmetic: ratio = best / (0.0 + 1e-6), which is enormous
        # for any nonzero energy -- and best is computed from the same failed
        # recording, so this fired on noise.
        status, _ = lb.loopback_verdict(
            best=0.5, base_rms=0.0, capture_error="no samples captured")
        self.assertNotEqual(status, lb.DETECTED)

    def test_a_failed_play_outranks_a_plausible_looking_ratio(self):
        # If the tone never played, a high ratio is something else in the
        # room at 1200Hz -- not evidence about this output path.
        status, _ = lb.loopback_verdict(best=100.0, base_rms=1.0,
                                        play_error="could not run aplay")
        self.assertEqual(status, lb.INCONCLUSIVE)


class TestSummaryExitCode(unittest.TestCase):
    def test_all_detected_passes(self):
        self.assertEqual(
            lb.summary_exit_code({"tv": lb.DETECTED, "handset": lb.DETECTED}),
            lb.EXIT_OK)

    def test_one_not_detected_fails(self):
        self.assertEqual(
            lb.summary_exit_code({"tv": lb.DETECTED, "handset": lb.NOT_DETECTED}),
            lb.EXIT_NOT_DETECTED)

    def test_inconclusive_outranks_not_detected(self):
        code = lb.summary_exit_code({"tv": lb.INCONCLUSIVE, "handset": lb.NOT_DETECTED})
        self.assertEqual(code, lb.EXIT_INCONCLUSIVE)

    def test_inconclusive_is_never_confused_with_a_pass(self):
        self.assertNotEqual(
            lb.summary_exit_code({"tv": lb.INCONCLUSIVE, "handset": lb.DETECTED}),
            lb.EXIT_OK)

    def test_testing_nothing_is_not_a_pass(self):
        self.assertNotEqual(lb.summary_exit_code({}), lb.EXIT_OK)

    def test_every_status_has_summary_wording(self):
        for status in (lb.DETECTED, lb.NOT_DETECTED, lb.INCONCLUSIVE):
            self.assertIn(status, lb.SUMMARY_TEXT)
        # And the inconclusive wording must not read like a verdict about
        # the hardware, which is the whole point of having a third one.
        self.assertNotIn("mic hears", lb.SUMMARY_TEXT[lb.INCONCLUSIVE])


class TestLastLine(unittest.TestCase):
    def test_picks_the_cause_not_the_preamble(self):
        self.assertEqual(
            lb.last_line("ALSA lib pcm.c: preamble\nNo such file or directory\n"),
            "No such file or directory")

    def test_empty_stderr_still_says_something(self):
        self.assertTrue(lb.last_line("").strip())


if __name__ == "__main__":
    unittest.main()
