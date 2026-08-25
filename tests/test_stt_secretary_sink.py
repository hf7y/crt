#!/usr/bin/env python3
# Offline tests for crt-stt-solo.py's CRT_STT_SINK=secretary routing
# (PARKING-LOT.md's "Local-first STT routing" plan, 2026-07-21) -- no
# mic/tmux/live crt-secretary.py needed; send_to_claude/send_to_secretary
# are monkeypatched to record calls instead of touching tmux/Popen.
import importlib.util
import os
import tempfile
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")


def load_stt_solo():
    spec = importlib.util.spec_from_file_location("crt_stt_solo", os.path.join(BIN_DIR, "crt-stt-solo.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestSecretarySinkRouting(unittest.TestCase):
    def setUp(self):
        self.stt = load_stt_solo()
        self.tmpdir = tempfile.mkdtemp()
        self.stt.STT_LOG = os.path.join(self.tmpdir, "stt.log")
        self.stt.GATE_LOG = os.path.join(self.tmpdir, "thoughts.log")
        self.stt.SINK = "secretary"
        self.stt.GATE = False
        self.claude_calls = []
        self.secretary_calls = []
        self.stt.send_to_claude = lambda text, key: self.claude_calls.append((text, key))
        self.stt.send_to_secretary = lambda text: self.secretary_calls.append(text)

    def test_ordinary_utterance_routes_to_secretary_not_claude(self):
        self.stt.emit("what time is it")
        self.assertEqual(self.secretary_calls, ["what time is it"])
        self.assertEqual(self.claude_calls, [])

    def test_control_keyword_still_goes_straight_to_tmux(self):
        self.stt.emit("yes")
        self.assertEqual(self.claude_calls, [("yes", "yes")])
        self.assertEqual(self.secretary_calls, [])

    def test_gate_still_applies_in_secretary_mode(self):
        self.stt.GATE = True
        self.stt.emit("just some ambient room chatter")
        self.assertEqual(self.secretary_calls, [])
        self.assertEqual(self.claude_calls, [])

    def test_wake_word_passes_gate_and_routes_to_secretary(self):
        self.stt.GATE = True
        self.stt.emit("claude what time is it")
        self.assertEqual(self.secretary_calls, ["claude what time is it"])

    def test_claude_sink_unaffected_default_behavior(self):
        self.stt.SINK = "claude"
        self.stt.emit("what time is it")
        self.assertEqual(self.claude_calls, [("what time is it", "whattimeisit")])
        self.assertEqual(self.secretary_calls, [])

    def test_free_text_utterance_logs_to_thoughts_for_mono_window(self):
        # window 1 ("mono") previously only showed Claude's own replies --
        # a real free-text utterance that gets routed onward should also
        # show up in thoughts.log so mono displays both sides.
        self.stt.emit("what time is it")
        with open(self.stt.GATE_LOG) as f:
            contents = f.read()
        self.assertIn("[you] what time is it", contents)

    def test_control_keyword_does_not_clutter_thoughts_log(self):
        self.stt.emit("yes")
        # log_user_thought is never called for a control keystroke, so the
        # file may not even exist yet -- that (no "[you]" line, period) is
        # the actual thing under test, not any particular file state.
        contents = ""
        if os.path.exists(self.stt.GATE_LOG):
            with open(self.stt.GATE_LOG) as f:
                contents = f.read()
        self.assertNotIn("[you]", contents)

    def test_gated_utterance_is_not_logged_as_user_thought(self):
        self.stt.GATE = True
        self.stt.emit("just some ambient room chatter")
        contents = ""
        if os.path.exists(self.stt.GATE_LOG):
            with open(self.stt.GATE_LOG) as f:
                contents = f.read()
        self.assertNotIn("[you]", contents)


class TestPersonaControlOverride(unittest.TestCase):
    """crt#34: "next" is CONTROL's Down-arrow AND crt-media-player.py's
    skip -- the persona owns the word, so is_control must check which
    persona is active rather than always favoring CONTROL."""

    def setUp(self):
        self.stt = load_stt_solo()
        self.tmpdir = tempfile.mkdtemp()
        self.stt.STT_LOG = os.path.join(self.tmpdir, "stt.log")
        self.stt.GATE_LOG = os.path.join(self.tmpdir, "thoughts.log")
        self.stt.SINK = "secretary"
        self.stt.GATE = False
        self.claude_calls = []
        self.secretary_calls = []
        self.stt.send_to_claude = lambda text, key: self.claude_calls.append((text, key))
        self.stt.send_to_secretary = lambda text: self.secretary_calls.append(text)

    def test_next_is_the_down_arrow_when_media_is_not_active(self):
        self.stt.media_player.is_media_active = lambda: False
        self.stt.emit("next")
        self.assertEqual(self.claude_calls, [("next", "next")])
        self.assertEqual(self.secretary_calls, [])

    def test_next_reaches_the_media_playbook_when_media_is_active(self):
        self.stt.media_player.is_media_active = lambda: True
        self.stt.emit("next")
        self.assertEqual(self.secretary_calls, ["next"])
        self.assertEqual(self.claude_calls, [])

    def test_other_control_words_are_unaffected_by_media_state(self):
        self.stt.media_player.is_media_active = lambda: True
        self.stt.emit("yes")
        self.assertEqual(self.claude_calls, [("yes", "yes")])
        self.assertEqual(self.secretary_calls, [])


if __name__ == "__main__":
    unittest.main()
