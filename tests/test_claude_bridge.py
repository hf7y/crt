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
        # Guard the actual regression: the hardcoded "-home-zach-crt" project
        # segment must not reappear. (Don't test for the bare substring
        # "zach" -- $HOME legitimately expands to /home/zach on this box, so
        # that gave a false failure whenever the runner's own user is zach.)
        self.assertNotIn("-home-zach-crt", m.PROJECT_DIR)

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


class TestExtractMarked(unittest.TestCase):
    def setUp(self):
        self.m = load_bridge({"PATH": os.environ.get("PATH", "")})

    def test_extracts_marked_line_and_strips_marker(self):
        entry = {"type": "assistant", "message": {"content": [{"type": "text", "text": "» hi zach"}]}}
        self.assertEqual(self.m.extract_marked(entry), "hi zach")

    def test_ignores_unmarked_prose_entirely(self):
        # The whole point of the marker filter: ordinary technical/
        # diagnostic writeups must NOT flood window 1.
        entry = {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "Found the bug: latest_transcript() picks by mtime...\nlots more detail here"}]}}
        self.assertIsNone(self.m.extract_marked(entry))

    def test_extracts_only_marked_lines_from_a_mixed_reply(self):
        entry = {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "Here's the diagnosis, boring detail.\n» *bzzt* i hear you\nmore boring detail"}]}}
        self.assertEqual(self.m.extract_marked(entry), "*bzzt* i hear you")

    def test_ignores_non_assistant_entries(self):
        entry = {"type": "user", "message": {"content": [{"type": "text", "text": "» hello"}]}}
        self.assertIsNone(self.m.extract_marked(entry))

    def test_ignores_tool_use_blocks(self):
        entry = {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash"}]}}
        self.assertIsNone(self.m.extract_marked(entry))

    def test_joins_multiple_marked_lines_across_blocks(self):
        entry = {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "» part one"}, {"type": "text", "text": "» part two"}]}}
        self.assertEqual(self.m.extract_marked(entry), "part one part two")

    def test_custom_marker_override(self):
        entry = {"type": "assistant", "message": {"content": [{"type": "text", "text": "CRT: hi"}]}}
        self.assertEqual(self.m.extract_marked(entry, marker="CRT: "), "hi")


class TestExtractFallback(unittest.TestCase):
    def setUp(self):
        self.m = load_bridge({"PATH": os.environ.get("PATH", "")})

    def test_returns_full_unmarked_text(self):
        entry = {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "Found the bug in latest_transcript()."}]}}
        self.assertEqual(self.m.extract_fallback(entry), "Found the bug in latest_transcript().")

    def test_ignores_non_assistant_entries(self):
        entry = {"type": "user", "message": {"content": [{"type": "text", "text": "hello"}]}}
        self.assertIsNone(self.m.extract_fallback(entry))

    def test_joins_multiple_text_blocks(self):
        entry = {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "part one"}, {"type": "text", "text": "part two"}]}}
        self.assertEqual(self.m.extract_fallback(entry), "part one part two")


class TestChooseText(unittest.TestCase):
    def setUp(self):
        self.m = load_bridge({"PATH": os.environ.get("PATH", "")})
        self.marked_entry = {"type": "assistant", "message": {"content": [{"type": "text", "text": "» hi"}]}}
        self.prose_entry = {"type": "assistant", "message": {"content": [{"type": "text", "text": "long diagnosis"}]}}

    def test_prefers_marked_line_when_present(self):
        text, was_marked = self.m.choose_text(self.marked_entry, last_marked=0, now=1)
        self.assertEqual(text, "hi")
        self.assertTrue(was_marked)

    def test_unmarked_prose_stays_silent_while_marker_still_fresh(self):
        text, was_marked = self.m.choose_text(self.prose_entry, last_marked=1000, now=1010)
        self.assertIsNone(text)
        self.assertFalse(was_marked)

    def test_falls_back_to_full_text_once_marker_has_gone_stale(self):
        # The real fix, per Zach: a dark window 1 is worse than a flooded
        # one -- if the marker convention lapses (long session, model
        # drift), degrade back to forwarding everything rather than
        # forwarding nothing forever.
        now = 1000 + self.m.FALLBACK_STALE_SECS + 1
        text, was_marked = self.m.choose_text(self.prose_entry, last_marked=1000, now=now)
        self.assertEqual(text, "long diagnosis")
        self.assertFalse(was_marked)

    def test_boundary_exactly_at_fallback_stale_secs_stays_silent(self):
        now = 1000 + self.m.FALLBACK_STALE_SECS
        text, was_marked = self.m.choose_text(self.prose_entry, last_marked=1000, now=now)
        self.assertIsNone(text)


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
