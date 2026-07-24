#!/usr/bin/env python3
# Offline test for bin/crt-tts.py's play_wav(): the handset device must
# duck crt-stt-solo.py's capture (write "mute 1"/"mute 0" to the shared
# CTL file) around playback, same rationale as
# tests/test_earcon_capture_duck.sh for crt-earcon.sh's handset path --
# both share the same USB adapter as the live mic, so a played tone can't
# be reliably distinguished from silence by the capture pipeline while it's
# playing. tv/local-fallback playback must NOT touch the CTL file.
import importlib.util
import os
import sys
import tempfile
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")
spec = importlib.util.spec_from_file_location("crt_tts", os.path.join(BIN_DIR, "crt-tts.py"))
tts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tts)


class TestCaptureDuck(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.ctl_file = os.path.join(self.tmpdir, "ctl")
        self.wav = os.path.join(self.tmpdir, "x.wav")
        open(self.wav, "w").close()
        tts.CTL_FILE = self.ctl_file
        self.orig_run = tts.subprocess.run
        tts.subprocess.run = lambda *a, **k: None  # fake aplay: no-op

    def tearDown(self):
        tts.subprocess.run = self.orig_run

    def _ctl_lines(self):
        if not os.path.exists(self.ctl_file):
            return []
        with open(self.ctl_file) as f:
            return [l.strip() for l in f if l.strip()]

    def test_handset_playback_mutes_then_unmutes_capture(self):
        tts.play_wav(self.wav, "handset")
        self.assertEqual(self._ctl_lines(), ["mute 1", "mute 0"])

    def test_tv_playback_does_not_touch_ctl_file(self):
        tts.play_wav(self.wav, "tv")
        self.assertEqual(self._ctl_lines(), [])

    def test_handset_unmutes_even_if_aplay_raises(self):
        def boom(*a, **k):
            raise OSError("no such device")
        tts.subprocess.run = boom
        with self.assertRaises(OSError):
            tts.play_wav(self.wav, "handset")
        self.assertEqual(self._ctl_lines(), ["mute 1", "mute 0"])


if __name__ == "__main__":
    unittest.main()
