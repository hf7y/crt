#!/usr/bin/env python3
# Tests for bin/crt-stt-training-merge.py -- the background auto-merge
# half of "STT training in the background" (2026-07-21, Zach's direct
# ask). No live files touched by default; every test uses temp paths.
import importlib.util
import json
import os
import tempfile
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")
spec = importlib.util.spec_from_file_location("crt_stt_training_merge", os.path.join(BIN_DIR, "crt-stt-training-merge.py"))
tm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tm)


class TestMergeCandidates(unittest.TestCase):
    def test_adds_new_candidate_tagged_auto(self):
        existing = {"slide": {"intent": "claude", "confidence": "confirmed"}}
        candidates = {"friction": {"intent": "fiction", "confidence": "candidate", "note": "seen 3x"}}
        merged, added = tm.merge_candidates(existing, candidates)
        self.assertEqual(added, ["friction"])
        self.assertEqual(merged["friction"]["confidence"], "auto")
        self.assertEqual(merged["friction"]["intent"], "fiction")

    def test_never_touches_an_existing_key(self):
        existing = {"slide": {"intent": "claude", "confidence": "confirmed", "note": "human-verified"}}
        candidates = {"slide": {"intent": "something else entirely", "confidence": "candidate"}}
        merged, added = tm.merge_candidates(existing, candidates)
        self.assertEqual(added, [])
        self.assertEqual(merged["slide"]["confidence"], "confirmed")
        self.assertEqual(merged["slide"]["intent"], "claude")

    def test_empty_candidates_changes_nothing(self):
        existing = {"slide": {"intent": "claude", "confidence": "confirmed"}}
        merged, added = tm.merge_candidates(existing, {})
        self.assertEqual(added, [])
        self.assertEqual(merged, existing)

    def test_original_existing_dict_not_mutated(self):
        existing = {"slide": {"intent": "claude", "confidence": "confirmed"}}
        tm.merge_candidates(existing, {"new": {"intent": "x", "confidence": "candidate"}})
        self.assertNotIn("new", existing)


class TestLoadFixupsFile(unittest.TestCase):
    def test_missing_file_returns_empty_dict(self):
        self.assertEqual(tm.load_fixups_file("/nonexistent/stt-fixups.json"), {})

    def test_malformed_file_returns_empty_dict(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "stt-fixups.json")
            with open(path, "w") as f:
                f.write("{not valid json")
            self.assertEqual(tm.load_fixups_file(path), {})

    def test_reads_real_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "stt-fixups.json")
            with open(path, "w") as f:
                json.dump({"slide": {"intent": "claude"}}, f)
            self.assertEqual(tm.load_fixups_file(path), {"slide": {"intent": "claude"}})


class TestRunMergePass(unittest.TestCase):
    def test_full_pass_merges_repeated_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            fixups_path = os.path.join(d, "stt-fixups.json")
            training_log = os.path.join(d, "training.jsonl")
            with open(fixups_path, "w") as f:
                json.dump({"slide": {"intent": "claude", "confidence": "confirmed"}}, f)
            with open(training_log, "w") as f:
                for _ in range(3):
                    f.write(json.dumps({"isbn": "1", "expected": "fiction", "heard": "friction",
                                         "correct_content": False, "correct_stt": False}) + "\n")

            added = tm.run_merge_pass(fixups_path=fixups_path, training_log_path=training_log)
            self.assertEqual(added, ["friction"])
            with open(fixups_path) as f:
                data = json.load(f)
            self.assertIn("friction", data)
            self.assertEqual(data["friction"]["confidence"], "auto")
            self.assertEqual(data["slide"]["confidence"], "confirmed")  # untouched

    def test_no_repeats_no_write(self):
        with tempfile.TemporaryDirectory() as d:
            fixups_path = os.path.join(d, "stt-fixups.json")
            training_log = os.path.join(d, "training.jsonl")
            with open(fixups_path, "w") as f:
                json.dump({}, f)
            with open(training_log, "w") as f:
                f.write(json.dumps({"isbn": "1", "expected": "fiction", "heard": "friction",
                                     "correct_content": False, "correct_stt": False}) + "\n")
            mtime_before = os.path.getmtime(fixups_path)
            added = tm.run_merge_pass(fixups_path=fixups_path, training_log_path=training_log)
            self.assertEqual(added, [])
            self.assertEqual(os.path.getmtime(fixups_path), mtime_before)  # never rewritten

    def test_missing_training_log_is_a_no_op(self):
        with tempfile.TemporaryDirectory() as d:
            fixups_path = os.path.join(d, "stt-fixups.json")
            with open(fixups_path, "w") as f:
                json.dump({}, f)
            added = tm.run_merge_pass(fixups_path=fixups_path, training_log_path="/nonexistent/training.jsonl")
            self.assertEqual(added, [])


if __name__ == "__main__":
    unittest.main()
