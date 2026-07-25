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
        # A real executable named `aplay`, found the way play_wav() really
        # finds it (2026-07-25). This used to be
        # `subprocess.run = lambda *a, **k: None`, and that stub was never a
        # faithful stand-in: real subprocess.run returns a CompletedProcess,
        # so the stub silently asserted that nothing downstream would ever
        # look at aplay's exit status -- which is exactly the bug that was
        # sitting in play_wav() the whole time this test was green.
        self.binstub = os.path.join(self.tmpdir, "bin")
        os.makedirs(self.binstub)
        aplay = os.path.join(self.binstub, "aplay")
        with open(aplay, "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(aplay, 0o755)
        self.orig_path = os.environ["PATH"]
        os.environ["PATH"] = self.binstub + os.pathsep + self.orig_path

    def tearDown(self):
        os.environ["PATH"] = self.orig_path

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

    def test_handset_named_by_alsa_device_still_ducks(self):
        # The duck used to be `device == "handset"`, so naming the very same
        # hardware by its ALSA name skipped it entirely.
        tts.play_wav(self.wav, tts.LOCAL_HANDSET_DEVICE)
        self.assertEqual(self._ctl_lines(), ["mute 1", "mute 0"])

    def test_unspecified_device_ducks(self):
        # crt-stt-speakback.sh / crt-secretary.py / crt-idle-teaser.sh all
        # called in with no device at all and fell through to ALSA `default`.
        # Nothing establishes that `default` is not the capture hardware, so
        # the unknown case ducks -- see ducks_capture()'s docstring.
        tts.play_wav(self.wav, "")
        self.assertEqual(self._ctl_lines(), ["mute 1", "mute 0"])

    def test_an_explicitly_named_other_device_does_not_duck(self):
        tts.play_wav(self.wav, tts.LOCAL_TV_DEVICE)
        self.assertEqual(self._ctl_lines(), [])

    def test_handset_unmutes_even_if_aplay_cannot_run(self):
        # aplay not installed at all: the real failure this stands for, and
        # now produced the real way (an empty PATH) rather than by patching
        # subprocess.run to raise. The duck must still be released -- a
        # console with no sound output must not also end up with no mic.
        os.environ["PATH"] = self.tmpdir + "/nonexistent-bin"
        with self.assertRaises(OSError):
            tts.play_wav(self.wav, "handset")
        self.assertEqual(self._ctl_lines(), ["mute 1", "mute 0"])


if __name__ == "__main__":
    unittest.main()
