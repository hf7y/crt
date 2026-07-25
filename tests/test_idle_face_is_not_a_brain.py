#!/usr/bin/env python3
# Offline tests for "the pane behind the idle face is not a brain"
# (2026-07-25, nineteenth nightly cycle). See bin/crt_config.py's PANE_ENV
# block for the finding; the short version:
#
# bin/crt-console.sh hands the stt window CRT_TMUX_PANE=0.0 on one line, for
# both layouts. In the idle-lean layout -- the one potato boots
# (CRT_NO_IDLE_CLAUDE=1) -- window 0 is crt-screensaver.py, not Claude Code.
# Two engines typed into it anyway:
#
#   crt-stt-solo.py       single-word CONTROL utterances, which bypass the
#                         wake gate by design, so any ambient "okay"/"no" in
#                         the room got typed onto the console's own face.
#   crt-secretary.py      the entire escalation path whenever
#                         CRT_CLAUDE_REMOTE_PORT is 0 -- i.e. after a plain
#                         `crt-mandark.sh off`. tmux ACCEPTS those keys (the
#                         pane is real), so every delivery check passed, and
#                         wait_for_claude_reply() then diffed the potato's
#                         own moving caption looking for an answer.
#
# The tests that matter here are the negative ones: nothing is sent, and the
# historical layout is byte-for-byte unaffected.
import importlib.util
import os
import unittest

BIN_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))

IDLE_LEAN_ENV = {"CRT_IDLE_FACE_WINDOW": "0", "CRT_TMUX_PANE": "0.0"}
HISTORICAL_ENV = {"CRT_TMUX_PANE": "0.0"}          # CRT_IDLE_FACE_WINDOW unset


def load(name, filename, env):
    """A fresh module with `env` applied over the real environment: both
    engines read this config at import, which is also how the live processes
    see it (one env per tmux window, crt-console.sh)."""
    saved = {k: os.environ.get(k) for k in
             ("CRT_IDLE_FACE_WINDOW", "CRT_TMUX_PANE", "CRT_CLAUDE_REMOTE_PORT")}
    for k in saved:
        os.environ.pop(k, None)
    os.environ.update(env)
    try:
        spec = importlib.util.spec_from_file_location(name, os.path.join(BIN_DIR, filename))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class TestPaneIsIdleFace(unittest.TestCase):
    def setUp(self):
        self.cfg = load("crt_config_under_test", "crt_config.py", {})

    def test_pane_window_drops_the_pane_half(self):
        self.assertEqual(self.cfg.pane_window("0.0"), "0")
        self.assertEqual(self.cfg.pane_window("0"), "0")
        self.assertEqual(self.cfg.pane_window("book.1"), "book")
        self.assertEqual(self.cfg.pane_window(" 0.0 "), "0")
        self.assertEqual(self.cfg.pane_window(None), "")

    def test_idle_lean_layout_is_the_idle_face(self):
        self.assertTrue(self.cfg.pane_is_idle_face(env=dict(IDLE_LEAN_ENV)))

    def test_historical_layout_is_a_brain(self):
        # The whole safety property: with CRT_IDLE_FACE_WINDOW unset, window 0
        # really is a live Claude and every caller behaves as it always has.
        self.assertFalse(self.cfg.pane_is_idle_face(env=dict(HISTORICAL_ENV)))

    def test_blank_idle_face_var_is_a_brain(self):
        # crt-console.sh `unset`s it, but a shell that exported an empty
        # string must not read as "the idle face is window ''".
        self.assertFalse(self.cfg.pane_is_idle_face(
            env={"CRT_IDLE_FACE_WINDOW": "  ", "CRT_TMUX_PANE": "0.0"}))

    def test_a_pane_on_another_window_is_not_the_idle_face(self):
        self.assertFalse(self.cfg.pane_is_idle_face(
            env={"CRT_IDLE_FACE_WINDOW": "0", "CRT_TMUX_PANE": "book.0"}))

    def test_default_pane_is_window_zero(self):
        # Both engines default CRT_TMUX_PANE to "0" when it is unset.
        self.assertTrue(self.cfg.pane_is_idle_face(env={"CRT_IDLE_FACE_WINDOW": "0"}))

    def test_report_names_both_halves(self):
        report = self.cfg.idle_face_pane_report(env=dict(IDLE_LEAN_ENV))
        self.assertIn("CRT_TMUX_PANE=0.0", report)
        self.assertIn("CRT_IDLE_FACE_WINDOW=0", report)
        # It lands on a 40-column tube via window 1; keep it to a couple of
        # lines there rather than a paragraph.
        self.assertLessEqual(len(report), 120)


class TestSttSoloControlKeys(unittest.TestCase):
    """crt-stt-solo.py must not press keys into the idle face."""

    def _loaded(self, env):
        mod = load("crt_stt_solo_idle_face", "crt-stt-solo.py", env)
        self.sent = []
        mod.subprocess.run = lambda *a, **kw: self.sent.append(a[0])
        self.thoughts = []
        mod.log_console_thought = lambda text, *a, **kw: self.thoughts.append(text)
        return mod

    def test_idle_lean_sends_nothing(self):
        mod = self._loaded(IDLE_LEAN_ENV)
        mod.send_to_claude("yes", "yes")
        self.assertEqual(self.sent, [],
                         "a control keystroke was typed into the potato screensaver")

    def test_idle_lean_says_so_on_window_one(self):
        mod = self._loaded(IDLE_LEAN_ENV)
        mod.send_to_claude("yes", "yes")
        mod.send_to_claude("no", "no")
        self.assertEqual(len(self.thoughts), 1,
                         "window 1 should hear this once, not once per stray word")
        self.assertIn("CRT_IDLE_FACE_WINDOW", self.thoughts[0])

    def test_historical_layout_still_presses_the_key(self):
        mod = self._loaded(HISTORICAL_ENV)
        mod.send_to_claude("yes", "yes")
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0][-1], "Enter")
        self.assertIn("claude:0.0", self.sent[0])

    def test_historical_layout_still_types_free_text(self):
        mod = self._loaded(HISTORICAL_ENV)
        mod.send_to_claude("what time is it", "whattimeisit")
        self.assertEqual(len(self.sent), 2)
        self.assertIn("what time is it", self.sent[0])
        self.assertEqual(self.sent[1][-1], "Enter")

    def test_the_control_earcon_is_suppressed_with_it(self):
        # Not a separate decision: an earcon is how this console says "done".
        mod = self._loaded(IDLE_LEAN_ENV)
        self.assertTrue(mod.PANE_IS_IDLE_FACE)
        with open(os.path.join(BIN_DIR, "crt-stt-solo.py")) as f:
            src = f.read()
        self.assertIn('if EARCON_ON_CONTROL and is_control and not PANE_IS_IDLE_FACE:', src)


class TestSecretaryLocalRoute(unittest.TestCase):
    """crt-secretary.py must not hold a conversation with a screensaver."""

    def _loaded(self, env):
        mod = load("crt_secretary_idle_face", "crt-secretary.py", env)
        self.ran = []

        class _R:
            returncode = 0
            stdout = "potato\n"
            stderr = ""

        mod.sh = lambda cmd, **kw: (self.ran.append(cmd), _R())[1]
        self.unreachable = []
        mod.log_brain_unreachable = lambda text, detail, **kw: \
            self.unreachable.append((text, detail))
        return mod

    def test_idle_lean_refuses_to_send(self):
        mod = self._loaded(IDLE_LEAN_ENV)
        self.assertFalse(mod.send_to_claude("what time is it"),
                         "the utterance was typed into the idle face and called delivered")
        self.assertEqual([c for c in self.ran if "send-keys" in c], [])

    def test_idle_lean_logs_why(self):
        mod = self._loaded(IDLE_LEAN_ENV)
        mod.send_to_claude("what time is it")
        self.assertEqual(len(self.unreachable), 1)
        self.assertIn("idle face", self.unreachable[0][1])

    def test_idle_lean_has_no_pane_to_read(self):
        # The dangerous half: the screensaver's pane reads FINE, and its
        # caption moves, so a diff of it comes back looking like a reply.
        mod = self._loaded(IDLE_LEAN_ENV)
        self.assertIsNone(mod.capture_pane())

    def test_wait_for_reply_cannot_speak_the_potato(self):
        # End to end through the real waiter: with no readable pane it must
        # report "unobserved" rather than hand route_claude_reply() a
        # screensaver frame to say out loud.
        mod = self._loaded(IDLE_LEAN_ENV)
        mod.CLAUDE_POLL = 0
        reply, status = mod.wait_for_claude_reply("whatever was there before")
        self.assertEqual(reply, "")
        self.assertEqual(status, "unobserved")

    def test_historical_layout_still_sends_and_reads(self):
        mod = self._loaded(HISTORICAL_ENV)
        self.assertTrue(mod.send_to_claude("what time is it"))
        self.assertEqual(len([c for c in self.ran if "send-keys" in c]), 2)
        self.assertEqual(mod.capture_pane(), "potato\n")

    def test_the_remote_route_is_untouched(self):
        # CRT_CLAUDE_REMOTE_PORT set is the live potato config, and it never
        # reaches the local branch at all -- assert that this change cannot
        # have moved it.
        mod = self._loaded(dict(IDLE_LEAN_ENV, CRT_CLAUDE_REMOTE_PORT="8993"))
        seen = []
        mod._bridge_request = lambda cmd, port, timeout=None: (seen.append(cmd), "OK")[1]
        self.assertTrue(mod.send_to_claude("what time is it"))
        self.assertEqual(seen, ["SEND what time is it"])


if __name__ == "__main__":
    unittest.main()
