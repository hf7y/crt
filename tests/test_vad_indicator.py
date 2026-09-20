#!/usr/bin/env python3
# Offline tests for the visual VAD indicator (crt#344): crt-stt-solo.py's
# opt-in set_vad_indicator()/init_vad_indicator(). No real tmux session
# needed -- subprocess.run is stubbed, same pattern as
# tests/test_sideband_wiring.py.
import atexit
import importlib.util
import os
import shutil
import tempfile
import unittest

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


class _FakeProc:
    returncode = 0


class TestVadIndicator(unittest.TestCase):
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
    """Witnesses the header comment above set_vad_indicator() in
    bin/crt-stt-solo.py: init_vad_indicator() paints armed once at startup,
    then onset at the threshold crossing, thinking right before
    transcribe(), armed once the pipeline is done with the utterance
    either way (transcribed, or too short to count)."""

    def test_call_sites_are_exactly_armed_onset_thinking_armed_armed(self):
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
        self.assertEqual(states, ["armed", "onset", "thinking", "armed", "armed"])


if __name__ == "__main__":
    unittest.main()
