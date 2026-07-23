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

    def arm(self, text, match_kind, match_source=None, matched_word=None,
            now=None, arm_secs=None):
        now = now if now is not None else time.time()
        arm_secs = arm_secs if arm_secs is not None else ARM_SECS
        self.armed = True
        self.deadline = now + arm_secs
        self.trigger_text = text
        self.match_kind = match_kind
        self.match_source = match_source
        self.matched_word = matched_word

    def disarm(self):
        self.armed = False


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
    outcome = ("timeout-with-leftover"
               if has_leftover_content(state.trigger_text, state.matched_word)
               else "timeout-empty")
    spawn_judge(outcome, state.trigger_text, state.match_kind,
                state.match_source, state.matched_word)
    state.disarm()
    return True
