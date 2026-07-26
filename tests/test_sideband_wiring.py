#!/usr/bin/env python3
# Offline tests for the sideband state-transition wiring (SIDEBAND.md):
# crt-stt-solo.py's opt-in set_sideband_state(), and crt-tts.py's
# always-on mute-duck around play_wav(). No real mic/TTS backend needed.
import importlib.util
import os
import tempfile
import unittest

# Pin the live-console state defaults into tmp BEFORE any bin/ module is
# imported and reads them at module scope (2026-07-25). This file was one of
# five appending to the REAL ~/.crt -- the capture-duck control channel a
# running crt-stt-solo.py reads live, and the state crt-window-switcher.py
# reads to decide whether a brain is behind the screen. tests/run_tests.sh
# pins these for the whole suite; this covers running this file on its own.
_state = tempfile.mkdtemp(prefix="crt-test-state-")
os.environ.setdefault("CRT_CTL_FILE", os.path.join(_state, "ctl"))
os.environ.setdefault("CRT_CLAUDE_ACTIVE_STATE",
                      os.path.join(_state, "claude-window-active.state"))
os.environ.setdefault("CRT_THOUGHT_LOG", os.path.join(_state, "thoughts.log"))
os.environ.setdefault("CRT_STT_GATE_LOG", os.path.join(_state, "thoughts.log"))

BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, os.path.join(BIN_DIR, path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestSttSoloSidebandGate(unittest.TestCase):
    def setUp(self):
        self.stt = load("crt_stt_solo", "crt-stt-solo.py")
        self.calls = []
        self.stt.subprocess.run = lambda *a, **kw: self.calls.append((a, kw)) or _FakeProc()

    def test_off_by_default_no_subprocess_call(self):
        self.stt.SIDEBAND = False
        self.stt.set_sideband_state("listening")
        self.assertEqual(self.calls, [])

    def test_enabled_calls_the_setter_script_with_state(self):
        self.stt.SIDEBAND = True
        self.stt.set_sideband_state("thinking")
        self.assertEqual(len(self.calls), 1)
        args = self.calls[0][0][0]
        self.assertEqual(args[0], "bash")
        self.assertIn("crt-sideband-set.sh", args[1])
        self.assertEqual(args[2], "thinking")

    def test_subprocess_failure_is_swallowed(self):
        self.stt.SIDEBAND = True

        def boom(*a, **kw):
            raise OSError("no such file")

        self.stt.subprocess.run = boom
        # Must not raise -- a broken sideband setter can never crash real
        # transcription, same contract as predictive_flash().
        self.stt.set_sideband_state("listening")


class _FakeProc:
    returncode = 0


class TestTtsSidebandDuck(unittest.TestCase):
    def setUp(self):
        self.tts = load("crt_tts", "crt-tts.py")
        self.tmpdir = tempfile.mkdtemp()
        self.tts.SIDEBAND_MUTE_FILE = os.path.join(self.tmpdir, "sideband.mute")
        # Stub out the actual playback so this needs no real audio device.
        self.observed_during_playback = {}

        def fake_aplay_run(cmd, *a, **kw):
            self.observed_during_playback["mute_exists"] = os.path.exists(self.tts.SIDEBAND_MUTE_FILE)
            return _FakeProc()

        self.tts.subprocess.run = fake_aplay_run

    def test_mute_file_present_during_playback_and_removed_after(self):
        fd, wav = tempfile.mkstemp(suffix=".wav", dir=self.tmpdir)
        os.close(fd)
        self.tts.play_wav(wav, None)
        self.assertTrue(self.observed_during_playback.get("mute_exists"))
        self.assertFalse(os.path.exists(self.tts.SIDEBAND_MUTE_FILE))

    def test_mute_file_removed_even_if_playback_raises(self):
        def boom(cmd, *a, **kw):
            raise RuntimeError("aplay exploded")

        self.tts.subprocess.run = boom
        fd, wav = tempfile.mkstemp(suffix=".wav", dir=self.tmpdir)
        os.close(fd)
        with self.assertRaises(RuntimeError):
            self.tts.play_wav(wav, None)
        self.assertFalse(os.path.exists(self.tts.SIDEBAND_MUTE_FILE))


if __name__ == "__main__":
    unittest.main()
