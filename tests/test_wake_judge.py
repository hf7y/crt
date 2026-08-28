#!/usr/bin/env python3
# Tests for bin/crt-wake-judge.py's pure/file-state logic (2026-07-21,
# self-tuning pass). The actual `claude -p` subprocess call
# (run_judge()) is NOT exercised here -- that would spend real API usage
# in CI; instead this covers rate-limiting and prompt construction, the
# parts that are safe and meaningful to test offline.
import importlib.util
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

    def test_per_event_log_is_off_repo_not_the_tracked_tuning_doc(self):
        prompt = judge.build_prompt("timeout-empty", "text", "exact")
        self.assertIn(judge.JUDGE_LOG, prompt)
        self.assertNotIn(judge.PROJECT_DIR, judge.JUDGE_LOG)

    def test_tracked_tuning_doc_is_written_only_when_a_knob_moved(self):
        prompt = judge.build_prompt("timeout-empty", "text", "exact")
        line = next(l for l in prompt.splitlines() if judge.TUNING_DOC in l
                    and l.lstrip().startswith("-"))
        self.assertIn("ONLY when", line)

    def test_warns_against_single_event_tuning(self):
        prompt = judge.build_prompt("timeout-empty", "text", "exact")
        self.assertIn("PATTERN", prompt)


if __name__ == "__main__":
    unittest.main()
