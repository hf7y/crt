#!/usr/bin/env python3
# Offline tests for crt-stt-solo.py's STT gate (FOCUS.md "STT gate", 2026-07-20):
# addressed_to_console() decides whether an utterance was actually meant for
# the console (wake word, or a known stt-fixups.json mishear of it) before
# it's allowed to become a live Claude Code turn. No mic/VM/tmux needed --
# this is pure string matching against the real stt-fixups.json in bin/.
import importlib.util
import json
import os
import tempfile
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")
spec = importlib.util.spec_from_file_location("crt_stt_solo", os.path.join(BIN_DIR, "crt-stt-solo.py"))
stt_solo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stt_solo)


class TestGateDefaultsOff(unittest.TestCase):
    def test_gate_is_off_unless_env_set(self):
        # Importing the module with no CRT_STT_GATE in the environment must
        # not enable the gate -- the always-escalate path stays the default
        # until a human has watched this run live (nightly-batch.md's
        # acceptance-bar note).
        self.assertFalse(stt_solo.GATE)


class TestAddressedToConsole(unittest.TestCase):
    def test_wake_word_present(self):
        self.assertTrue(stt_solo.addressed_to_console("claude what time is it"))
        self.assertTrue(stt_solo.addressed_to_console("hey claude, run the tests"))
        self.assertTrue(stt_solo.addressed_to_console("Claude"))

    def test_no_wake_word_is_dropped(self):
        self.assertFalse(stt_solo.addressed_to_console("what a nice day"))
        self.assertFalse(stt_solo.addressed_to_console(""))

    def test_known_mishear_of_wake_word_counts(self):
        # "slide" -> confirmed mishear of "claude" in the real stt-fixups.json.
        self.assertTrue(stt_solo.addressed_to_console("slide over here and look"))

    def test_fragment_does_not_match_inside_another_word(self):
        # "landslide" contains the substring "slide" but is not the fixup's
        # whole-word fragment -- must not false-positive.
        self.assertFalse(stt_solo.addressed_to_console("landslide warning today"))

    def test_other_fixups_with_a_different_intent_dont_gate_open(self):
        # "read about" -> intent "ring the bell" in the real stt-fixups.json,
        # not "claude" -- must not be treated as a wake word.
        self.assertFalse(stt_solo.addressed_to_console("read about the news"))

    def test_custom_wake_word_and_fixups_override(self):
        fixups = {"gray dude": {"intent": "greydog"}}
        self.assertTrue(stt_solo.addressed_to_console("greydog fetch", wake_word="greydog", fixups=fixups))
        self.assertTrue(stt_solo.addressed_to_console("gray dude fetch", wake_word="greydog", fixups=fixups))
        self.assertFalse(stt_solo.addressed_to_console("nothing relevant", wake_word="greydog", fixups=fixups))


class TestLoadFixups(unittest.TestCase):
    def test_loads_real_file_and_skips_comment_key(self):
        fixups = stt_solo.load_fixups(stt_solo.FIXUPS_PATH)
        self.assertIn("slide", fixups)
        self.assertNotIn("_comment", fixups)

    def test_missing_file_yields_empty_dict(self):
        self.assertEqual(stt_solo.load_fixups("/nonexistent/stt-fixups.json"), {})

    def test_malformed_json_yields_empty_dict(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write("{not valid json")
            path = f.name
        try:
            self.assertEqual(stt_solo.load_fixups(path), {})
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
