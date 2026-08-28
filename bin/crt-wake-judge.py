#!/usr/bin/env python3
# The autonomous wake-word self-tuning judge (2026-07-21, Zach's direct
# ask): "call claude, if it got ignored, tweak. if it sees a lot of
# attempts to wake it failing... tweak. but also be available to help
# (i.e. factor in whether it was genuinely used on wake)."
#   [rest: vault:crt/header-archaeology-20260817.md]
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

EVENTS_LOG = os.path.expanduser(
    os.environ.get("CRT_WAKE_JUDGE_EVENTS_LOG", "~/.crt/wake-judge-events.log"))
EVENTS_LOG_MAX_LINES = int(os.environ.get("CRT_WAKE_JUDGE_EVENTS_LOG_MAX_LINES", "500"))


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


def log_event(outcome, trigger_text, match_kind, match_source=None,
              matched_word=None, followup_text=None, now=None, log_path=None):
    now = now if now is not None else time.time()
    log_path = log_path or EVENTS_LOG
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "outcome": outcome,
        "trigger_text": trigger_text,
        "match_kind": match_kind,
        "match_source": match_source,
        "matched_word": matched_word,
        "followup_text": followup_text,
    }
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        lines = []
        if os.path.exists(log_path):
            with open(log_path) as f:
                lines = f.readlines()
        lines.append(json.dumps(record) + "\n")
        with open(log_path, "w") as f:
            f.writelines(lines[-EVENTS_LOG_MAX_LINES:])
    except OSError:
        pass


def build_prompt(outcome, trigger_text, match_kind, match_source=None,
                  matched_word=None, followup_text=None):
    """Pure function: the actual prompt handed to `claude -p`. Includes
    enough concrete detail (exact trigger text, which mechanism fired,
    the ground-truth outcome) that Claude can judge without needing to
    go re-derive context, plus explicit pointers to the three files it's
    allowed to edit, the events log for pattern history, and the "don't
    act on a single event" guardrail from WAKE-TUNING-STATE.md."""
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
        f"Read {TUNING_DOC} first for full context: current tuning values and the reasoning",
        "behind them. IMPORTANT: do not tweak anything based on this ONE event alone unless",
        "it's blatant (e.g. an obviously unrelated word armed the system). Zach's own",
        "instruction: tune on a PATTERN of failures, not a single data point -- every wake",
        f"event (this one included) is recorded in {EVENTS_LOG}, one JSON object per line,",
        "regardless of whether it's judged tuning-worthy. Check it for recent similar",
        "outcomes on the same word/source before making a change.",
        "",
        "Files you may edit if a tuning change is warranted:",
        f"  - {DICT_PATH} (remove a specific bad wake-pool word)",
        f"  - {TUNING_CONFIG} (JSON: close_ratio, cluster_min_by_source -- read it first,",
        "    it may not exist yet, in which case crt-wake-pool.py's own code defaults are",
        "    in effect and this file should be created with your adjusted values)",
        f"  - {TUNING_DOC} (append a dated entry to the Judgment log ONLY when you actually",
        "    make a tuning change, describing what changed and why)",
        "",
        "Do NOT append to the Judgment log when you leave the tuning alone -- that is the",
        f"common case, it is already captured in {EVENTS_LOG}, and the log's whole point",
        "is that an entry there means a knob moved.",
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

    match_source = get("--match-source")
    matched_word = get("--matched-word")
    followup_text = get("--followup-text")

    log_event(outcome, trigger_text, match_kind, match_source, matched_word, followup_text)

    if rate_limited():
        sys.exit(0)
    touch_rate_limit()

    run_judge(
        outcome, trigger_text, match_kind,
        match_source=match_source,
        matched_word=matched_word,
        followup_text=followup_text,
    )


if __name__ == "__main__":
    main()
