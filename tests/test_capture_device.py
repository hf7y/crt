#!/usr/bin/env python3
# Offline tests for crt-stt-solo.py's capture-device-by-name resolution
# (FOCUS.md stability-milestone bar item, 2026-07-23 07:10/07:20 notes):
# a hardcoded ALSA card INDEX silently breaks on a USB replug/reboot that
# renumbers cards. resolve_capture_device_by_name() is a pure string parse
# of `arecord -l` output -- no hardware/subprocess needed to test it.
import importlib.util
import os
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")
spec = importlib.util.spec_from_file_location("crt_stt_solo", os.path.join(BIN_DIR, "crt-stt-solo.py"))
stt_solo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stt_solo)

# Real `arecord -l` output shape seen live on potato (2026-07-23 07:10 note):
# card 0 is onboard/playback-only (doesn't appear in a CAPTURE listing at
# all), card 1 is the USB adapter that actually has a capture subdevice.
POTATO_ARECORD_L = """**** List of CAPTURE Hardware Devices ****
card 1: Audio [KT USB Audio], device 0: USB Audio [USB Audio]
  Subdevices: 1/1
  Subdevice #0: subdevice #0
"""

RENUMBERED_ARECORD_L = """**** List of CAPTURE Hardware Devices ****
card 2: Audio [KT USB Audio], device 0: USB Audio [USB Audio]
  Subdevices: 1/1
  Subdevice #0: subdevice #0
"""

MULTI_CARD_ARECORD_L = """**** List of CAPTURE Hardware Devices ****
card 0: PCH [HDA Intel PCH], device 0: ALC3271 Analog [ALC3271 Analog]
  Subdevices: 1/1
  Subdevice #0: subdevice #0
card 1: Audio [KT USB Audio], device 0: USB Audio [USB Audio]
  Subdevices: 1/1
  Subdevice #0: subdevice #0
"""


class TestResolveCaptureDeviceByName(unittest.TestCase):
    def test_matches_card_by_name(self):
        self.assertEqual(
            stt_solo.resolve_capture_device_by_name(POTATO_ARECORD_L),
            "plughw:1,0")

    def test_follows_renumbering(self):
        # The whole point: a USB replug that moves the card index must not
        # require any code/config change to keep working.
        self.assertEqual(
            stt_solo.resolve_capture_device_by_name(RENUMBERED_ARECORD_L),
            "plughw:2,0")

    def test_picks_matching_card_among_several(self):
        self.assertEqual(
            stt_solo.resolve_capture_device_by_name(MULTI_CARD_ARECORD_L),
            "plughw:1,0")

    def test_case_insensitive_match(self):
        self.assertEqual(
            stt_solo.resolve_capture_device_by_name(POTATO_ARECORD_L, name_pattern="usb audio"),
            "plughw:1,0")

    def test_no_name_match_prefers_a_real_capture_card_over_the_hardcoded_index(self):
        # DEV_FALLBACK (plughw:0,0) is precisely the device that broke live on
        # potato -- card 0 there is playback-only and absent from this listing,
        # so falling back to it guarantees silent no-capture. Any card that
        # appears in a CAPTURE listing can at least be opened.
        self.assertEqual(
            stt_solo.resolve_capture_device_by_name(MULTI_CARD_ARECORD_L, name_pattern="nonexistent card"),
            "plughw:0,0")   # first LISTED capture card here, which is a real one
        self.assertEqual(
            stt_solo.resolve_capture_device_by_name(RENUMBERED_ARECORD_L, name_pattern="nonexistent card"),
            "plughw:2,0")   # not DEV_FALLBACK's plughw:0,0 -- no such capture card

    def test_empty_output_falls_back(self):
        self.assertEqual(stt_solo.resolve_capture_device_by_name(""), stt_solo.DEV_FALLBACK)
        self.assertEqual(stt_solo.resolve_capture_device_by_name(None), stt_solo.DEV_FALLBACK)

    def test_custom_fallback_honored(self):
        self.assertEqual(
            stt_solo.resolve_capture_device_by_name("", fallback="plughw:9,0"),
            "plughw:9,0")


class TestExplicitOverrideWins(unittest.TestCase):
    def test_explicit_env_var_skips_name_resolution_entirely(self):
        # CRT_AUDIO_DEV must always be a hard override -- name-resolution
        # should never even run `arecord -l` when it's set (2026-07-23
        # 07:20 design note: never remove the manual escape hatch).
        original = dict(os.environ)
        try:
            os.environ["CRT_AUDIO_DEV"] = "plughw:5,0"
            self.assertEqual(stt_solo._detect_capture_device(), "plughw:5,0")
        finally:
            os.environ.clear()
            os.environ.update(original)


class TestCaptureDeathReport(unittest.TestCase):
    """The 2026-07-23 07:10 note's actual complaint -- "the process restarted
    silently exits (no error, no capture) rather than failing loudly" -- was
    about the SILENCE, not just the wrong card index. Resolving by name fixed
    one cause; this covers the report that now gets printed (and the nonzero
    exit that goes with it) whenever capture stops for any reason."""

    def test_instant_death_names_the_likely_cause_and_the_escape_hatch(self):
        msg = stt_solo.capture_death_report(
            "plughw:0,0", 1,
            "arecord: main:830: audio open error: No such file or directory", 0.2)
        self.assertIn("CAPTURE DIED", msg)
        self.assertIn("plughw:0,0", msg)
        self.assertIn("never produced any audio", msg)
        self.assertIn("CRT_AUDIO_DEV", msg)          # how to fix it, on screen
        self.assertIn("audio open error", msg)       # arecord's own words

    def test_death_after_running_a_while_is_described_differently(self):
        msg = stt_solo.capture_death_report("plughw:1,0", 0, "", 4200.0)
        self.assertNotIn("never produced any audio", msg)
        self.assertIn("USB replug", msg)
        self.assertIn("arecord said nothing on stderr", msg)

    def test_long_stderr_is_trimmed_for_a_40_column_screen(self):
        noisy = "\n".join("line %d" % i for i in range(50))
        msg = stt_solo.capture_death_report("plughw:1,0", 1, noisy, 0.1)
        self.assertIn("line 49", msg)                # keeps the most recent
        self.assertNotIn("line 40", msg)             # but not all 50
        self.assertLessEqual(len(msg.splitlines()), 10)

    def test_unknown_exit_code_and_runtime_are_tolerated(self):
        msg = stt_solo.capture_death_report("plughw:1,0", None, None, None)
        self.assertIn("CAPTURE DIED", msg)


if __name__ == "__main__":
    unittest.main()
