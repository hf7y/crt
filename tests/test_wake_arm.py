#!/usr/bin/env python3
# Tests for bin/crt-wake-arm.py -- the arm-window state machine wiring
# crt-wake-judge.py to a real trigger (2026-07-23, the missing piece
# behind WAKE-TUNING-STATE.md's judgment log / the sticky-wake-window
# gap). spawn_judge()'s actual subprocess call is stubbed via monkeypatch
# in every test that exercises consume/timeout -- this suite must never
# spend real API usage (crt-wake-judge.py spawns a real `claude -p` call
# when CRT_WAKE_JUDGE_ENABLED=1).
import importlib.util
import os
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")

_spec = importlib.util.spec_from_file_location("crt_wake_arm", os.path.join(BIN_DIR, "crt-wake-arm.py"))
wa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wa)


class TestHasLeftoverContent(unittest.TestCase):
    def test_bare_wake_word_has_no_leftover(self):
        self.assertFalse(wa.has_leftover_content("Potato", "potato"))

    def test_wake_word_with_punctuation_only_has_no_leftover(self):
        self.assertFalse(wa.has_leftover_content("Potato!", "potato"))

    def test_real_request_has_leftover(self):
        self.assertTrue(wa.has_leftover_content("Potato, what's AGM?", "potato"))

    def test_no_matched_word_falls_back_to_word_count(self):
        self.assertTrue(wa.has_leftover_content("hello there console", None))
        self.assertFalse(wa.has_leftover_content("hello", None))


class TestArmState(unittest.TestCase):
    def test_starts_disarmed(self):
        state = wa.ArmState()
        self.assertFalse(state.armed)

    def test_arm_sets_fields_and_deadline(self):
        state = wa.ArmState()
        state.arm("Potato, run the tests", "exact", None, "potato", now=100.0, arm_secs=12.0)
        self.assertTrue(state.armed)
        self.assertEqual(state.deadline, 112.0)
        self.assertEqual(state.trigger_text, "Potato, run the tests")
        self.assertEqual(state.matched_word, "potato")

    def test_rearm_replaces_previous_trigger(self):
        state = wa.ArmState()
        state.arm("first", "exact", now=100.0, arm_secs=12.0)
        state.arm("second", "pool", now=105.0, arm_secs=12.0)
        self.assertEqual(state.trigger_text, "second")
        self.assertEqual(state.deadline, 117.0)


class TestConsumeArmWithFollowup(unittest.TestCase):
    def setUp(self):
        self.judge_calls = []
        self._orig_spawn = wa.spawn_judge
        wa.spawn_judge = lambda *a, **kw: self.judge_calls.append((a, kw))

    def tearDown(self):
        wa.spawn_judge = self._orig_spawn

    def test_consumes_when_armed_and_within_window(self):
        state = wa.ArmState()
        state.arm("Potato", "exact", matched_word="potato", now=100.0, arm_secs=12.0)
        consumed = wa.consume_arm_with_followup(state, "run the tests", now=105.0)
        self.assertTrue(consumed)
        self.assertEqual(len(self.judge_calls), 1)
        args = self.judge_calls[0][0]
        self.assertEqual(args[0], "consumed")

    def test_window_slides_forward_instead_of_closing_after_one_followup(self):
        # The live 2026-07-23 bug was FOUR follow-ups in one breath. A window
        # that closes on the first still drops the other three -- the same
        # complaint, one utterance later.
        state = wa.ArmState()
        state.arm("Potato, this is Zach", "exact", matched_word="potato",
                  now=100.0, arm_secs=12.0, max_secs=60.0)
        for i, (text, t) in enumerate([("we made some updates", 105.0),
                                       ("routed off-site", 112.0),
                                       ("to the model", 120.0),
                                       ("does that make sense", 128.0)]):
            self.assertTrue(wa.consume_arm_with_followup(state, text, now=t),
                            "follow-up %d was dropped" % (i + 1))
            self.assertTrue(state.armed)
        self.assertEqual(len(self.judge_calls), 4)

    def test_sliding_is_capped_by_the_session_ceiling(self):
        # Sliding with no ceiling would let ambient room chatter keep a mic
        # armed indefinitely -- the failure mode this room's noise floor
        # makes real.
        state = wa.ArmState()
        state.arm("Potato", "exact", matched_word="potato",
                  now=100.0, arm_secs=12.0, max_secs=30.0)   # ceiling t=130
        self.assertTrue(wa.consume_arm_with_followup(state, "one", now=110.0))
        self.assertEqual(state.deadline, 122.0)              # slid normally
        self.assertTrue(wa.consume_arm_with_followup(state, "two", now=121.0))
        self.assertEqual(state.deadline, 130.0)              # clamped, not 133
        self.assertTrue(wa.consume_arm_with_followup(state, "three", now=129.0))
        self.assertEqual(state.deadline, 130.0)              # still clamped
        # At the ceiling the window closes and stays closed: more chatter
        # can't reopen it, only the wake word can.
        self.assertTrue(wa.check_arm_timeout(state, now=130.0))
        self.assertFalse(state.armed)
        self.assertFalse(wa.consume_arm_with_followup(state, "four", now=131.0))

    def test_wake_word_again_starts_a_fresh_session(self):
        # A deliberate re-wake resets the ceiling; only follow-ups are capped.
        # NOTE (2026-07-25): this reaches arm() by calling it, which the LIVE
        # path could not do from an armed state -- see
        # tests/test_wake_rearm_ceiling.py, which drives the same claim
        # through crt-stt-solo.py's real emit().
        state = wa.ArmState()
        state.arm("Potato", "exact", matched_word="potato",
                  now=100.0, arm_secs=12.0, max_secs=30.0)
        wa.consume_arm_with_followup(state, "one", now=105.0)
        state.arm("Potato", "exact", matched_word="potato",
                  now=125.0, arm_secs=12.0, max_secs=30.0)
        self.assertEqual(state.session_deadline, 155.0)
        self.assertFalse(state.continuation)

    def test_continuation_timeout_is_not_reported_as_an_unanswered_wake(self):
        # The follow-up already proved the wake was wanted. Filing a timeout
        # when the conversation later ends would teach the judge the
        # opposite, poisoning WAKE-TUNING-STATE.md's ground truth.
        state = wa.ArmState()
        state.arm("Potato, what's AGM?", "exact", matched_word="potato",
                  now=100.0, arm_secs=12.0)
        wa.consume_arm_with_followup(state, "the battery kind", now=105.0)
        self.judge_calls.clear()
        self.assertTrue(wa.check_arm_timeout(state, now=200.0))
        self.assertFalse(state.armed)
        self.assertEqual(self.judge_calls, [])

    def test_does_not_consume_when_not_armed(self):
        state = wa.ArmState()
        consumed = wa.consume_arm_with_followup(state, "hello", now=100.0)
        self.assertFalse(consumed)
        self.assertEqual(len(self.judge_calls), 0)

    def test_does_not_consume_after_deadline(self):
        state = wa.ArmState()
        state.arm("Potato", "exact", matched_word="potato", now=100.0, arm_secs=12.0)
        consumed = wa.consume_arm_with_followup(state, "too late", now=113.0)
        self.assertFalse(consumed)
        self.assertTrue(state.armed)  # untouched -- check_arm_timeout handles expiry


class TestCheckArmTimeout(unittest.TestCase):
    def setUp(self):
        self.judge_calls = []
        self._orig_spawn = wa.spawn_judge
        wa.spawn_judge = lambda *a, **kw: self.judge_calls.append((a, kw))

    def tearDown(self):
        wa.spawn_judge = self._orig_spawn

    def test_no_timeout_while_armed_and_within_window(self):
        state = wa.ArmState()
        state.arm("Potato", "exact", matched_word="potato", now=100.0, arm_secs=12.0)
        fired = wa.check_arm_timeout(state, now=105.0)
        self.assertFalse(fired)
        self.assertTrue(state.armed)
        self.assertEqual(len(self.judge_calls), 0)

    def test_no_timeout_when_not_armed(self):
        state = wa.ArmState()
        fired = wa.check_arm_timeout(state, now=100.0)
        self.assertFalse(fired)
        self.assertEqual(len(self.judge_calls), 0)

    def test_timeout_empty_for_bare_wake_word(self):
        state = wa.ArmState()
        state.arm("Potato", "exact", matched_word="potato", now=100.0, arm_secs=12.0)
        fired = wa.check_arm_timeout(state, now=113.0)
        self.assertTrue(fired)
        self.assertFalse(state.armed)
        self.assertEqual(self.judge_calls[0][0][0], "timeout-empty")

    def test_timeout_with_leftover_for_real_request(self):
        state = wa.ArmState()
        state.arm("Potato, what's AGM?", "exact", matched_word="potato", now=100.0, arm_secs=12.0)
        fired = wa.check_arm_timeout(state, now=113.0)
        self.assertTrue(fired)
        self.assertEqual(self.judge_calls[0][0][0], "timeout-with-leftover")

    def test_only_fires_once(self):
        state = wa.ArmState()
        state.arm("Potato", "exact", matched_word="potato", now=100.0, arm_secs=12.0)
        wa.check_arm_timeout(state, now=113.0)
        fired_again = wa.check_arm_timeout(state, now=120.0)
        self.assertFalse(fired_again)
        self.assertEqual(len(self.judge_calls), 1)


class TestSpawnJudgeDisabledByDefault(unittest.TestCase):
    def test_noop_unless_judge_enabled(self):
        # JUDGE_ENABLED reads the env once at import time -- verify the
        # module-level default (no env var set in this test process) is
        # off, matching the "not hardware-verified" opt-in posture.
        self.assertFalse(wa.JUDGE_ENABLED)


if __name__ == "__main__":
    unittest.main()
