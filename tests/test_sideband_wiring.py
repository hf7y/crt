#!/usr/bin/env python3
# Offline tests for the sideband state-transition wiring (SIDEBAND.md):
# crt-stt-solo.py's opt-in set_sideband_state(), and crt-tts.py's
# always-on mute-duck around play_wav(). No real mic/TTS backend needed.
import atexit
import importlib.util
import os
import shutil
import tempfile
import unittest

# Pin the live-console state defaults into tmp BEFORE any bin/ module is
# imported and reads them at module scope (2026-07-25). This file was one of
# five appending to the REAL ~/.crt -- the capture-duck control channel a
# running crt-stt-solo.py reads live, and the state crt-window-switcher.py
# reads to decide whether a brain is behind the screen. tests/run_tests.sh
# pins these for the whole suite; this covers running this file on its own.
_state = tempfile.mkdtemp(prefix="crt-test-state-")
atexit.register(shutil.rmtree, _state, ignore_errors=True)
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
        # self.stt.subprocess IS the real subprocess module (cached in
        # sys.modules by name), so assigning .run here mutates it globally.
        # Restore the original on every teardown -- even if a test
        # reassigns .run again mid-test (see test_subprocess_failure_is_swallowed)
        # -- so this doesn't leak into other test files under bare `pytest tests/` (crt#170).
        self.addCleanup(setattr, self.stt.subprocess, "run", self.stt.subprocess.run)
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


class TestSidebandCallSites(unittest.TestCase):
    """Witnesses the header comment above set_sideband_state() in
    bin/crt-stt-solo.py: it is the sole writer of "listening"/"thinking".
    crt#345 candidate 3 (OVERLAP_TRANSCRIBE) added two more "listening"
    sites: finish_utterance() consolidates the post-utterance "listening"
    call for both the blocking and background-drain paths, and spawning a
    background transcription returns to "listening" immediately rather than
    "thinking" (capture never stops for it) -- see finish_utterance() and
    the OVERLAP_TRANSCRIBE branch in main()."""

    def test_call_sites_are_exactly_listening_listening_listening_thinking(self):
        import ast
        path = os.path.join(BIN_DIR, "crt-stt-solo.py")
        with open(path) as f:
            tree = ast.parse(f.read(), path)
        states = []
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "set_sideband_state"):
                arg = node.args[0]
                self.assertIsInstance(arg, ast.Constant)
                states.append(arg.value)
        self.assertEqual(states, ["listening", "listening", "listening", "thinking"])


class TestVadIndicator(unittest.TestCase):
    """The visual counterpart to sideband (crt#344): same opt-in/
    best-effort contract, but paints tmux's status-right instead of an
    audio texture -- see set_vad_indicator()'s own header in
    bin/crt-stt-solo.py for why status-right is the venue."""

    def setUp(self):
        self.stt = load("crt_stt_solo_vad", "crt-stt-solo.py")
        self.calls = []
        self.addCleanup(setattr, self.stt.subprocess, "run", self.stt.subprocess.run)
        self.stt.subprocess.run = lambda *a, **kw: self.calls.append((a, kw)) or _FakeProc()
        self.stt._vad_indicator_last = None

    def test_off_by_default_no_subprocess_call(self):
        self.stt.VAD_INDICATOR = False
        self.stt.set_vad_indicator("onset")
        self.assertEqual(self.calls, [])

    def test_init_no_op_when_off(self):
        self.stt.VAD_INDICATOR = False
        self.stt.init_vad_indicator()
        self.assertEqual(self.calls, [])

    def test_enabled_sets_status_right_to_the_state_glyph(self):
        self.stt.VAD_INDICATOR = True
        self.stt.set_vad_indicator("onset")
        self.assertEqual(len(self.calls), 1)
        args = self.calls[0][0][0]
        self.assertEqual(args[:4], ["tmux", "set-option", "-t", self.stt.SESSION])
        self.assertEqual(args[4], "status-right")
        self.assertEqual(args[5], self.stt.VAD_INDICATOR_GLYPH["onset"])

    def test_repeated_same_state_is_deduped(self):
        self.stt.VAD_INDICATOR = True
        self.stt.set_vad_indicator("thinking")
        self.stt.set_vad_indicator("thinking")
        self.assertEqual(len(self.calls), 1)

    def test_state_change_is_not_deduped(self):
        self.stt.VAD_INDICATOR = True
        self.stt.set_vad_indicator("onset")
        self.stt.set_vad_indicator("thinking")
        self.assertEqual(len(self.calls), 2)

    def test_init_claims_the_status_bar_then_paints_armed(self):
        self.stt.VAD_INDICATOR = True
        self.stt.init_vad_indicator()
        options_set = [c[0][0][4] for c in self.calls if c[0][0][1] == "set-option"]
        self.assertIn("status", options_set)
        self.assertIn("status-left", options_set)
        self.assertIn("status-right-length", options_set)
        last = self.calls[-1][0][0]
        self.assertEqual(last[4:], ["status-right", self.stt.VAD_INDICATOR_GLYPH["armed"]])

    def test_subprocess_failure_is_swallowed(self):
        self.stt.VAD_INDICATOR = True

        def boom(*a, **kw):
            raise OSError("no such file")

        self.stt.subprocess.run = boom
        # Must not raise -- a broken tmux can never crash real
        # transcription, same contract as set_sideband_state().
        self.stt.set_vad_indicator("onset")
        self.stt.init_vad_indicator()


class TestVadIndicatorCallSites(unittest.TestCase):
    """Witnesses set_vad_indicator()'s own header comment in
    bin/crt-stt-solo.py: init paints armed once at startup, then onset at
    the threshold crossing, thinking right before a blocking transcribe(),
    armed once the pipeline is done with the utterance either way
    (transcribed, or too short to count). crt#345 candidate 3
    (OVERLAP_TRANSCRIBE) added a second "armed" site: finish_utterance()'s
    terminal call, shared by the blocking path and the background-drain
    path, plus the immediate "armed" a spawned background transcription
    sets rather than waiting in "thinking" -- see finish_utterance() and
    the OVERLAP_TRANSCRIBE branch in main(). finish_utterance() is defined
    before the capture loop starts, so its "armed" call sorts ahead of the
    loop's own onset/thinking sites below (this list is source order, not
    call order)."""

    def test_call_sites_are_exactly_armed_armed_onset_armed_armed_thinking(self):
        import ast
        path = os.path.join(BIN_DIR, "crt-stt-solo.py")
        with open(path) as f:
            tree = ast.parse(f.read(), path)
        states = []
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "set_vad_indicator"):
                arg = node.args[0]
                self.assertIsInstance(arg, ast.Constant)
                states.append(arg.value)
        self.assertEqual(states,
                         ["armed", "armed", "onset", "armed", "armed", "thinking"])


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

        # self.tts.subprocess is the real, shared subprocess module -- restore
        # it on teardown so this doesn't leak into other test files (crt#170).
        self.addCleanup(setattr, self.tts.subprocess, "run", self.tts.subprocess.run)
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
