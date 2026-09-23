#!/usr/bin/env python3
# Offline tests for bin/crt-midi-knobs.py's write_ctl() -- had ZERO coverage
# before this. Only the file-write contract is testable without real MIDI
# hardware (mido import happens inside main(), not at module scope).
#
# Run: python3 tests/test_midi_knobs.py
import importlib.util
import os
import tempfile
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")


def load_midi_knobs():
    spec = importlib.util.spec_from_file_location(
        "crt_midi_knobs_under_test", os.path.join(BIN_DIR, "crt-midi-knobs.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestWriteCtl(unittest.TestCase):
    def setUp(self):
        self.m = load_midi_knobs()
        self.d = tempfile.TemporaryDirectory()
        self.m.CTL = os.path.join(self.d.name, "ctl")

    def tearDown(self):
        self.d.cleanup()

    def test_appends_when_small(self):
        self.m.write_ctl("vad 4.0")
        self.m.write_ctl("nr 0.1")
        with open(self.m.CTL) as f:
            self.assertEqual(f.read().splitlines(), ["vad 4.0", "nr 0.1"])

    def test_truncates_instead_of_appending_once_over_8192_bytes(self):
        with open(self.m.CTL, "w") as f:
            f.write("x" * 8193)
        self.m.write_ctl("vad 4.0")
        # A reader tracking a byte offset into this file must see the size
        # drop -- that is what tells it to restart at 0 (crt-stt-solo.py's
        # main() loop, `sz < ctl_pos`). Appending here would hide the drop.
        with open(self.m.CTL) as f:
            self.assertEqual(f.read(), "vad 4.0\n")


if __name__ == "__main__":
    unittest.main()
