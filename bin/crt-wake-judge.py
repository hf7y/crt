#!/usr/bin/env python3
# The autonomous wake-word self-tuning judge (2026-07-21, Zach's direct
# ask): "call claude, if it got ignored, tweak. if it sees a lot of
# attempts to wake it failing... tweak. but also be available to help
# (i.e. factor in whether it was genuinely used on wake)."
#
# Spawned (Popen, fire-and-forget) by crt-stt-solo.py once a wake event's
# arm window has RESOLVED (either consumed by a real follow-up, or timed
# out) -- not at the moment of arming itself, since "was this genuinely
# used" is exactly the ground-truth signal this needs and that isn't
# known until the window closes. Rate-limited via a simple lockfile-with-
# timestamp so a burst of wake events (e.g. the book-title-noise flood
# that motivated this whole pass) can't spawn a pile of overlapping
# `claude -p` calls.
#
# This script's job ends at building the prompt and invoking `claude -p`
# with write access to the tuning files -- it does NOT parse Claude's
# output or apply any change itself. Claude's own file-editing tools do
# the actual tuning (wake-pool-dict.txt, wake-tuning-config.json,
# WAKE-TUNING-STATE.md), same "give it real tool access, trust the
# judgment" posture as crt-secretary.py's Claude-escalation path, just
# headless/non-interactive instead of typed into the live window-0
# session (this must NOT interrupt/interleave with whatever Zach is
# actually doing in window 0 right now).
#
# STATUS: written 2026-07-21, NOT hardware-verified -- no real claude -p
# call has been observed live yet. The rate-limit/prompt-building logic
# is pure and unit-tested (tests/test_wake_judge.py); the actual `claude
# -p` invocation is a real subprocess call this test suite cannot safely
# exercise (would spend real API usage in CI).
#
# Usage: crt-wake-judge.py --outcome consumed|timeout-with-leftover|timeout-empty
#                           --trigger-text "..." --match-kind exact|pool|fuzzy
#                           [--match-source dict|book-title] [--matched-word "..."]
#                           [--followup-text "..."]
import json
import os
import subprocess
import sys
import time

BIN_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BIN_DIR)

RATE_LIMIT_SECS = float(os.environ.get("CRT_WAKE_JUDGE_RATE_LIMIT_SECS", "45"))
RATE_LIMIT_STATE = os.path.expanduser(
    os.environ.get("CRT_WAKE_JUDGE_RATE_LIMIT_STATE", "~/.crt/wake-judge-last-run.state"))
TUNING_DOC = os.path.join(PROJECT_DIR, "WAKE-TUNING-STATE.md")
TUNING_CONFIG = os.path.expanduser(
    os.environ.get("CRT_WAKE_TUNING_CONFIG", "~/.crt/wake-tuning-config.json"))
DICT_PATH = os.path.expanduser(os.environ.get("CRT_WAKE_POOL_DICT", "~/.crt/wake-pool-dict.txt"))
CLAUDE_BIN = os.environ.get("CRT_CLAUDE_BIN", "claude")
JUDGE_TIMEOUT_SECS = float(os.environ.get("CRT_WAKE_JUDGE_TIMEOUT_SECS", "60"))


def rate_limited(now=None, state_path=None):
    """True if a judge call ran within RATE_LIMIT_SECS of now -- pure
    given an injected now/state_path, but reads real wall-clock/file
    state by default. Missing/malformed state file means "not rate
    limited" (never blocks the first-ever call)."""
    now = now if now is not None else time.time()
    state_path = state_path or RATE_LIMIT_STATE
    try:
        with open(state_path) as f:
            last = float(f.read().strip())
    except (OSError, ValueError):
        return False
    return (now - last) < RATE_LIMIT_SECS


def touch_rate_limit(now=None, state_path=None):
    now = now if now is not None else time.time()
    state_path = state_path or RATE_LIMIT_STATE
    try:
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        with open(state_path, "w") as f:
            f.write(str(now))
    except OSError:
        pass


def build_prompt(outcome, trigger_text, match_kind, match_source=None,
                  matched_word=None, followup_text=None):
    """Pure function: the actual prompt handed to `claude -p`. Includes
    enough concrete detail (exact trigger text, which mechanism fired,
    the ground-truth outcome) that Claude can judge without needing to
    go re-derive context, plus explicit pointers to the three files it's
    allowed to edit and the "don't act on a single event" guardrail from
    WAKE-TUNING-STATE.md."""
    lines = [
        "You are the autonomous wake-word tuning judge for this CRT voice console project.",
        "A wake event just occurred and its outcome is now known. Judge whether it was a",
        "GOOD wake (genuinely addressed to the console) or a BAD wake (noise/ordinary",
        "conversation that shouldn't have triggered), then decide whether any tuning change",
        "is warranted.",
        "",
        f"Trigger text (what STT heard): {trigger_text!r}",
        f"Match kind: {match_kind}" + (f" (source: {match_source})" if match_source else ""),
    ]
    if matched_word:
        lines.append(f"Matched word: {matched_word!r}")
    lines.append(f"Outcome: {outcome}")
    if followup_text:
        lines.append(f"Follow-up utterance that was dispatched: {followup_text!r}")
    lines += [
        "",
        "Outcome meanings:",
        "  consumed            -- a real follow-up arrived and was dispatched. Strong",
        "                         evidence this was a GOOD wake.",
        "  timeout-with-leftover -- the wake had leftover content but nobody continued",
        "                         within the arm window before it dispatched alone.",
        "  timeout-empty        -- a bare wake trigger with no leftover and no follow-up",
        "                         ever came. Evidence (not proof) this was a BAD wake.",
        "",
        f"Read {TUNING_DOC} first for full context: current tuning values, the reasoning",
        "behind them, and the judgment log of past decisions. IMPORTANT: do not tweak",
        "anything based on this ONE event alone unless it's blatant (e.g. an obviously",
        "unrelated word armed the system). Zach's own instruction: tune on a PATTERN of",
        "failures, not a single data point -- check the judgment log for recent similar",
        "outcomes on the same word/source before making a change.",
        "",
        "Files you may edit if a tuning change is warranted:",
        f"  - {DICT_PATH} (remove a specific bad wake-pool word)",
        f"  - {TUNING_CONFIG} (JSON: close_ratio, cluster_min_by_source -- read it first,",
        "    it may not exist yet, in which case crt-wake-pool.py's own code defaults are",
        "    in effect and this file should be created with your adjusted values)",
        f"  - {TUNING_DOC} (append a dated entry to the Judgment log describing this event,",
        "    the verdict, and what you changed or why you left it alone)",
        "",
        "Always append a judgment log entry, even if you make no tuning change -- the log",
        "existing at all is what lets a future judge call see the pattern.",
    ]
    return "\n".join(lines)


def run_judge(outcome, trigger_text, match_kind, match_source=None,
              matched_word=None, followup_text=None):
    """Spawns `claude -p` with the built prompt, in PROJECT_DIR so it has
    the project's own CLAUDE.md context and can resolve the tuning file
    paths naturally. Fire-and-forget from the CALLER's perspective (this
    function itself blocks up to JUDGE_TIMEOUT_SECS, but callers should
    invoke this whole script via Popen, not call run_judge() inline in
    the capture loop)."""
    prompt = build_prompt(outcome, trigger_text, match_kind, match_source,
                          matched_word, followup_text)
    try:
        subprocess.run(
            [CLAUDE_BIN, "-p", prompt,
             "--allowedTools", "Read", "Edit", "Write",
             "--permission-mode", "acceptEdits"],
            cwd=PROJECT_DIR, timeout=JUDGE_TIMEOUT_SECS,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def main():
    args = dict(zip(sys.argv[1::2], sys.argv[2::2])) if len(sys.argv) > 1 else {}
    def get(flag, default=None):
        return args.get(flag, default)

    outcome = get("--outcome")
    trigger_text = get("--trigger-text", "")
    match_kind = get("--match-kind", "exact")
    if not outcome:
        sys.stderr.write("usage: crt-wake-judge.py --outcome <...> --trigger-text <...> --match-kind <...>\n")
        sys.exit(2)

    if rate_limited():
        sys.exit(0)
    touch_rate_limit()

    run_judge(
        outcome, trigger_text, match_kind,
        match_source=get("--match-source"),
        matched_word=get("--matched-word"),
        followup_text=get("--followup-text"),
    )


if __name__ == "__main__":
    main()
