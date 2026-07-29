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
# 2026-07-29: WHICH CLOCK the window is measured on turned out to matter
# more than its length. Every time below is wall-clock, but there are two
# very different wall-clock instants attached to one utterance -- when it was
# SPOKEN, and when its transcript came back -- and the caller was using the
# second for both ends of the comparison. That silently charged the window
# for the follow-up's own speaking duration plus two whisper round-trips.
# Measured on potato's real ~/.crt/stt.log (1597 consecutive-utterance gaps,
# 2026-07-29): median transcript-to-transcript gap 21s against a 12s window,
# with a hard mode at 20-22s because CRT_VAD_MAX cuts continuous speech at
# 20s -- so during exactly the run-on speech this room produces, the true
# silence between two utterances is under a second while the number the
# window was comparing against was over twenty. The window was not too
# short; it was being measured from the wrong end of the utterance. Callers
# now pass the ONSET of a follow-up (openness test) and the END of whatever
# arms/slides the window (deadline anchor); both default to the module clock
# so a caller that passes neither behaves exactly as before.
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

# Where the open window is published for OTHER processes (2026-07-25,
# twentieth cycle). The state machine itself is in-process -- one ArmState
# held by crt-stt-solo.py for the life of the engine -- and that was enough
# while the engine was the only thing that cared. It is not: bin/crt-book-
# answer-listen.py reads the SAME ~/.crt/stt.log with the opposite rule
# (anything inside a scanned book's answer window is a trivia answer), and an
# arm-window follow-up carries no wake word BY DESIGN, so from over there it
# is indistinguishable from someone answering the question on the tube. See
# that file's grade_pending_answer() for what it costs.
#
# A DEADLINE, not a flag: the wake utterance opens the window, so the file is
# already on disk before the follow-up it describes is ever spoken -- no
# ordering race with emit()'s own stt.log append, which happens before the
# routing decision. A stale file (a crash, a reboot, arming turned back off)
# describes a deadline in the past and reads as closed, so there is nothing
# to clean up and no second env var for the reader to agree about.
ARM_STATE_FILE = os.path.expanduser(
    os.environ.get("CRT_WAKE_ARM_STATE", "~/.crt/wake-arm.state"))

# Since 2026-07-29 this is a budget for SILENCE, not for round-trips: it is
# measured from the end of the wake utterance's audio to the start of the
# follow-up's, so neither utterance's own length nor whisper's latency spends
# any of it. 12s of dead air before the console stops assuming you are still
# talking to it is a defensible number; 12s covering "say a sentence, wait for
# two transcriptions, and start the next one" was not, and that is what it
# silently meant before. Do not re-tune this by ear without checking which of
# the two it is currently measuring.
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
        the conversation already in progress.

        CONFIRMED BY ZACH 2026-07-25, in reply to the twelfth nightly
        cycle's report, in these words: "Always starts a FRESH session,
        including when one is already open -- saying the wake word again is
        deliberate, so it resets the ARM_MAX_SECS ceiling rather than being
        swallowed by the conversation already in progress." That settles
        the open question a9e899b raised (does the ceiling belong to a
        conversation, or to a wake? -- to a wake). This is no longer an
        inference from a docstring: do NOT "simplify" the re-wake branch in
        consume_arm_with_followup() back into a plain slide."""
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


def publish_arm_window(state, path=None, reader_lag=0.0):
    """Mirror `state`'s deadline to ARM_STATE_FILE so another process can ask
    whether the console is mid-conversation. Writes 0 when disarmed.

    `reader_lag` TRANSLATES BETWEEN THE TWO CLOCKS (2026-07-29). Since that
    date `state.deadline` is in audio time -- when the person stopped
    speaking -- but the only reader of this file, bin/crt-book-answer-listen.py,
    tails ~/.crt/stt.log and asks arm_window_open() at the moment a line
    APPEARS there, which is one whisper round-trip later. Publishing the raw
    audio-time deadline would hand that reader a window shorter than the one
    the engine is enforcing, and every follow-up landing in the difference
    would be graded as a trivia answer on the tube as well as being answered
    by Claude. So the caller passes the lag it just measured on the utterance
    that armed or slid this window, and the published number lands in the
    reader's own domain -- which for a wake that took L seconds to transcribe
    is publish-time + ARM_SECS, i.e. bit-for-bit what this file carried before
    the clock fix. The engine's internal window is corrected; the reader's
    contract is deliberately not changed at the same time.

    Defaults to 0.0, which publishes the deadline unmodified -- what every
    caller that has no lag to report (a timeout, a test) should do.

    Called by the SOLE MIC READER after every arm-state transition, so it is
    held to that loop's rules: never raises (an unwritable ~/.crt must not
    cost the console its ears), and never blocks on anything but one small
    local write. os.replace so a reader can never catch a half-written
    number -- the reader tolerates one anyway, but a torn read here would
    silently mean "closed", which is the failure this file exists to stop.

    Deliberately NOT a method on ArmState: that object is pure, held by
    reference in tests that arm and slide it hundreds of times, and giving it
    a filesystem side effect would put ~/.crt writes inside the unit tests --
    the test-hermeticity class this project has already paid for once."""
    # `is None` means "use the module default", NOT `or` -- an explicit ""
    # has to be able to mean "publish nowhere" (CRT_WAKE_ARM_STATE= turns
    # this off), and `path or ARM_STATE_FILE` would quietly redirect that to
    # the real ~/.crt/wake-arm.state instead. Caught by a test of this file
    # writing into the suite runner's own home directory.
    path = ARM_STATE_FILE if path is None else path
    if not path:
        return
    deadline = (state.deadline + reader_lag) if state.armed else 0.0
    tmp = path + ".tmp"
    try:
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(tmp, "w") as f:
            f.write("%.3f\n" % deadline)
        os.replace(tmp, path)
    except OSError:
        pass


def read_arm_deadline(path=None):
    """The published deadline as a Unix epoch float, or None if there isn't
    one to read (never published, unreadable, junk). None means "no open
    window", never a crash -- this is called from another window's own loop
    and a missing file is the ordinary case, not an error."""
    path = ARM_STATE_FILE if path is None else path   # see publish_arm_window
    if not path:
        return None
    try:
        with open(path) as f:
            return float(f.read().strip())
    except (OSError, ValueError):
        return None


def arm_window_open(now=None, path=None):
    """True when a sticky-conversation window is open RIGHT NOW -- i.e. the
    engine will route the next utterance to Claude as a follow-up, without it
    needing to carry the wake word.

    The boundary belongs to the engine, not to this reader: an utterance
    arriving within a hair of the deadline may be consumed there and read as
    closed here (or the reverse). Both processes read the same clock on the
    same box, so the disagreement window is sub-millisecond, and it degrades
    to exactly the behaviour that existed before this function -- a follow-up
    also graded as a trivia answer -- rather than to anything new."""
    deadline = read_arm_deadline(path)
    if deadline is None:
        return False
    return (now if now is not None else time.time()) < deadline


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


def consume_arm_with_followup(state, followup_text, now=None, wake_match=None,
                              arm_secs=None, max_secs=None, ended_at=None):
    """A real follow-up utterance arrived while armed -- strong evidence
    the wake was wanted (WAKE-TUNING-STATE.md's ground-truth rule).
    Disarms and spawns the judge with outcome=consumed. Returns True if
    there was actually anything armed to consume -- callers use this to
    decide whether to treat followup_text as implicitly addressed,
    bypassing the normal wake-word gate for just this one utterance.

    `wake_match` is the caller's (kind, source, matched_word) classification
    of followup_text ITSELF -- crt-stt-solo.py's classify_wake_match(). When
    it carries a kind, this follow-up is a deliberate re-wake, and the whole
    point of arm()'s "always starts a FRESH session" contract is that such a
    re-wake resets the ARM_MAX_SECS ceiling instead of being swallowed by
    the session already in progress (2026-07-25, twelfth cycle: that
    contract was only ever reachable from a disarmed state -- see the
    caller's own note). Zach confirmed that contract directly on
    2026-07-25 -- see arm()'s docstring for his words. The re-wake branch
    below is load-bearing, not an optimisation.

    TWO TIMES, deliberately (2026-07-29, see this file's header):
    `now` is when the follow-up STARTED being spoken -- the only fair thing
    to test an "is the window still open?" deadline against, since the person
    cannot know how long their own sentence will run or how long whisper will
    take. `ended_at` is when it FINISHED, and is what the resulting slide or
    re-wake is anchored to, so the next window starts counting from the end of
    the speech rather than from the middle of it. `ended_at` defaults to `now`,
    which is the pre-2026-07-29 behaviour exactly."""
    now = now if now is not None else time.time()
    ended_at = ended_at if ended_at is not None else now
    if not state.armed or now >= state.deadline:
        return False
    spawn_judge("consumed", state.trigger_text, state.match_kind,
                state.match_source, state.matched_word, followup_text)
    if wake_match and wake_match[0]:
        kind, source, word = wake_match
        state.arm(followup_text, kind, source, word, now=ended_at,
                  arm_secs=arm_secs, max_secs=max_secs)
        return True
    # Slide, don't close: the live 2026-07-23 bug was FOUR follow-ups in one
    # breath, and a window that shuts after the first still drops three of
    # them -- the same complaint, one utterance later. Capped by
    # ARM_MAX_SECS so a sliding window can't become an always-on mic.
    if not state.slide(followup_text, ended_at, arm_secs=arm_secs):
        state.disarm()
    return True


def check_arm_timeout(state, now=None, utt_start=None):
    """Call periodically (crt-stt-solo.py's own fast capture-loop tick is
    fine, cheap -- no VAD/whisper work happens here). If armed and the
    deadline has passed with no follow-up ever consumed, disarms and
    spawns the judge with timeout-with-leftover or timeout-empty per
    has_leftover_content() on the ORIGINAL trigger text. Returns True if
    a timeout was actually processed (state was armed and had expired) --
    mainly for tests; callers don't need the return value in production.

    `utt_start` is the wall-clock onset of an utterance the mic is capturing
    RIGHT NOW, or None when the room is quiet (2026-07-29). An utterance that
    BEGAN inside the window is still a candidate follow-up even if it is
    still being spoken -- and it can be spoken for a long time, since
    CRT_VAD_MAX lets one run 20s against a 12s window. Timing out underneath
    it would disarm the window and then gate-drop the very utterance the
    window was opened to admit, which is the failure this whole file exists
    to prevent. So the timeout is DEFERRED, not cancelled: the next tick after
    that utterance resolves finds the mic idle again and fires it. A follow-up
    that starts AFTER the deadline gets no such protection -- it could not
    have been consumed anyway.

    The deferral is self-bounding and needs no ceiling of its own:
    crt-stt-solo.py's utt_chunk() hard-caps a single utterance at CRT_VAD_MAX
    (20s by default) and at MUTE_UTT_MAX_SECS while ducked, so the mic cannot
    stay `in_utt` indefinitely and the window cannot be held open by a stuck
    capture state. Worst case is deadline + CRT_VAD_MAX, comfortably inside
    ARM_MAX_SECS at both defaults."""
    now = now if now is not None else time.time()
    if not state.armed or now < state.deadline:
        return False
    if utt_start is not None and utt_start < state.deadline:
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
