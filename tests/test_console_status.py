#!/usr/bin/env python3
# Offline tests for the persistent status cell (crt#344): crt-stt-solo.py's
# set_console_status(), which pushes to tmux's session-wide status-line
# instead of set_hud()'s pane-local flash. No real tmux/mic needed.
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


class TestConsoleStatusCell(unittest.TestCase):
    def setUp(self):
        self.stt = load("crt_stt_solo_console_status", "crt-stt-solo.py")
        self.calls = []
        self.addCleanup(setattr, self.stt.subprocess, "run", self.stt.subprocess.run)
        self.stt.subprocess.run = lambda *a, **kw: self.calls.append((a, kw)) or _FakeProc()
        self.stt.CONSOLE_STATUS = True
        self.stt.console_status_text = None
        self.stt.console_status_until = 0.0

    def test_pushes_to_tmux_status_right_on_the_session(self):
        self.stt.SESSION = "claude"
        self.stt.set_console_status("listening")
        self.assertEqual(len(self.calls), 1)
        args = self.calls[0][0][0]
        self.assertEqual(args, ["tmux", "set-option", "-t", "claude", "status-right", "listening"])

    def test_off_by_default_flag_is_a_no_op(self):
        self.stt.CONSOLE_STATUS = False
        self.stt.set_console_status("listening")
        self.assertEqual(self.calls, [])

    def test_identical_text_is_not_repushed(self):
        self.stt.set_console_status("listening")
        self.stt.set_console_status("listening")
        self.assertEqual(len(self.calls), 1)

    def test_new_text_replaces_the_old(self):
        self.stt.set_console_status("listening")
        self.stt.set_console_status("transcribing")
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[1][0][0][-1], "transcribing")

    def test_secs_schedules_a_revert_deadline(self):
        before = self.stt.time.time()
        self.stt.set_console_status("hello there", secs=2.5)
        self.assertGreater(self.stt.console_status_until, before)

    def test_no_secs_leaves_the_state_open_ended(self):
        self.stt.set_console_status("listening")
        self.assertEqual(self.stt.console_status_until, 0.0)

    def test_subprocess_failure_is_swallowed(self):
        def boom(*a, **kw):
            raise OSError("no such file")
        self.stt.subprocess.run = boom
        # Must not raise -- same contract as set_sideband_state/predictive_flash.
        self.stt.set_console_status("listening")


class TestConsoleStatusCallSites(unittest.TestCase):
    """Witnesses the header comment above set_console_status() in
    bin/crt-stt-solo.py: onset, utterance-close, and transcript-back each
    call it, so the persistent cell can't silently lose one of its three
    states as the surrounding code changes."""

    def test_call_sites_cover_onset_thinking_and_transcript(self):
        import ast
        path = os.path.join(BIN_DIR, "crt-stt-solo.py")
        with open(path) as f:
            tree = ast.parse(f.read(), path)
        texts = []
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "set_console_status"):
                arg = node.args[0]
                texts.append(arg.value if isinstance(arg, ast.Constant) else None)
        # Literal onset/thinking states, plus at least one call whose text is
        # a variable (the failure report and the transcript itself) -- both
        # of those show up as `None` here since they aren't ast.Constant.
        self.assertIn("listening", texts)
        self.assertIn("transcribing", texts)
        self.assertGreaterEqual(len(texts), 4)


if __name__ == "__main__":
    unittest.main()
