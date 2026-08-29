#!/usr/bin/env python3
# Tests for bin/crt-wake-judge.py's pure/file-state logic (2026-07-21,
# self-tuning pass). The actual `claude -p` subprocess call
# (run_judge()) is NOT exercised here -- that would spend real API usage
# in CI; instead this covers rate-limiting and prompt construction, the
# parts that are safe and meaningful to test offline.
import importlib.util
import json
import os
import tempfile
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")
spec = importlib.util.spec_from_file_location("crt_wake_judge", os.path.join(BIN_DIR, "crt-wake-judge.py"))
judge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(judge)


class TestRateLimiting(unittest.TestCase):
    def test_missing_state_file_is_not_rate_limited(self):
        self.assertFalse(judge.rate_limited(now=1000.0, state_path="/nonexistent/state"))

    def test_malformed_state_file_is_not_rate_limited(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "state")
            with open(path, "w") as f:
                f.write("not a number")
            self.assertFalse(judge.rate_limited(now=1000.0, state_path=path))

    def test_recent_run_is_rate_limited(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "state")
            judge.touch_rate_limit(now=1000.0, state_path=path)
            self.assertTrue(judge.rate_limited(now=1000.0 + judge.RATE_LIMIT_SECS - 1, state_path=path))

    def test_old_run_is_not_rate_limited(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "state")
            judge.touch_rate_limit(now=1000.0, state_path=path)
            self.assertFalse(judge.rate_limited(now=1000.0 + judge.RATE_LIMIT_SECS + 1, state_path=path))

    def test_touch_rate_limit_broken_path_does_not_raise(self):
        blocker = os.path.join(tempfile.mkdtemp(), "not_a_dir")
        open(blocker, "w").close()
        judge.touch_rate_limit(now=1000.0, state_path=os.path.join(blocker, "state"))  # must not raise


class TestLogEvent(unittest.TestCase):
    def test_appends_one_json_line(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "events.log")
            judge.log_event("consumed", "Confederacy!", "exact", now=1000.0, log_path=path)
            with open(path) as f:
                lines = f.readlines()
            self.assertEqual(len(lines), 1)
            record = json.loads(lines[0])
            self.assertEqual(record["outcome"], "consumed")
            self.assertEqual(record["trigger_text"], "Confederacy!")

    def test_accumulates_across_calls(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "events.log")
            judge.log_event("consumed", "a", "exact", now=1000.0, log_path=path)
            judge.log_event("timeout-empty", "b", "pool", now=1001.0, log_path=path)
            with open(path) as f:
                lines = f.readlines()
            self.assertEqual(len(lines), 2)

    def test_caps_at_max_lines(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "events.log")
            old_max = judge.EVENTS_LOG_MAX_LINES
            judge.EVENTS_LOG_MAX_LINES = 3
            try:
                for i in range(5):
                    judge.log_event("consumed", f"word-{i}", "exact", now=1000.0 + i, log_path=path)
                with open(path) as f:
                    lines = [json.loads(line) for line in f.readlines()]
            finally:
                judge.EVENTS_LOG_MAX_LINES = old_max
            self.assertEqual(len(lines), 3)
            self.assertEqual([r["trigger_text"] for r in lines], ["word-2", "word-3", "word-4"])

    def test_creates_missing_parent_dir(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "nested", "events.log")
            judge.log_event("consumed", "a", "exact", now=1000.0, log_path=path)
            self.assertTrue(os.path.exists(path))

    def test_unwritable_path_does_not_raise(self):
        blocker = os.path.join(tempfile.mkdtemp(), "not_a_dir")
        open(blocker, "w").close()
        judge.log_event("consumed", "a", "exact", now=1000.0,
                         log_path=os.path.join(blocker, "events.log"))  # must not raise


class TestBuildPrompt(unittest.TestCase):
    def test_includes_trigger_text_and_outcome(self):
        prompt = judge.build_prompt("consumed", "Confederacy!", "exact")
        self.assertIn("Confederacy!", prompt)
        self.assertIn("consumed", prompt)

    def test_includes_match_source_when_provided(self):
        prompt = judge.build_prompt("timeout-empty", "Confederacy!", "pool", match_source="book-title")
        self.assertIn("book-title", prompt)

    def test_includes_matched_word_when_provided(self):
        prompt = judge.build_prompt("timeout-empty", "text", "fuzzy", matched_word="confederacy")
        self.assertIn("confederacy", prompt)

    def test_includes_followup_text_when_provided(self):
        prompt = judge.build_prompt("consumed", "claude", "exact", followup_text="what time is it")
        self.assertIn("what time is it", prompt)

    def test_omits_followup_section_when_not_provided(self):
        prompt = judge.build_prompt("timeout-empty", "text", "exact")
        self.assertNotIn("Follow-up utterance that was dispatched", prompt)

    def test_references_tuning_files_by_path(self):
        prompt = judge.build_prompt("timeout-empty", "text", "exact")
        self.assertIn("wake-pool-dict.txt", prompt)
        self.assertIn("wake-tuning-config.json", prompt)
        self.assertIn("WAKE-TUNING-STATE.md", prompt)

    def test_warns_against_single_event_tuning(self):
        prompt = judge.build_prompt("timeout-empty", "text", "exact")
        self.assertIn("PATTERN", prompt)

    def test_does_not_instruct_unconditional_logging(self):
        prompt = judge.build_prompt("timeout-empty", "text", "exact")
        self.assertNotIn("Always append", prompt)

    def test_instructs_judgment_log_only_on_tuning_change(self):
        prompt = judge.build_prompt("timeout-empty", "text", "exact")
        self.assertIn("ONLY when you actually", prompt)
        self.assertIn("Do NOT append", prompt)

    def test_points_at_events_log_for_pattern_history(self):
        prompt = judge.build_prompt("timeout-empty", "text", "exact")
        self.assertIn(judge.EVENTS_LOG, prompt)


if __name__ == "__main__":
    unittest.main()
