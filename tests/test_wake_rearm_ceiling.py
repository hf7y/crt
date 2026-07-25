#!/usr/bin/env python3
# A deliberate re-wake mid-conversation has to start a FRESH session
# (2026-07-25, twelfth nightly cycle).
#
# bin/crt-wake-arm.py's ArmState.arm() documents itself as "Always starts a
# FRESH session, including when one is already open -- saying the wake word
# again is deliberate, so it resets the ARM_MAX_SECS ceiling rather than
# being swallowed by the conversation already in progress", and
# tests/test_wake_arm.py asserted exactly that. But it asserted it by
# CALLING arm() directly, and in the live wiring an utterance arriving while
# armed can never reach that call: crt-stt-solo.py's emit() runs the
# consume-follow-up check first and returns as soon as it consumes, so
# arm() was only ever reachable from a disarmed state -- the one state where
# resetting the ceiling means nothing.
#
# Live consequence, with CRT_WAKE_ARM_ENABLED=1 as potato's ~/.bash_profile
# actually sets it: someone who re-says the wake word out of habit (which is
# what this room's own 2026-07-23 log shows people doing) still hits the
# 60s ceiling measured from their FIRST wake, and the utterance after it is
# gate-dropped in silence.
#
# The two emit()-driven tests below fail against the parent with that exact
# symptom -- an utterance the person spoke seconds after saying the wake
# word, never delivered -- not with an AttributeError about a missing kwarg.
#
# CONFIRMED BY ZACH 2026-07-25 (thirteenth cycle, replying inline on that
# report): "saying the wake word again is deliberate, so it resets the
# ARM_MAX_SECS ceiling rather than being swallowed by the conversation
# already in progress." These tests are therefore pinning a decision the
# human has made, not an inference from a docstring.
import importlib.util
import os
import shutil
import tempfile
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")
SOLO_PATH = os.path.join(BIN_DIR, "crt-stt-solo.py")
ARM_PATH = os.path.join(BIN_DIR, "crt-wake-arm.py")

ARM_SECS = 12.0
MAX_SECS = 30.0


class FakeClock:
    """Stands in for the `time` module inside crt-wake-arm.py only -- emit()'s
    own time.time() (HUD flash timing) is left real and unaffected."""

    def __init__(self, now):
        self.now = now

    def time(self):
        return self.now


def load_arm():
    spec = importlib.util.spec_from_file_location("crt_wake_arm_rearm", ARM_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestConsumeRearmsOnAWakeMatch(unittest.TestCase):
    """The state-machine half, driven directly."""

    def setUp(self):
        self.wa = load_arm()
        self.wa.spawn_judge = lambda *a, **kw: None

    def test_a_wake_match_in_the_followup_resets_the_session_ceiling(self):
        state = self.wa.ArmState()
        state.arm("potato hello", "exact", None, "potato",
                  now=100.0, arm_secs=ARM_SECS, max_secs=MAX_SECS)   # ceiling 130
        self.assertTrue(self.wa.consume_arm_with_followup(
            state, "potato are you there", now=110.0,
            wake_match=("exact", None, "potato"),
            arm_secs=ARM_SECS, max_secs=MAX_SECS))
        self.assertEqual(state.session_deadline, 140.0)   # parent: still 130
        self.assertEqual(state.deadline, 122.0)

    def test_a_rewake_is_a_fresh_session_not_a_continuation(self):
        # continuation=True means "a conversation that ran its course" and
        # suppresses the judge outcome when the window closes. A fresh wake
        # that nobody follows up on IS an unanswered wake and must still be
        # reported.
        state = self.wa.ArmState()
        state.arm("potato hello", "exact", None, "potato",
                  now=100.0, arm_secs=ARM_SECS, max_secs=MAX_SECS)
        self.wa.consume_arm_with_followup(state, "tell me more", now=105.0)
        self.assertTrue(state.continuation)
        self.wa.consume_arm_with_followup(state, "potato hello again", now=110.0,
                                          wake_match=("exact", None, "potato"))
        self.assertFalse(state.continuation)
        self.assertEqual(state.trigger_text, "potato hello again")
        self.assertEqual(state.matched_word, "potato")

    def test_a_plain_followup_still_slides_inside_the_ceiling(self):
        # The ceiling is what stops ambient chatter re-arming the mic
        # forever; only a wake word may reset it.
        state = self.wa.ArmState()
        state.arm("potato hello", "exact", None, "potato",
                  now=100.0, arm_secs=ARM_SECS, max_secs=MAX_SECS)
        self.wa.consume_arm_with_followup(state, "chatter", now=110.0,
                                          wake_match=(None, None, None))
        self.assertEqual(state.deadline, 122.0)
        self.wa.consume_arm_with_followup(state, "more chatter", now=121.0,
                                          wake_match=(None, None, None))
        self.assertEqual(state.session_deadline, 130.0)
        self.assertEqual(state.deadline, 130.0)          # clamped, not 133

    def test_wake_match_is_ignored_when_nothing_is_armed(self):
        # A wake word arriving cold is the gate's business, not this one's --
        # emit() arms it further down, with the same classification.
        state = self.wa.ArmState()
        self.assertFalse(self.wa.consume_arm_with_followup(
            state, "potato hello", now=100.0, wake_match=("exact", None, "potato")))
        self.assertFalse(state.armed)


class TestRewakeThroughEmit(unittest.TestCase):
    """The live path: crt-stt-solo.py's real emit(), real gate, real
    arm-window wiring. Only the sinks and the arm module's clock are faked."""

    def setUp(self):
        self.env_backup = {k: os.environ.get(k) for k in
                           ("CRT_WAKE_ARM_ENABLED", "CRT_WAKE_ARM_SECS",
                            "CRT_WAKE_ARM_MAX_SECS", "CRT_STT_GATE",
                            "CRT_WAKE_WORD", "CRT_STT_SINK",
                            "CRT_EARCON_ON_ADDRESSED")}
        os.environ.update({
            "CRT_WAKE_ARM_ENABLED": "1",
            "CRT_WAKE_ARM_SECS": str(ARM_SECS),
            "CRT_WAKE_ARM_MAX_SECS": str(MAX_SECS),
            "CRT_STT_GATE": "1",
            "CRT_WAKE_WORD": "potato",
            "CRT_STT_SINK": "secretary",
            "CRT_EARCON_ON_ADDRESSED": "0",
        })
        spec = importlib.util.spec_from_file_location("crt_stt_solo_rearm", SOLO_PATH)
        self.stt = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.stt)

        self.tmpdir = tempfile.mkdtemp()
        self.stt.STT_LOG = os.path.join(self.tmpdir, "stt.log")
        self.stt.GATE_LOG = os.path.join(self.tmpdir, "thoughts.log")
        # emit() publishes the arm window for crt-book-answer-listen.py to
        # read (2026-07-25, twentieth cycle). This class drives the REAL
        # emit(), so without this redirect the suite writes an open window
        # into the live console's own ~/.crt -- on potato that would suppress
        # trivia grading for twelve seconds because someone ran the tests.
        self.arm_state = os.path.join(self.tmpdir, "wake-arm.state")
        self.stt.wake_arm.ARM_STATE_FILE = self.arm_state
        self.stt.log_user_thought = lambda text, **kw: None
        self.stt.play_earcon = lambda *a, **kw: None
        self.heard = []
        self.stt.send_to_secretary = self.heard.append
        self.stt.send_to_claude = lambda text, key: self.heard.append(text)

        self.clock = FakeClock(100.0)
        self.stt.wake_arm.time = self.clock

    def tearDown(self):
        for k, v in self.env_backup.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def say(self, text, at):
        self.clock.now = at
        self.stt.emit(text)

    def test_a_rewake_buys_a_fresh_ceiling_for_what_follows_it(self):
        self.say("potato what is the weather", 100.0)        # ceiling 130
        self.say("and tomorrow", 110.0)                      # slides to 122
        self.say("potato are you still there", 120.0)        # re-wake
        self.say("what about tuesday", 128.0)
        # Parent: the ceiling is still 130 from the FIRST wake, so this one
        # arrives disarmed, carries no wake word, and is gate-dropped --
        # eight seconds after the person said the wake word.
        self.say("and wednesday", 135.0)
        self.assertIn("and wednesday", self.heard)
        self.assertEqual(self.heard, ["potato what is the weather",
                                      "and tomorrow",
                                      "potato are you still there",
                                      "what about tuesday",
                                      "and wednesday"])

    def test_chatter_alone_still_cannot_push_past_the_ceiling(self):
        # The other half of the same change: without a wake word the ceiling
        # must behave exactly as it did. This passes against the parent too --
        # it is here so a future loosening of the re-wake path cannot quietly
        # take the ceiling with it.
        self.say("potato what is the weather", 100.0)        # ceiling 130
        for t in (110.0, 120.0, 129.0):
            self.say("more ambient chatter", t)
        self.say("still more chatter", 131.0)
        self.assertNotIn("still more chatter", self.heard)

    def test_a_rewake_still_reaches_the_sink_like_any_other_utterance(self):
        self.say("potato what is the weather", 100.0)
        self.say("potato one more thing", 105.0)
        self.assertEqual(self.heard, ["potato what is the weather",
                                      "potato one more thing"])

    def test_emit_publishes_the_window_it_is_actually_in(self):
        """The other reader of this window is a different process
        (crt-book-answer-listen.py, which must not grade a follow-up as a
        trivia answer -- tests/test_book_answer_arm_window.py). It learns
        about the window through this file, so the deadline on disk has to
        track what emit() actually did, not just what ArmState holds in
        memory. Uses the same FakeClock the rest of this class runs on."""
        read = lambda: self.stt.wake_arm.read_arm_deadline(self.arm_state)
        self.say("potato what is the weather", 100.0)
        self.assertEqual(read(), 112.0)                  # armed: 100 + ARM_SECS
        self.say("and tomorrow", 110.0)                  # consumed -> slides
        self.assertEqual(read(), 122.0)
        self.say("potato are you still there", 120.0)    # re-wake -> fresh
        self.assertEqual(read(), 132.0)

    def test_a_window_that_times_out_is_published_shut(self):
        """A timeout happens in the capture loop, not in emit() -- and a
        deadline left on disk after the window closed would keep the book
        window silent for as long as the clock said it was open."""
        self.say("potato what is the weather", 100.0)
        self.clock.now = 113.0
        if self.stt.wake_arm.check_arm_timeout(self.stt.ARM_STATE, 113.0):
            self.stt.publish_arm_window()
        self.assertEqual(self.stt.wake_arm.read_arm_deadline(self.arm_state), 0.0)


if __name__ == "__main__":
    unittest.main()
