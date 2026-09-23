#!/usr/bin/env python3
# Offline tests for bin/crt-midi-knobs.py's write_ctl() -- pure file I/O,
# no MIDI hardware/mido needed.
import importlib.util
import os
import sys
import tempfile
import unittest

BIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")

spec = importlib.util.spec_from_file_location("crt_midi_knobs", os.path.join(BIN, "crt-midi-knobs.py"))
mk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mk)


class TestWriteCtl(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ctl = os.path.join(self.tmp.name, "sub", "ctl")
        self.old_ctl = mk.CTL
        mk.CTL = self.ctl

    def tearDown(self):
        mk.CTL = self.old_ctl
        self.tmp.cleanup()

    def test_creates_parent_dir_and_appends_when_small(self):
        mk.write_ctl("vad 3.0")
        mk.write_ctl("nr 0.1")
        with open(self.ctl) as f:
            lines = f.read().splitlines()
        self.assertEqual(lines, ["vad 3.0", "nr 0.1"])

    def test_truncates_once_file_exceeds_8192_bytes(self):
        # The engine reads new lines by byte offset and resets that offset
        # to 0 when it sees the file shrink -- so once CTL is large, the
        # next write must replace it, not append onto an ever-growing tail.
        os.makedirs(os.path.dirname(self.ctl), exist_ok=True)
        with open(self.ctl, "w") as f:
            f.write("x" * 8193)
        mk.write_ctl("vad 3.0")
        with open(self.ctl) as f:
            content = f.read()
        self.assertEqual(content, "vad 3.0\n")

    def test_stays_in_append_mode_at_exactly_8192_bytes(self):
        os.makedirs(os.path.dirname(self.ctl), exist_ok=True)
        with open(self.ctl, "w") as f:
            f.write("x" * 8192)
        mk.write_ctl("vad 3.0")
        with open(self.ctl) as f:
            content = f.read()
        self.assertTrue(content.startswith("x" * 8192))
        self.assertTrue(content.endswith("vad 3.0\n"))


if __name__ == "__main__":
    unittest.main()
