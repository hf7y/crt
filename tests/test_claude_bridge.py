#!/usr/bin/env python3
# Offline tests for bin/crt-claude-bridge.py -- had ZERO coverage before
# 2026-07-23, which is exactly how its real bug (hardcoded
# "-home-zach-crt" project dir, silently forwarding nothing on this box's
# actual user/path) went unnoticed since the migration to this hardware.
#
# Run: python3 tests/test_claude_bridge.py
import importlib.util
import json
import os
import sys
import tempfile
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")


def load_bridge(env=None):
    old_env = dict(os.environ)
    try:
        if env is not None:
            os.environ.clear()
            os.environ.update(env)
        spec = importlib.util.spec_from_file_location(
            "crt_claude_bridge_under_test", os.path.join(BIN_DIR, "crt-claude-bridge.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        os.environ.clear()
        os.environ.update(old_env)


class TestDefaultProjectDir(unittest.TestCase):
    def test_derives_from_crt_project_dir_env(self):
        m = load_bridge({"CRT_PROJECT_DIR": "/home/vkv/crt", "PATH": os.environ.get("PATH", "")})
        self.assertEqual(m.PROJECT_DIR, os.path.expanduser("~/.claude/projects/-home-vkv-crt"))

    def test_derives_correctly_for_a_different_user_path(self):
        # The real bug: this used to hardcode "-home-zach-crt" no matter
        # what user/path was actually running it.
        m = load_bridge({"CRT_PROJECT_DIR": "/home/someoneelse/crt", "PATH": os.environ.get("PATH", "")})
        self.assertEqual(m.PROJECT_DIR, os.path.expanduser("~/.claude/projects/-home-someoneelse-crt"))
        self.assertNotIn("zach", m.PROJECT_DIR)

    def test_explicit_override_wins(self):
        m = load_bridge({"CRT_CLAUDE_PROJECT_DIR": "/explicit/path",
                          "CRT_PROJECT_DIR": "/home/vkv/crt",
                          "PATH": os.environ.get("PATH", "")})
        self.assertEqual(m.PROJECT_DIR, "/explicit/path")


class TestLatestTranscript(unittest.TestCase):
    def test_finds_the_most_recently_modified_jsonl(self):
        with tempfile.TemporaryDirectory() as d:
            m = load_bridge({"CRT_CLAUDE_PROJECT_DIR": d, "PATH": os.environ.get("PATH", "")})
            old_path = os.path.join(d, "old.jsonl")
            new_path = os.path.join(d, "new.jsonl")
            open(old_path, "w").close()
            os.utime(old_path, (1000, 1000))
            open(new_path, "w").close()
            os.utime(new_path, (2000, 2000))
            self.assertEqual(m.latest_transcript(), new_path)

    def test_none_when_directory_has_no_transcripts(self):
        with tempfile.TemporaryDirectory() as d:
            m = load_bridge({"CRT_CLAUDE_PROJECT_DIR": d, "PATH": os.environ.get("PATH", "")})
            self.assertIsNone(m.latest_transcript())

    def test_none_when_directory_does_not_exist(self):
        m = load_bridge({"CRT_CLAUDE_PROJECT_DIR": "/nonexistent/project/dir",
                          "PATH": os.environ.get("PATH", "")})
        self.assertIsNone(m.latest_transcript())


class TestExtractText(unittest.TestCase):
    def setUp(self):
        self.m = load_bridge({"PATH": os.environ.get("PATH", "")})

    def test_extracts_assistant_text(self):
        entry = {"type": "assistant", "message": {"content": [{"type": "text", "text": "hi zach"}]}}
        self.assertEqual(self.m.extract_text(entry), "hi zach")

    def test_ignores_non_assistant_entries(self):
        entry = {"type": "user", "message": {"content": [{"type": "text", "text": "hello"}]}}
        self.assertIsNone(self.m.extract_text(entry))

    def test_ignores_tool_use_blocks(self):
        entry = {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash"}]}}
        self.assertIsNone(self.m.extract_text(entry))

    def test_joins_multiple_text_blocks(self):
        entry = {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "part one"}, {"type": "text", "text": "part two"}]}}
        self.assertEqual(self.m.extract_text(entry), "part one part two")


class TestShouldSwitch(unittest.TestCase):
    def setUp(self):
        self.m = load_bridge({"PATH": os.environ.get("PATH", "")})

    def test_adopts_first_file_seen(self):
        self.assertTrue(self.m.should_switch(None, "/a.jsonl", 1000, 1000))

    def test_stays_on_current_when_it_is_still_latest(self):
        self.assertFalse(self.m.should_switch("/a.jsonl", "/a.jsonl", 1000, 1005))

    def test_does_not_steal_focus_to_a_concurrent_session_thats_still_fresh(self):
        # The real bug: a second, unrelated session's file becomes
        # mtime-latest while window 0's own session is still actively
        # being written to -- must NOT switch away from it.
        self.assertFalse(self.m.should_switch("/window0.jsonl", "/other.jsonl", last_growth=999, now=1005))

    def test_fails_over_once_current_has_gone_stale(self):
        self.assertTrue(self.m.should_switch("/window0.jsonl", "/other.jsonl",
                                              last_growth=1000, now=1000 + self.m.STALE_SECS + 1))

    def test_boundary_exactly_at_stale_secs_does_not_switch_yet(self):
        self.assertFalse(self.m.should_switch("/window0.jsonl", "/other.jsonl",
                                               last_growth=1000, now=1000 + self.m.STALE_SECS))


class TestWriteThought(unittest.TestCase):
    def test_appends_a_line_to_the_log(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = os.path.join(d, "thoughts.log")
            m = load_bridge({"CRT_THOUGHT_LOG": log_path, "PATH": os.environ.get("PATH", "")})
            m.write_thought("hello from claude")
            with open(log_path) as f:
                content = f.read()
            self.assertIn("hello from claude", content)


if __name__ == "__main__":
    unittest.main()
