#!/usr/bin/env python3
# Offline tests for bin/crt-predict.py against synthetic stt.log-shaped
# data -- no real transcript history needed.
import importlib.util
import os
import tempfile
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")
spec = importlib.util.spec_from_file_location("crt_predict", os.path.join(BIN_DIR, "crt-predict.py"))
predict = importlib.util.module_from_spec(spec)
spec.loader.exec_module(predict)

SAMPLE_LOG = """\
09:01:02  any reports for me
09:15:44  any reports for me
14:20:01  play the thing
14:21:09  next
09:30:00  any reports for me
23:59:59  goodnight
"""


class TestParseLog(unittest.TestCase):
    def test_parses_hour_and_text(self):
        with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False) as f:
            f.write(SAMPLE_LOG)
            path = f.name
        try:
            entries = predict.parse_log(path)
            self.assertEqual(len(entries), 6)
            self.assertEqual(entries[0], (9, "any reports for me"))
            self.assertEqual(entries[2], (14, "play the thing"))
        finally:
            os.unlink(path)

    def test_missing_file_yields_empty(self):
        self.assertEqual(predict.parse_log("/nonexistent/path/stt.log"), [])


class TestBuildAndGuess(unittest.TestCase):
    def setUp(self):
        with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False) as f:
            f.write(SAMPLE_LOG)
            self.path = f.name
        self.model = predict.build_model(self.path)

    def tearDown(self):
        os.unlink(self.path)

    def test_most_frequent_utterance_wins_overall(self):
        self.assertEqual(predict.guess(self.model), "any reports for me")

    def test_hour_bucket_used_when_available(self):
        # Hour 14 only ever saw "play the thing" and "next" -- the overall
        # top ("any reports for me") must NOT leak into a 14:xx guess.
        g = predict.guess(self.model, hour=14)
        self.assertIn(g, ("play the thing", "next"))
        self.assertNotEqual(g, "any reports for me")

    def test_unseen_hour_falls_back_to_overall(self):
        g = predict.guess(self.model, hour=3)
        self.assertEqual(g, "any reports for me")

    def test_empty_model_guesses_empty_string(self):
        empty = predict.build_model("/nonexistent/path/stt.log")
        self.assertEqual(predict.guess(empty), "")

    def test_save_and_load_roundtrip(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            model_path = f.name
        try:
            predict.save_model(self.model, model_path)
            loaded = predict.load_model(model_path)
            self.assertEqual(predict.guess(loaded), predict.guess(self.model))
        finally:
            os.unlink(model_path)


class TestBigramFallback(unittest.TestCase):
    def test_chains_a_plausible_guess_with_no_repeats(self):
        with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False) as f:
            f.write("10:00:00  turn on the tv\n10:01:00  turn down the volume\n")
            path = f.name
        try:
            model = predict.build_model(path)
            # No utterance repeats, so overall_top's top entry has count 1 --
            # guess() should still return *something* non-empty via that top
            # entry rather than nothing.
            g = predict.guess(model)
            self.assertTrue(g)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
