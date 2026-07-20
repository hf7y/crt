#!/usr/bin/env python3
# The secretary wrapper -- SECRETARY.md steps 1-4 / SUPERVISOR.md's
# playbook model, first real implementation. Sits between stt-feed.sh and
# the claude tmux pane: runs an ordered list of PLAYBOOKS, each a plain
# (match, handle) pair -- the first one whose match() fires handles the
# request entirely locally (no Claude Code call at all). Only a request
# nothing matches falls through to the existing Claude-routing path
# (tmux send-keys + capture-pane), which then decides printer vs. CRT vs.
# TTS for the reply instead of leaving it to sit in tmux scrollback.
#
# STATUS: NOT hardware-verified. Playbooks are covered by
# tests/test_secretary.py against synthetic files (status) and a real
# invocation of this repo's own tests/run_tests.sh (run_tests). The
# Claude-routing path (send via tmux send-keys, then poll capture-pane for
# "the reply has stopped changing") is the riskiest part of this whole
# design -- it's a real heuristic (idle-detect by diffing repeated
# captures) with no live Claude Code CLI to test it against. Treat
# CLAUDE_IDLE_SECS/CLAUDE_MAX_WAIT as first-draft guesses, and expect the
# pane-diff to need real tuning once someone can watch it run against the
# actual CLI's prompt chrome/spinner output.
#
# Usage:
#   crt-secretary.py "text"          # one utterance, decide + act
# Env (matches conventions used elsewhere in bin/):
#   CRT_TMUX_SESSION (default claude), CRT_TMUX_PANE (default 0)
#   CRT_REPORTS_DIR (default ~/reports/crt), CRT_REPO_DIR (default ~/crt)
import datetime
import os
import re
import subprocess
import sys
import time

BIN_DIR = os.path.dirname(os.path.abspath(__file__))
SESSION = os.environ.get("CRT_TMUX_SESSION", "claude")
PANE = os.environ.get("CRT_TMUX_PANE", "0")
REPORTS_DIR = os.path.expanduser(os.environ.get("CRT_REPORTS_DIR", "~/reports/crt"))
REPO_DIR = os.path.expanduser(os.environ.get("CRT_REPO_DIR", "~/crt"))
QUESTIONS = os.environ.get("CRT_QUESTIONS_FILE", os.path.join(REPO_DIR, ".claude/QUESTIONS.md"))
TEST_SUITE = os.environ.get("CRT_TEST_SUITE", os.path.join(REPO_DIR, "tests/run_tests.sh"))

CLAUDE_IDLE_SECS = float(os.environ.get("CRT_SECRETARY_IDLE_SECS", "3"))
CLAUDE_MAX_WAIT = float(os.environ.get("CRT_SECRETARY_MAX_WAIT", "120"))
CLAUDE_POLL = float(os.environ.get("CRT_SECRETARY_POLL", "1"))

SHORT_ANSWER_CHARS = 240  # above this, speak a one-line summary + print full text


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def speak(text, device="handset"):
    sh(["python3", os.path.join(BIN_DIR, "crt-tts.py"), "--device", device, text])


def print_full(text):
    sh([os.path.join(BIN_DIR, "crt-print.sh")], input=text)


def read_local_status():
    """Build a short spoken summary from the same files crt-idle-teaser.sh
    watches, plus the full text for printing if he wants it."""
    parts = []
    latest = os.path.join(REPORTS_DIR, "LATEST.md")
    if os.path.exists(latest):
        with open(latest) as f:
            body = f.read()
        bullets = [ln for ln in body.splitlines() if ln.startswith("- ")]
        if bullets:
            parts.append("Reports:\n" + "\n".join(bullets))

    if os.path.exists(QUESTIONS):
        with open(QUESTIONS) as f:
            body = f.read()
        bullets = [ln for ln in body.splitlines() if ln.startswith("- **")]
        if bullets:
            parts.append("Open questions:\n" + "\n".join(bullets))

    if not parts:
        return None, "Nothing new since I last checked. Pretty quiet."

    full_text = "\n\n".join(parts)
    n_items = sum(p.count("\n- ") + 1 for p in parts)
    spoken = "You've got %d thing%s waiting. Want me to print the details?" % (
        n_items, "" if n_items == 1 else "s")
    return full_text, spoken


def _matches_any(text, triggers):
    low = text.lower().strip()
    return any(trigger in low for trigger in triggers)


# --- Playbook: status -------------------------------------------------
# Answerable locally without ever waking Claude -- these are exactly the
# phrases idle-bait's payoff is supposed to satisfy (IDLE-BAIT.md step
# "he asks what's up" -> answered by voice, no tmux involved).
STATUS_TRIGGERS = (
    "what's up", "whats up", "what is up",
    "any reports", "any report", "anything new",
    "what happened", "what's new", "whats new",
    "any questions", "any blockers", "any blocker",
    "status", "give me a status",
)


def match_status(text):
    return _matches_any(text, STATUS_TRIGGERS)


def handle_status(text):
    full_text, spoken = read_local_status()
    speak(spoken)
    if full_text:
        print_full(full_text)


# --- Playbook: run_tests ------------------------------------------------
# "is the code still healthy" is exactly as deterministic-given-local-state
# as reading a report file -- SUPERVISOR.md's bar for a playbook -- so this
# runs tests/run_tests.sh (built this session) directly, no Claude needed.
RUN_TESTS_TRIGGERS = (
    "run the tests", "run the test suite", "run tests",
    "are the tests passing", "tests passing", "check the tests",
)


def match_run_tests(text):
    return _matches_any(text, RUN_TESTS_TRIGGERS)


def handle_run_tests(text):
    if not os.path.exists(TEST_SUITE):
        speak("I don't see a test suite to run.")
        return
    # CRT_SKIP_SECRETARY_TESTS=1: the suite itself runs test_secretary.py,
    # which calls this exact handler in its own tests -- without this, that
    # nested invocation would shell out to the suite again, unbounded.
    env = dict(os.environ, CRT_SKIP_SECRETARY_TESTS="1")
    r = sh(["bash", TEST_SUITE], env=env)
    if r.returncode == 0:
        speak("All green. Every offline check passed.")
    else:
        speak("Something's failing in the test suite. Printing the details.")
        print_full((r.stdout or "") + "\n" + (r.stderr or ""))


# --- Playbook: what_time -------------------------------------------------
# The trivial case, included to prove the pattern scales down cleanly.
WHAT_TIME_TRIGGERS = ("what time is it", "what's the time", "whats the time")


def match_what_time(text):
    return _matches_any(text, WHAT_TIME_TRIGGERS)


def handle_what_time(text):
    speak(datetime.datetime.now().strftime("It's %I:%M %p.").lstrip("0"))


# Ordered: first match wins. See SUPERVISOR.md for what belongs here vs.
# what should stay a Claude call.
PLAYBOOKS = (
    ("status", match_status, handle_status),
    ("run_tests", match_run_tests, handle_run_tests),
    ("what_time", match_what_time, handle_what_time),
)


def find_playbook(text):
    for name, match, action in PLAYBOOKS:
        if match(text):
            return name, action
    return None, None


def capture_pane():
    r = sh(["tmux", "capture-pane", "-t", "%s:%s" % (SESSION, PANE), "-p", "-S", "-200"])
    return r.stdout if r.returncode == 0 else ""


def send_to_claude(text):
    sh(["tmux", "send-keys", "-t", "%s:%s" % (SESSION, PANE), "-l", text])
    sh(["tmux", "send-keys", "-t", "%s:%s" % (SESSION, PANE), "Enter"])


def wait_for_claude_reply(before_snapshot):
    """Poll capture-pane until it stops changing for CLAUDE_IDLE_SECS, or
    CLAUDE_MAX_WAIT elapses. Returns the pane lines added since before_snapshot
    (best-effort -- a real terminal UI has spinners/prompt redraws that a
    plain diff can't fully distinguish from genuine new content; this is a
    first draft, not a robust terminal parser)."""
    deadline = time.time() + CLAUDE_MAX_WAIT
    last = capture_pane()
    stable_since = time.time()
    while time.time() < deadline:
        time.sleep(CLAUDE_POLL)
        now_snap = capture_pane()
        if now_snap != last:
            last = now_snap
            stable_since = time.time()
        elif time.time() - stable_since >= CLAUDE_IDLE_SECS:
            break

    before_lines = before_snapshot.splitlines()
    after_lines = last.splitlines()
    # Crude diff: new trailing lines not present in the before-snapshot's
    # tail. Good enough as a first cut; a real implementation should key off
    # Claude Code's actual prompt markers instead of pure line-set diffing.
    new_lines = [ln for ln in after_lines if ln not in before_lines]
    reply = "\n".join(ln for ln in new_lines if ln.strip())
    return reply.strip()


def route_claude_reply(reply):
    if not reply:
        speak("I sent that to Claude but didn't catch a reply -- check the screen.")
        return
    clean = re.sub(r"\s+", " ", reply).strip()
    if len(clean) <= SHORT_ANSWER_CHARS:
        speak(clean)
    else:
        speak(clean[:160].rsplit(" ", 1)[0] + "... printing the rest.")
        print_full(reply)


def handle(text):
    _, action = find_playbook(text)
    if action:
        action(text)
        return

    before = capture_pane()
    send_to_claude(text)
    reply = wait_for_claude_reply(before)
    route_claude_reply(reply)


def main():
    text = " ".join(sys.argv[1:]).strip() or sys.stdin.read().strip()
    if not text:
        sys.stderr.write("usage: crt-secretary.py <text>\n")
        sys.exit(2)
    handle(text)


if __name__ == "__main__":
    main()
