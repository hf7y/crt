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
import importlib.util
import os
import random
import re
import subprocess
import sys
import threading
import time

BIN_DIR = os.path.dirname(os.path.abspath(__file__))

# STT-CONFIDENCE.md's decision function, loaded the same importlib way
# tests/test_secretary.py already loads THIS file -- bin/ scripts here
# aren't packaged, so this is the established pattern for one script
# reusing another's functions.
_conf_spec = importlib.util.spec_from_file_location(
    "crt_stt_confidence", os.path.join(BIN_DIR, "crt-stt-confidence.py"))
stt_confidence = importlib.util.module_from_spec(_conf_spec)
_conf_spec.loader.exec_module(stt_confidence)

# Opt-in, default OFF -- per STT-CONFIDENCE.md's "start conservative" note
# and this project's own rule of never changing live default behavior
# without hands-on verification. When on, a playbook match ALSO
# (sometimes, per call_probability) triggers a silent background Claude
# call purely to confirm the local answer -- see confidence_route().
CONFIDENCE_ENABLED = os.environ.get("CRT_SECRETARY_CONFIDENCE", "0") == "1"
_CONFIDENCE_STATE_LOCK = threading.Lock()
SESSION = os.environ.get("CRT_TMUX_SESSION", "claude")
PANE = os.environ.get("CRT_TMUX_PANE", "0")
REPORTS_DIR = os.path.expanduser(os.environ.get("CRT_REPORTS_DIR", "~/reports/crt"))
REPO_DIR = os.path.expanduser(os.environ.get("CRT_REPO_DIR", "~/crt"))
QUESTIONS = os.environ.get("CRT_QUESTIONS_FILE", os.path.join(REPO_DIR, ".claude/QUESTIONS.md"))
TEST_SUITE = os.environ.get("CRT_TEST_SUITE", os.path.join(REPO_DIR, "tests/run_tests.sh"))
CALIBRATE_BIN = os.environ.get(
    "CRT_CALIBRATE_BIN", os.path.join(BIN_DIR, "crt-calibrate-display.py"))

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
    return spoken


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
        return "I don't see a test suite to run."
    # CRT_SKIP_SECRETARY_TESTS=1: the suite itself runs test_secretary.py,
    # which calls this exact handler in its own tests -- without this, that
    # nested invocation would shell out to the suite again, unbounded.
    env = dict(os.environ, CRT_SKIP_SECRETARY_TESTS="1")
    r = sh(["bash", TEST_SUITE], env=env)
    if r.returncode == 0:
        speak("All green. Every offline check passed.")
        return "All green. Every offline check passed."
    else:
        speak("Something's failing in the test suite. Printing the details.")
        print_full((r.stdout or "") + "\n" + (r.stderr or ""))
        return "Something's failing in the test suite."


# --- Playbook: calibrate --------------------------------------------------
# The overscan calibration game's single-shot entry point (DISPLAY-
# CALIBRATION.md) -- SUPERVISOR.md named this as the natural next
# playbook. Deliberately only runs `show`, not the interactive `run` loop:
# `run` blocks on real voice-driven back-and-forth (its own `input()`
# loop), which doesn't fit handle()'s one-shot request/response shape --
# launching it here would just hang this call until a multi-round
# conversation finished. `show` renders the CURRENT saved margin's test
# pattern once; a human decides from there whether to actually run the
# full game by hand.
CALIBRATE_TRIGGERS = ("calibrate the display", "calibrate the screen", "run the calibration")


def match_calibrate(text):
    return _matches_any(text, CALIBRATE_TRIGGERS)


def handle_calibrate(text):
    if not os.path.exists(CALIBRATE_BIN):
        speak("I don't have the calibration tool installed.")
        return "I don't have the calibration tool installed."
    r = sh(["python3", CALIBRATE_BIN, "show"])
    if not (r.stdout or "").strip():
        speak("Couldn't render the calibration pattern.")
        return "Couldn't render the calibration pattern."
    # The pattern itself is CRT-screen content, not something to speak or
    # print -- write it straight to stdout, the same channel
    # crt-monologue.sh's tmux pane already displays.
    print(r.stdout, end="")
    spoken = "Calibration pattern's up. Run the full game by hand if you want to adjust it."
    speak(spoken)
    return spoken


# --- Playbook: what_time -------------------------------------------------
# The trivial case, included to prove the pattern scales down cleanly.
WHAT_TIME_TRIGGERS = ("what time is it", "what's the time", "whats the time")


def match_what_time(text):
    return _matches_any(text, WHAT_TIME_TRIGGERS)


def handle_what_time(text):
    spoken = datetime.datetime.now().strftime("It's %I:%M %p.").lstrip("0")
    speak(spoken)
    return spoken


# --- Playbook: morning_report --------------------------------------------
# The scheduler's CROSS-PROJECT morning report (chezz, wtul, crt itself,
# etc. -- see MORNING-REPORT-PRESENTATION.md), presented entirely without
# a Claude call via bin/crt-present-morning-report.py, which just parses
# bin/morning-report.sh's own output. Distinct from the `status` playbook
# above, which only covers crt's OWN reports/questions.
MORNING_REPORT_TRIGGERS = (
    "morning report", "give me the morning report", "read me the morning report",
)
MORNING_REPORT_BIN = os.environ.get(
    "CRT_MORNING_REPORT_BIN", os.path.join(BIN_DIR, "crt-present-morning-report.py"))


def match_morning_report(text):
    return _matches_any(text, MORNING_REPORT_TRIGGERS)


def handle_morning_report(text):
    if not os.path.exists(MORNING_REPORT_BIN):
        speak("I don't have a morning report presenter installed.")
        return "I don't have a morning report presenter installed."
    r = sh(["python3", MORNING_REPORT_BIN, "screen"])
    lines = [ln for ln in (r.stdout or "").splitlines() if ln.strip()]
    if not lines:
        speak("Nothing in the morning report right now.")
        return "Nothing in the morning report right now."
    spoken = ("%d project%s in this morning's report. Printing the full thing."
              % (len(lines), "" if len(lines) == 1 else "s"))
    speak(spoken)
    full = sh(["python3", MORNING_REPORT_BIN, "print-all"])
    print_full(full.stdout or "")
    return spoken


# Ordered: first match wins. See SUPERVISOR.md for what belongs here vs.
# what should stay a Claude call.
PLAYBOOKS = (
    ("status", match_status, handle_status),
    ("run_tests", match_run_tests, handle_run_tests),
    ("calibrate", match_calibrate, handle_calibrate),
    ("what_time", match_what_time, handle_what_time),
    ("morning_report", match_morning_report, handle_morning_report),
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


FALLTHROUGH_LOG = os.path.expanduser(
    os.environ.get("CRT_FALLTHROUGH_LOG", "~/.crt/fallthrough.log"))


def log_fallthrough(text):
    """Every request no playbook matched, logged (not acted on) so a
    future session can see which requests keep escalating to Claude and
    are worth writing a new playbook for -- SUPERVISOR.md's open item.
    Best-effort: a broken log write must never block the real Claude
    routing that follows it."""
    try:
        d = os.path.dirname(FALLTHROUGH_LOG)
        if d:
            os.makedirs(d, exist_ok=True)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(FALLTHROUGH_LOG, "a") as f:
            f.write("%s  %s\n" % (ts, text))
    except OSError:
        pass


def _answers_match(local_answer, claude_reply):
    """Best-effort, loose comparison between the secretary's own local
    answer and what Claude said for the same utterance -- STT-CONFIDENCE.md
    option 3's confirmation signal. Exact string equality would almost
    never fire since Claude's phrasing differs from a playbook's canned
    text even when they agree on the underlying fact; normalize + a
    substring check either direction is a first draft, not real semantic
    equivalence. This only ever grows tracking state -- it never changes
    what the user is shown, since the user already got the fast local
    answer before this comparison runs."""
    if not local_answer or not claude_reply:
        return False
    a = stt_confidence.normalize_key(local_answer)
    b = stt_confidence.normalize_key(claude_reply)
    if not a or not b:
        return False
    return a in b or b in a


def _confirm_in_background(text, local_answer):
    """Runs in a background thread AFTER the local playbook has already
    answered, so the user never waits on this. Per STT-CONFIDENCE.md's
    "start conservative" direction: this NEVER skips the local playbook
    (it already ran by the time this is called) and NEVER shows/speaks
    Claude's confirmation reply to the user -- it only sometimes (per
    call_probability, decaying as this utterance shape gets confirmed
    more) fires a silent Claude call purely to grow confirmed_hits/
    claude_hits state for next time. No Claude calls are actually SAVED
    yet by this wiring alone -- that's the deliberate next step once
    real confirmed/unconfirmed data exists (see STT-CONFIDENCE.md)."""
    with _CONFIDENCE_STATE_LOCK:
        state = stt_confidence.load_state()
    if not stt_confidence.should_call_claude(text, state, random):
        return
    before = capture_pane()
    send_to_claude(text)
    reply = wait_for_claude_reply(before)
    with _CONFIDENCE_STATE_LOCK:
        state = stt_confidence.load_state()
        stt_confidence.record_claude_call(text, state)
        if _answers_match(local_answer, reply):
            stt_confidence.record_confirmed(text, state)
        stt_confidence.save_state(state)


def confidence_route(text, action):
    """Runs the matched playbook exactly as before (never skipped, never
    delayed), then -- only when CRT_SECRETARY_CONFIDENCE=1 -- kicks off
    the background confirmation pass above. Default off: with the flag
    unset this is byte-for-byte the old action(text) behavior."""
    local_answer = action(text)
    if CONFIDENCE_ENABLED and local_answer:
        threading.Thread(
            target=_confirm_in_background, args=(text, local_answer), daemon=True
        ).start()
    return local_answer


def handle(text):
    _, action = find_playbook(text)
    if action:
        confidence_route(text, action)
        return

    log_fallthrough(text)
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
