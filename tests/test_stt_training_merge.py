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


class TestFailureModeByLoopFlag(unittest.TestCase):
    """Witnesses the claim main()'s comment used to make in prose:
    one-shot (no guard) propagates a raise; --loop (LoopGuard) swallows
    it and keeps going."""

    def test_no_guard_propagates_the_raise(self):
        def boom():
            raise RuntimeError("disk full")
        with self.assertRaises(RuntimeError):
            tm._run_pass_guarded(None, merge_pass=boom)

    def test_loop_guard_swallows_the_raise_and_counts_it(self):
        calls = []

        def boom():
            calls.append(1)
            raise OSError("ENOSPC")

        guard = tm.loop_guard.LoopGuard("stttrain", report=lambda line: None, echo=False)
        tm._run_pass_guarded(guard, merge_pass=boom)  # must not raise
        self.assertEqual(len(calls), 1)
        self.assertEqual(guard.failures, 1)


if __name__ == "__main__":
    unittest.main()
