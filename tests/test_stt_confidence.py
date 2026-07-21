#!/usr/bin/env python3
# Offline tests for bin/crt-stt-confidence.py against synthetic state --
# no real ~/.crt history needed. See test_predict.py for the same pattern.
import importlib.util
import os
import random
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")
spec = importlib.util.spec_from_file_location(
    "crt_stt_confidence", os.path.join(BIN_DIR, "crt-stt-confidence.py"))
conf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(conf)


class TestNormalizeKey(unittest.TestCase):
    def test_lowercases_and_strips_punctuation(self):
        self.assertEqual(conf.normalize_key("Any Reports for me?"),
                          "any reports for me")

    def test_collapses_whitespace(self):
        self.assertEqual(conf.normalize_key("what's   up"), "whats up")

    def test_different_text_different_key(self):
        self.assertNotEqual(conf.normalize_key("any reports"),
                             conf.normalize_key("any reports today"))


class TestCallProbability(unittest.TestCase):
    def test_unknown_key_is_full_probability(self):
        self.assertEqual(conf.call_probability("brand new phrase", {}), 1.0)

    def test_decays_with_confirmed_hits(self):
        state = {"any reports for me": {"confirmed_hits": 3, "claude_hits": 3}}
        p = conf.call_probability("any reports for me", state)
        self.assertLess(p, 1.0)
        self.assertGreater(p, 0.0)

    def test_monotonically_decreases_with_more_hits(self):
        prev = 1.0
        for hits in range(1, 10):
            state = {"k": {"confirmed_hits": hits, "claude_hits": hits}}
            p = conf.call_probability("k", state)
            self.assertLessEqual(p, prev)
            prev = p

    def test_never_goes_below_floor(self):
        state = {"k": {"confirmed_hits": 1000, "claude_hits": 1000}}
        p = conf.call_probability("k", state)
        self.assertGreaterEqual(p, conf.FLOOR_P)
        self.assertAlmostEqual(p, conf.FLOOR_P)


class TestShouldCallClaude(unittest.TestCase):
    def test_unknown_utterance_always_calls(self):
        state = {}
        rng = random.Random(0)
        for _ in range(20):
            self.assertTrue(conf.should_call_claude("never seen before", state, rng))

    def test_heavily_confirmed_utterance_rarely_calls(self):
        state = {"ok": {"confirmed_hits": 20, "claude_hits": 20}}
        rng = random.Random(1)
        calls = sum(conf.should_call_claude("ok", state, rng) for _ in range(500))
        # floor is 3%, so out of 500 draws expect roughly 15 -- generous bounds
        self.assertLess(calls, 60)


class TestRecordHelpers(unittest.TestCase):
    def test_record_confirmed_increments_and_creates_entry(self):
        state = {}
        conf.record_confirmed("ping", state)
        conf.record_confirmed("ping", state)
        self.assertEqual(state["ping"]["confirmed_hits"], 2)

    def test_record_claude_call_increments_separately(self):
        state = {}
        conf.record_claude_call("ping", state)
        conf.record_confirmed("ping", state)
        self.assertEqual(state["ping"]["claude_hits"], 1)
        self.assertEqual(state["ping"]["confirmed_hits"], 1)

    def test_normalization_shared_across_record_and_probability(self):
        state = {}
        for _ in range(10):
            conf.record_confirmed("Any Reports?", state)
        p = conf.call_probability(conf.normalize_key("any reports"), state)
        self.assertLess(p, 0.1)


class TestStatePersistence(unittest.TestCase):
    def test_save_and_load_roundtrip(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sub", "state.json")
            state = {}
            conf.record_confirmed("hello", state)
            conf.save_state(state, path)
            loaded = conf.load_state(path)
            self.assertEqual(loaded, state)

    def test_load_missing_file_returns_empty(self):
        self.assertEqual(conf.load_state("/nonexistent/path/state.json"), {})


if __name__ == "__main__":
    unittest.main()
