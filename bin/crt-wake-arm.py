#!/usr/bin/env python3
# The arm-window state machine wiring crt-wake-judge.py's autonomous
# tuning judge to a real live trigger -- the ONE missing piece identified
# 2026-07-23: consume_arm_with_followup()/check_arm_timeout() are
# referenced by name in crt-wake-judge.py's own prompt-building code and
# in WAKE-TUNING-STATE.md's judgment-log vocabulary, but grep confirmed
# zero implementations existed anywhere in bin/*.py before this file --
# only comments/docs referenced them (that log almost certainly comes
# from this mechanism running once on the old crt-vm, lost in the
# migration to potato).
#
# This is ALSO the real implementation of the separately-identified
# "sticky conversation window" gap, not a second feature: once a wake
# genuinely fires, a follow-up utterance shouldn't need to repeat the
# wake word to get through. Confirmed live 2026-07-23 as a real bug --
# "Potato, this is Zach" woke the console, but four follow-up utterances
# in the same breath right after all got silently gate-dropped.
#
# 2026-07-25: a consumed follow-up SLIDES the window forward rather than
# closing it. As first written, the window was single-shot -- which would
# have let follow-up #1 of that live report through and still dropped
# #2/#3/#4, i.e. the same complaint one utterance later. Sliding is
# bounded by CRT_WAKE_ARM_MAX_SECS (default 60s) so that in this
# specifically noisy room it can't ratchet itself into an always-on mic;
# saying the wake word again starts a fresh session with a fresh ceiling.
#
# Pure functions except spawn_judge()'s subprocess call -- covered by
# tests/test_wake_arm.py.
#
# STATUS: built 2026-07-23 (unattended nightly-batch pass, no live mic
# access this run). NOT hardware-verified -- wired into crt-stt-solo.py
# fully opt-in (CRT_WAKE_ARM_ENABLED, default OFF) so potato's current
# live/stable gate behavior is completely unchanged unless a human
# deliberately turns this on and confirms the arm-window duration feels
# right (doesn't cause unwanted "sticky" follow-ups, isn't too short to
# be useful) in a live session.
import os
import re
import subprocess
import time

BIN_DIR = os.path.dirname(os.path.abspath(__file__))
JUDGE_BIN = os.path.join(BIN_DIR, "crt-wake-judge.py")

ARM_SECS = float(os.environ.get("CRT_WAKE_ARM_SECS", "12"))
# Hard ceiling on one sticky conversation (2026-07-25). A consumed follow-up
# SLIDES the window forward -- the live bug this exists for was four
# follow-ups in one breath, of which a single-shot window would still have
# dropped three -- but sliding with no ceiling is dangerous in this
# specific room: CLAUDE.md's premise is ambient chatter and a noisy mic, and
# an unbounded window would let room noise keep re-arming itself until the
# console is effectively always listening. The wake word can always start a
# fresh session (a deliberate re-wake resets this ceiling); what it can't do
# is drift into always-on.
ARM_MAX_SECS = float(os.environ.get("CRT_WAKE_ARM_MAX_SECS", "60"))
JUDGE_ENABLED = os.environ.get("CRT_WAKE_JUDGE_ENABLED", "0") == "1"


def has_leftover_content(trigger_text, matched_word):
    """True if trigger_text carries real content beyond the bare matched
    word itself -- e.g. "Potato, what's AGM?" has leftover ("what's",
    "AGM"), bare "Potato" does not. Determines timeout-with-leftover vs
    timeout-empty if the arm window closes with nothing following (see
    WAKE-TUNING-STATE.md's outcome-meaning definitions)."""
    words = re.findall(r"[a-z0-9']+", trigger_text.lower())
    if not matched_word:
        return len(words) > 1
    matched_words = matched_word.lower().split()
    non_wake = [w for w in words if w not in matched_words]
    return len(non_wake) > 0


class ArmState:
    """One arm slot at a time -- a second wake event while already armed
    just re-arms with the new trigger (doesn't stack/queue). Plain
    mutable object, not a class hierarchy; crt-stt-solo.py holds one
    instance for the life of the process."""

    def __init__(self):
        self.armed = False
        self.deadline = 0.0
        self.trigger_text = ""
        self.match_kind = None
        self.match_source = None
        self.matched_word = None
        # Ceiling for the whole conversation, set by the wake word itself and
        # NOT pushed back by follow-ups (see ARM_MAX_SECS).
        self.session_deadline = 0.0
        # True once the window has been slid by a consumed follow-up. Such a
        # window closing is a conversation ending normally, not a wake that
        # went unanswered -- reporting it to the judge as a timeout would
        # teach it the wake word was unwanted, when a follow-up already
        # proved the opposite.
        self.continuation = False

    def arm(self, text, match_kind, match_source=None, matched_word=None,
            now=None, arm_secs=None, max_secs=None):
        """A wake word fired. Always starts a FRESH session, including when
        one is already open -- saying the wake word again is deliberate, so
        it resets the ARM_MAX_SECS ceiling rather than being swallowed by
        the conversation already in progress."""
        now = now if now is not None else time.time()
        arm_secs = arm_secs if arm_secs is not None else ARM_SECS
        max_secs = max_secs if max_secs is not None else ARM_MAX_SECS
        self.armed = True
        self.deadline = now + arm_secs
        self.session_deadline = now + max(arm_secs, max_secs)
        self.continuation = False
        self.trigger_text = text
        self.match_kind = match_kind
        self.match_source = match_source
        self.matched_word = matched_word

    def slide(self, followup_text, now=None, arm_secs=None):
        """Extend an open window after a consumed follow-up, capped at the
        session ceiling. Returns False when the ceiling is reached, meaning
        the caller should close the window instead."""
        now = now if now is not None else time.time()
        arm_secs = arm_secs if arm_secs is not None else ARM_SECS
        new_deadline = min(now + arm_secs, self.session_deadline)
        if new_deadline <= now:
            return False
        self.deadline = new_deadline
        self.continuation = True
        self.trigger_text = followup_text
        return True

    def disarm(self):
        self.armed = False
        self.continuation = False


def spawn_judge(outcome, trigger_text, match_kind, match_source=None,
                matched_word=None, followup_text=None):
    """Fire-and-forget (Popen), same posture as crt-stt-solo.py's own
    send_to_secretary() -- must never block the sole mic reader's capture
    loop. A complete no-op unless CRT_WAKE_JUDGE_ENABLED=1 -- this spawns
    a real `claude -p` call with file-write access (crt-wake-judge.py's
    own design), which is a bigger step than just arming/timing out, so
    it gets its own explicit opt-in on top of CRT_WAKE_ARM_ENABLED."""
    if not JUDGE_ENABLED:
        return
    cmd = [JUDGE_BIN, "--outcome", outcome, "--trigger-text", trigger_text,
           "--match-kind", match_kind or "exact"]
    if match_source:
        cmd += ["--match-source", match_source]
    if matched_word:
        cmd += ["--matched-word", matched_word]
    if followup_text:
        cmd += ["--followup-text", followup_text]
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def consume_arm_with_followup(state, followup_text, now=None):
    """A real follow-up utterance arrived while armed -- strong evidence
    the wake was wanted (WAKE-TUNING-STATE.md's ground-truth rule).
    Disarms and spawns the judge with outcome=consumed. Returns True if
    there was actually anything armed to consume -- callers use this to
    decide whether to treat followup_text as implicitly addressed,
    bypassing the normal wake-word gate for just this one utterance."""
    now = now if now is not None else time.time()
    if not state.armed or now >= state.deadline:
        return False
    spawn_judge("consumed", state.trigger_text, state.match_kind,
                state.match_source, state.matched_word, followup_text)
    # Slide, don't close: the live 2026-07-23 bug was FOUR follow-ups in one
    # breath, and a window that shuts after the first still drops three of
    # them -- the same complaint, one utterance later. Capped by
    # ARM_MAX_SECS so a sliding window can't become an always-on mic.
    if not state.slide(followup_text, now):
        state.disarm()
    return True


def check_arm_timeout(state, now=None):
    """Call periodically (crt-stt-solo.py's own fast capture-loop tick is
    fine, cheap -- no VAD/whisper work happens here). If armed and the
    deadline has passed with no follow-up ever consumed, disarms and
    spawns the judge with timeout-with-leftover or timeout-empty per
    has_leftover_content() on the ORIGINAL trigger text. Returns True if
    a timeout was actually processed (state was armed and had expired) --
    mainly for tests; callers don't need the return value in production."""
    now = now if now is not None else time.time()
    if not state.armed or now < state.deadline:
        return False
    if state.continuation:
        # A conversation that ran its course, not a wake nobody answered --
        # the consumed follow-up already told the judge this wake was
        # wanted. Filing a timeout here would argue the opposite.
        state.disarm()
        return True
    outcome = ("timeout-with-leftover"
               if has_leftover_content(state.trigger_text, state.matched_word)
               else "timeout-empty")
    spawn_judge(outcome, state.trigger_text, state.match_kind,
                state.match_source, state.matched_word)
    state.disarm()
    return True
