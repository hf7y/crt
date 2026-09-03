#!/usr/bin/env python3
# The arm window was measured on the wrong clock (2026-07-29).
#
# Measured on potato's own ~/.crt/stt.log, 1597 consecutive-utterance gaps:
# median transcript-to-transcript gap 21s against a 12s window, hard mode at
# 20-22s because CRT_VAD_MAX cuts speech at 20s -- so a run-on wake-then-
# follow-up lands 20s apart in transcript time while the real silence between
# them is under a second. Only 19% of gaps were under the window at all. It
# was never too short: it was compared against the follow-up's own speaking
# duration plus two round-trips. Unit tests over recorded numbers; whether
# 12s of silence is the right feel is still Zach's ear.
import importlib.util
import os
import shutil
import tempfile
import time
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")
SOLO_PATH = os.path.join(BIN_DIR, "crt-stt-solo.py")
ARM_PATH = os.path.join(BIN_DIR, "crt-wake-arm.py")

ARM_SECS = 12.0
MAX_SECS = 60.0

# One real shape from the log above, in seconds on a single wall clock.
WAKE_ON, WAKE_OFF = 100.0, 104.0      # "potato, this is zach" -- 4s of speech
WAKE_LANDED = 107.0                   # ...transcribed 3s later
FOLLOWUP_ON, FOLLOWUP_OFF = 105.0, 123.0   # spoken 1s later, runs to VAD_MAX
FOLLOWUP_LANDED = 126.0               # ...transcribed 3s after that


class FakeClock:
    """Parked at the LANDED instant -- what emit()'s own clock would say --
    so a path still reading it fails loudly rather than coincidentally."""

    def __init__(self, now):
        self.now = now

    def time(self):
        return self.now


def load_arm():
    spec = importlib.util.spec_from_file_location("crt_wake_arm_clock", ARM_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.spawn_judge = lambda *a, **kw: None
    return mod


class TestTwoClocks(unittest.TestCase):
    """The state machine, driven directly."""

    def setUp(self):
        self.wa = load_arm()

    def armed_state(self):
        state = self.wa.ArmState()
        state.arm("potato this is zach", "exact", None, "potato",
                  now=WAKE_OFF, arm_secs=ARM_SECS, max_secs=MAX_SECS)
        return state

    def test_a_long_followup_is_judged_on_when_it_started(self):
        # The headline. Onset 105 is inside the 116 deadline; the transcript
        # lands at 126, and 126 used to be the number compared.
        state = self.armed_state()
        self.assertEqual(state.deadline, WAKE_OFF + ARM_SECS)
        self.assertTrue(self.wa.consume_arm_with_followup(
            state, "switch me to the book game", now=FOLLOWUP_ON,
            ended_at=FOLLOWUP_OFF, arm_secs=ARM_SECS, max_secs=MAX_SECS))

    def test_the_old_transcript_time_comparison_would_have_dropped_it(self):
        # A WITNESS, not a regression guard: the same two utterances compared
        # the way emit() used to compare them are refused, one second of real
        # silence after the wake word. Passes against the parent too.
        state = self.wa.ArmState()
        state.arm("potato this is zach", "exact", None, "potato",
                  now=WAKE_LANDED, arm_secs=ARM_SECS, max_secs=MAX_SECS)
        self.assertFalse(self.wa.consume_arm_with_followup(
            state, "switch me to the book game", now=FOLLOWUP_LANDED,
            arm_secs=ARM_SECS, max_secs=MAX_SECS))

    def test_the_window_it_slides_to_is_anchored_on_the_END_of_the_speech(self):
        # Anchoring the next window on the onset would hand back 117 -- a
        # window already closed before the person stopped talking.
        state = self.armed_state()
        self.wa.consume_arm_with_followup(
            state, "switch me to the book game", now=FOLLOWUP_ON,
            ended_at=FOLLOWUP_OFF, arm_secs=ARM_SECS, max_secs=MAX_SECS)
        self.assertEqual(state.deadline, FOLLOWUP_OFF + ARM_SECS)
        self.assertGreater(state.deadline, FOLLOWUP_OFF)

    def test_a_rewake_is_anchored_on_the_end_of_the_speech_too(self):
        state = self.armed_state()
        self.wa.consume_arm_with_followup(
            state, "potato are you still there", now=FOLLOWUP_ON,
            ended_at=FOLLOWUP_OFF, wake_match=("exact", None, "potato"),
            arm_secs=ARM_SECS, max_secs=MAX_SECS)
        self.assertEqual(state.deadline, FOLLOWUP_OFF + ARM_SECS)
        self.assertEqual(state.session_deadline, FOLLOWUP_OFF + MAX_SECS)

    def test_an_onset_past_the_deadline_is_still_refused(self):
        # The change must not degrade into "any utterance, ever" -- someone
        # who starts talking after the window closed gets the gate, as before.
        state = self.armed_state()
        self.assertFalse(self.wa.consume_arm_with_followup(
            state, "unrelated room chatter", now=WAKE_OFF + ARM_SECS + 0.1,
            ended_at=WAKE_OFF + ARM_SECS + 5.0,
            arm_secs=ARM_SECS, max_secs=MAX_SECS))

    def test_the_session_ceiling_still_holds_against_long_utterances(self):
        # Sliding on end-of-speech spends more of the ceiling than sliding on
        # onset would, so the ceiling still has to stop the ratchet.
        state = self.wa.ArmState()
        state.arm("potato hello", "exact", None, "potato",
                  now=100.0, arm_secs=ARM_SECS, max_secs=30.0)   # ceiling 130
        self.assertTrue(self.wa.consume_arm_with_followup(
            state, "chatter", now=105.0, ended_at=125.0,
            arm_secs=ARM_SECS, max_secs=30.0))
        self.assertEqual(state.deadline, 130.0)                  # clamped
        self.assertFalse(self.wa.consume_arm_with_followup(
            state, "more chatter", now=131.0, ended_at=140.0,
            arm_secs=ARM_SECS, max_secs=30.0))

    def test_omitting_ended_at_is_exactly_the_old_behaviour(self):
        # Every older caller passes only `now`, which has to keep meaning
        # what it meant or this is a silent rewrite of a confirmed decision.
        state = self.armed_state()
        self.assertTrue(self.wa.consume_arm_with_followup(
            state, "and tomorrow", now=110.0,
            arm_secs=ARM_SECS, max_secs=MAX_SECS))
        self.assertEqual(state.deadline, 110.0 + ARM_SECS)


class TestTimeoutDefersToAnOpenUtterance(unittest.TestCase):
    """The capture loop's clock keeps ticking mid-sentence, and CRT_VAD_MAX
    allows 20s of speech against a 12s window -- so without a deferral the
    loop disarms the window just before emit() can consume it."""

    def setUp(self):
        self.wa = load_arm()
        self.state = self.wa.ArmState()
        self.state.arm("potato this is zach", "exact", None, "potato",
                       now=WAKE_OFF, arm_secs=ARM_SECS, max_secs=MAX_SECS)

    def test_deferred_while_an_utterance_that_began_in_time_is_open(self):
        self.assertFalse(self.wa.check_arm_timeout(
            self.state, now=WAKE_OFF + ARM_SECS + 2.0, utt_start=FOLLOWUP_ON))
        self.assertTrue(self.state.armed)

    def test_fires_once_that_utterance_resolves(self):
        self.wa.check_arm_timeout(self.state, now=WAKE_OFF + ARM_SECS + 2.0,
                                  utt_start=FOLLOWUP_ON)
        self.assertTrue(self.wa.check_arm_timeout(
            self.state, now=WAKE_OFF + ARM_SECS + 30.0, utt_start=None))
        self.assertFalse(self.state.armed)

    def test_an_utterance_that_began_after_the_deadline_earns_no_deferral(self):
        # It could never have been consumed: that is a longer window by accident.
        self.assertTrue(self.wa.check_arm_timeout(
            self.state, now=WAKE_OFF + ARM_SECS + 2.0,
            utt_start=WAKE_OFF + ARM_SECS + 1.0))
        self.assertFalse(self.state.armed)

    def test_a_quiet_room_times_out_exactly_as_before(self):
        self.assertFalse(self.wa.check_arm_timeout(
            self.state, now=WAKE_OFF + 1.0, utt_start=None))
        self.assertTrue(self.wa.check_arm_timeout(
            self.state, now=WAKE_OFF + ARM_SECS + 0.1))


class TestThroughTheLiveEmitPath(unittest.TestCase):
    """The real emit(), gate and wiring; only the sinks and the arm clock are
    faked, parked where a regression reproduces the live symptom."""

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
        spec = importlib.util.spec_from_file_location("crt_stt_solo_clock", SOLO_PATH)
        self.stt = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.stt)

        self.tmpdir = tempfile.mkdtemp()
        self.stt.STT_LOG = os.path.join(self.tmpdir, "stt.log")
        self.stt.GATE_LOG = os.path.join(self.tmpdir, "thoughts.log")
        # Never the live console's ~/.crt: driving the real emit() would
        # otherwise publish an open arm window on potato and suppress trivia
        # grading for twelve seconds because someone ran the tests.
        self.arm_state = os.path.join(self.tmpdir, "wake-arm.state")
        self.stt.wake_arm.ARM_STATE_FILE = self.arm_state
        self.stt.log_user_thought = lambda text, **kw: None
        self.stt.play_earcon = lambda *a, **kw: None
        self.heard = []
        self.stt.send_to_secretary = self.heard.append
        self.stt.send_to_claude = lambda text, key: self.heard.append(text)
        # The scenario's timeline is pinned to the REAL clock, offset so that
        # "the wake transcript just landed" is now. emit() measures the
        # published window's reader-lag against time.time() -- that is the
        # whole point of it, it is the one number in this file that is not
        # synthetic -- so the fixture has to sit where a real one would.
        self.base = time.time() - WAKE_LANDED
        self.clock = FakeClock(self.base + WAKE_LANDED)
        self.stt.wake_arm.time = self.clock

    def tearDown(self):
        for k, v in self.env_backup.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def say(self, text, on, off, landed):
        """One utterance as the capture loop actually sees it: spoken from
        `on` to `off`, handed to emit() at `landed`. All three are offsets
        into the scenario, resolved against the real clock by self.base."""
        self.clock.now = self.base + landed
        self.stt.emit(text, 1.0,
                      utt_start=self.base + on, utt_end=self.base + off)

    def test_the_live_shape_from_potatos_own_log_now_gets_through(self):
        self.say("potato this is zach", WAKE_ON, WAKE_OFF, WAKE_LANDED)
        self.say("switch me to the book game",
                 FOLLOWUP_ON, FOLLOWUP_OFF, FOLLOWUP_LANDED)
        self.assertEqual(self.heard, ["potato this is zach",
                                      "switch me to the book game"])

    def test_the_engine_enforces_the_window_in_audio_time(self):
        self.say("potato this is zach", WAKE_ON, WAKE_OFF, WAKE_LANDED)
        self.assertAlmostEqual(self.stt.ARM_STATE.deadline,
                               self.base + WAKE_OFF + ARM_SECS, places=6)

    def test_the_published_window_is_translated_into_the_readers_clock(self):
        # crt-book-answer-listen.py tails stt.log and asks arm_window_open()
        # when a line APPEARS -- one whisper round-trip after it was spoken.
        # Handing it the raw audio-time deadline would quietly shorten its
        # window by that round-trip and start grading follow-ups as trivia
        # answers. What it must keep seeing is ARM_SECS from right now, which
        # is exactly what it saw before the clock fix.
        self.say("potato this is zach", WAKE_ON, WAKE_OFF, WAKE_LANDED)
        published = self.stt.wake_arm.read_arm_deadline(self.arm_state)
        self.assertAlmostEqual(published - time.time(), ARM_SECS, delta=1.0)
        # ...and it is genuinely later than the engine's own deadline, i.e.
        # the translation happened rather than being a rounding coincidence.
        self.assertGreater(published, self.stt.ARM_STATE.deadline + 1.0)

    def test_a_wake_word_still_arms_when_no_timestamps_are_passed(self):
        # crt-stt-solo.py is not the only thing that has ever called emit(),
        # and a transcription that arrives without a span must not crash,
        # refuse to arm, or try to measure a lag it was never given.
        self.clock.now = self.base + 200.0
        self.stt.emit("potato this is zach")
        self.assertTrue(self.stt.ARM_STATE.armed)
        self.assertEqual(self.stt.ARM_STATE.deadline, self.base + 200.0 + ARM_SECS)
        # places=2: the file carries "%.3f", so a round-trip is not exact.
        self.assertAlmostEqual(
            self.stt.wake_arm.read_arm_deadline(self.arm_state),
            self.base + 200.0 + ARM_SECS, places=2)

    def test_chatter_long_after_the_window_is_still_gated(self):
        self.say("potato this is zach", WAKE_ON, WAKE_OFF, WAKE_LANDED)
        self.say("unrelated room chatter", 300.0, 310.0, 313.0)
        self.assertNotIn("unrelated room chatter", self.heard)


if __name__ == "__main__":
    unittest.main()
