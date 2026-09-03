#!/usr/bin/env python3
# The arm-window state machine wiring crt-wake-judge.py's autonomous
# tuning judge to a real live trigger -- the ONE missing piece identified
# 2026-07-23: consume_arm_with_followup()/check_arm_timeout() are
# referenced by name in crt-wake-judge.py's own prompt-building code and
#   [rest: vault:crt/header-archaeology-20260817.md]
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
#   [rest: vault:crt/header-archaeology-20260817.md]
ARM_STATE_FILE = os.path.expanduser(
    os.environ.get("CRT_WAKE_ARM_STATE", "~/.crt/wake-arm.state"))

# A budget for SILENCE, not for round-trips: measured from the end of the
# wake utterance's audio to the start of the follow-up's, so neither
# utterance's length nor whisper's latency spends any of it. Check what it
# measures before re-tuning it by ear.
ARM_SECS = float(os.environ.get("CRT_WAKE_ARM_SECS", "12"))
# Hard ceiling on one sticky conversation (2026-07-25). A consumed follow-up
# SLIDES the window forward -- the live bug this exists for was four
# follow-ups in one breath, of which a single-shot window would still have
# dropped three -- but sliding with no ceiling is dangerous in this
#   [rest: vault:crt/header-archaeology-20260817.md]
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

    `reader_lag` translates between the two clocks. `state.deadline` is in
    audio time; the file's only reader (crt-book-answer-listen.py) asks the
    moment a transcript APPEARS, one round-trip later, so publishing the raw
    deadline hands it a shorter window than the engine enforces. 0.0 publishes
    unmodified -- what a timeout or a test passes.

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

    TWO TIMES, deliberately: `now` is when the follow-up STARTED being
    spoken, the only fair thing to test the deadline against; `ended_at` is
    when it finished, and anchors the slide or re-wake. `ended_at` defaults
    to `now`, the pre-2026-07-29 behaviour exactly."""
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

    `utt_start` is the onset of an utterance the mic is capturing RIGHT NOW,
    or None when the room is quiet. One that BEGAN inside the window is still
    a candidate follow-up, so the timeout is DEFERRED rather than cancelled --
    firing underneath it would disarm the window and gate-drop the very
    utterance it was opened to admit. Self-bounding: utt_chunk() hard-caps one
    utterance at CRT_VAD_MAX, so the worst case is deadline + CRT_VAD_MAX."""
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
