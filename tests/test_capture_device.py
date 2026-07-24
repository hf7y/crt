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

    def test_no_match_falls_back(self):
        self.assertEqual(
            stt_solo.resolve_capture_device_by_name(MULTI_CARD_ARECORD_L, name_pattern="nonexistent card"),
            stt_solo.DEV_FALLBACK)

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


if __name__ == "__main__":
    unittest.main()
