#!/usr/bin/env python3
# Regression test for clean_claude_pane_reply() (2026-07-28) -- the raw
# pane-diff in wait_for_claude_reply() leaked Claude Code's own TUI chrome
# (echoed prompt, status bar, spinner) into the reply that gets spoken/
# printed. Fixture below is the exact pane-diff lines observed live on
# potato the first time a real remote reply was captured end-to-end.
import atexit
import importlib.util
import os
import shutil
import tempfile
import unittest

_state = tempfile.mkdtemp(prefix="crt-test-state-")
atexit.register(shutil.rmtree, _state, ignore_errors=True)
os.environ.setdefault("CRT_CTL_FILE", os.path.join(_state, "ctl"))
os.environ.setdefault("CRT_CLAUDE_ACTIVE_STATE",
                      os.path.join(_state, "claude-window-active.state"))
os.environ.setdefault("CRT_THOUGHT_LOG", os.path.join(_state, "thoughts.log"))
os.environ.setdefault("CRT_STT_GATE_LOG", os.path.join(_state, "thoughts.log"))

BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")


def load_secretary():
    spec = importlib.util.spec_from_file_location(
        "crt_secretary", os.path.join(BIN_DIR, "crt-secretary.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# The exact new_lines a real 2026-07-28 exchange produced (tmux pane diff,
# potato -> mandark bridge -> potato-claude session).
LIVE_FIXTURE = [
    "",
    "❯ trying to reach your brain potato do you have a brain",
    "",
    "● » yeah, i'm right here. brain's on, screen's warm. what do you need?",
    "",
    "✻ Baked for 2s",
    "",
    "",
    "────────────────────────────────────────────────────────────────────────────────",
    "❯ ",
    "────────────────────────────────────────────────────────────────────────────────",
    "  -- INSERT -- ⏵⏵ auto mode on (shift+tab to cycle) · ← for agents",
]


class TestCleanClaudePaneReply(unittest.TestCase):
    def setUp(self):
        self.sec = load_secretary()

    def test_strips_all_chrome_from_live_fixture(self):
        cleaned = self.sec.clean_claude_pane_reply(LIVE_FIXTURE)
        self.assertEqual(
            cleaned,
            "yeah, i'm right here. brain's on, screen's warm. what do you need?")

    def test_no_echoed_prompt_leaks_through(self):
        cleaned = self.sec.clean_claude_pane_reply(LIVE_FIXTURE)
        self.assertNotIn("trying to reach your brain", cleaned)

    def test_no_status_bar_leaks_through(self):
        cleaned = self.sec.clean_claude_pane_reply(LIVE_FIXTURE)
        self.assertNotIn("INSERT", cleaned)
        self.assertNotIn("auto mode on", cleaned)

    def test_no_spinner_leaks_through(self):
        cleaned = self.sec.clean_claude_pane_reply(LIVE_FIXTURE)
        self.assertNotIn("Baked for", cleaned)

    def test_no_border_leaks_through(self):
        cleaned = self.sec.clean_claude_pane_reply(LIVE_FIXTURE)
        self.assertNotIn("─", cleaned)

    def test_plain_lines_with_no_chrome_pass_through_unchanged(self):
        cleaned = self.sec.clean_claude_pane_reply(["just a plain reply line"])
        self.assertEqual(cleaned, "just a plain reply line")

    def test_empty_input_returns_empty(self):
        self.assertEqual(self.sec.clean_claude_pane_reply([]), "")

    def test_multiline_reply_preserves_line_breaks(self):
        cleaned = self.sec.clean_claude_pane_reply(
            ["● first line", "second line", "third line"])
        self.assertEqual(cleaned, "first line\nsecond line\nthird line")

    def test_the_spinner_is_matched_by_shape_not_by_one_verb(self):
        # "Baked for 2s" was the verb in 2026-07-28's capture and the filter
        # took it literally. The live pane on 2026-09-18 said "Worked for 0s",
        # which sailed through to be spoken as if it were Claude's answer.
        for verb in ("Baked", "Worked", "Pondering", "Noodling"):
            self.assertEqual(
                self.sec.clean_claude_pane_reply(["✻ %s for 3s" % verb]), "",
                "%s slipped the spinner filter" % verb)

    def test_a_real_sentence_shaped_like_the_spinner_survives(self):
        # The shape rule needs the seconds unit, so ordinary prose that
        # happens to start "<word> for <number>" is not eaten.
        self.assertEqual(
            self.sec.clean_claude_pane_reply(["● Waited for 3 days, then left"]),
            "Waited for 3 days, then left")


class BrainSignedOutTest(unittest.TestCase):
    """2026-09-18: the brain ran for hours answering every utterance with
    "Login expired", and every layer above it reported healthy. Cleaned like
    any other pane text, that error is SPOKEN as though it were the answer."""

    def setUp(self):
        self.sec = load_secretary()

    def test_the_live_pane_is_recognised(self):
        cleaned = self.sec.clean_claude_pane_reply(
            ["● Login expired · Please run /login", "✻ Worked for 0s"])
        self.assertTrue(self.sec.brain_signed_out(cleaned))

    def test_other_refusals_to_work_count_too(self):
        for phrasing in ("Invalid API key · Please run /login",
                         "Your credit balance is too low",
                         "API Error: authentication_error"):
            self.assertTrue(self.sec.brain_signed_out(phrasing), phrasing)

    def test_an_ordinary_answer_is_not_a_sign_out(self):
        # A false positive tells the room the brain is signed out when it is
        # merely talking about logging in -- its own confidently-wrong report.
        for phrasing in ("", "The kettle is on.",
                         "You log in with your GitHub account.",
                         "I checked the balance and it is fine."):
            self.assertFalse(self.sec.brain_signed_out(phrasing), phrasing)

    def test_the_spoken_line_says_where_and_what_to_do(self):
        # It is spoken aloud, so it must name the fix in words a voice can
        # say -- and nobody in the room can infer the host.
        line = self.sec.BRAIN_SIGNED_OUT_LINE
        self.assertIn("signed out", line.lower())
        self.assertIn("slash login", line.lower())
        self.assertNotIn("/login", line)


if __name__ == "__main__":
    unittest.main()
