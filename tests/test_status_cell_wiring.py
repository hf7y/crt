#!/usr/bin/env python3
# Offline tests for crt#344's status-cell wiring: crt-stt-solo.py's opt-in
# set_status_cell(), a persistent tmux status-right label keyed to the same
# VAD moments as SIDEBAND.md's audio state (see test_sideband_wiring.py).
# No real mic/tmux needed.
import atexit
import importlib.util
import os
import shutil
import tempfile
import unittest

# Pin the live-console state defaults into tmp BEFORE any bin/ module is
# imported and reads them at module scope -- see test_sideband_wiring.py's
# header for why this matters when this file runs on its own.
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


class TestSttSoloStatusCellGate(unittest.TestCase):
    def setUp(self):
        self.stt = load("crt_stt_solo", "crt-stt-solo.py")
        self.calls = []
        # self.stt.subprocess IS the real subprocess module (cached in
        # sys.modules by name) -- restore it on teardown so this doesn't
        # leak into other test files (crt#170).
        self.addCleanup(setattr, self.stt.subprocess, "run", self.stt.subprocess.run)
        self.stt.subprocess.run = lambda *a, **kw: self.calls.append((a, kw)) or _FakeProc()

    def test_off_by_default_no_subprocess_call(self):
        self.stt.STATUS_CELL = False
        self.stt.set_status_cell("hearing")
        self.assertEqual(self.calls, [])

    def test_enabled_sets_tmux_status_right_with_label(self):
        self.stt.STATUS_CELL = True
        self.stt.SESSION = "claude"
        self.stt.set_status_cell("thinking")
        self.assertEqual(len(self.calls), 1)
        args = self.calls[0][0][0]
        self.assertEqual(args[0], "tmux")
        self.assertIn("set-option", args)
        self.assertIn("status-right", args)
        self.assertIn("claude", args)
        self.assertIn("thinking", args[-1])

    def test_enabled_empty_label_clears_to_blank(self):
        self.stt.STATUS_CELL = True
        self.stt.set_status_cell("")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][0][0][-1], "")

    def test_subprocess_failure_is_swallowed(self):
        self.stt.STATUS_CELL = True

        def boom(*a, **kw):
            raise OSError("no such file")

        self.stt.subprocess.run = boom
        # Must not raise -- a broken tmux call can never crash real
        # transcription, same contract as set_sideband_state().
        self.stt.set_status_cell("hearing")


class TestStatusCellCallSites(unittest.TestCase):
    """Witnesses the header comment above set_status_cell() in
    bin/crt-stt-solo.py: onset -> "hearing", utterance-close -> "thinking",
    then back to "" once the transcript attempt (success, failure, or too
    short to try) resolves -- so the cell never sticks on a stale state."""

    def test_call_sites_are_exactly_hearing_thinking_blank_blank(self):
        import ast
        path = os.path.join(BIN_DIR, "crt-stt-solo.py")
        with open(path) as f:
            tree = ast.parse(f.read(), path)
        states = []
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "set_status_cell"):
                arg = node.args[0]
                self.assertIsInstance(arg, ast.Constant)
                states.append(arg.value)
        self.assertEqual(states, ["hearing", "thinking", "", ""])


if __name__ == "__main__":
    unittest.main()
