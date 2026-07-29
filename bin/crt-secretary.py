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

# PARKING-LOT.md's speculative/optimistic-response filler, loaded the
# same importlib way. Opt-in, default OFF, same "never change live
# default behavior without hands-on verification" rule -- see handle()'s
# Claude-escalation branch below for where this fires.
_spec_spec = importlib.util.spec_from_file_location(
    "crt_speculate", os.path.join(BIN_DIR, "crt-speculate.py"))
speculate = importlib.util.module_from_spec(_spec_spec)
_spec_spec.loader.exec_module(speculate)

SPECULATE_ENABLED = os.environ.get("CRT_SECRETARY_SPECULATE", "0") == "1"

# PARKING-LOT.md's second "primary product surface" job: voice-driven
# media playback. Loaded the same importlib way as the other bin/
# scripts this file reuses -- see crt-media-player.py's own header for
# why it's a pluggable Backend (FakeBackend for tests, VlcBackend
# untested-live) rather than a finished VLC/mpv integration.
_media_spec = importlib.util.spec_from_file_location(
    "crt_media_player", os.path.join(BIN_DIR, "crt-media-player.py"))
media_player = importlib.util.module_from_spec(_media_spec)
_media_spec.loader.exec_module(media_player)
MEDIA_BACKEND = media_player.VlcBackend()
SESSION = os.environ.get("CRT_TMUX_SESSION", "claude")
PANE = os.environ.get("CRT_TMUX_PANE", "0")

# One config question, one answer, shared with crt-stt-solo.py: is the pane
# below a Claude brain, or the potato idle face? See bin/crt_config.py's
# PANE_ENV block for the whole finding. Read once at import -- this process
# is spawned fresh per utterance, so there is nothing to go stale.
_cfg_spec = importlib.util.spec_from_file_location(
    "crt_config_for_secretary", os.path.join(BIN_DIR, "crt_config.py"))
crt_config = importlib.util.module_from_spec(_cfg_spec)
_cfg_spec.loader.exec_module(crt_config)
LOCAL_PANE_IS_IDLE_FACE = crt_config.pane_is_idle_face()
# Built here, beside the decision it explains -- see crt-stt-solo.py's copy.
IDLE_FACE_PANE_REPORT = crt_config.idle_face_pane_report(PANE)

# Remote-Claude wiring (2026-07-23, reverse-tunneled local-socket first
# cut -- see FOCUS.md's "move Claude off potato" note for the API-based
# version planned for later, and bin/crt-remote-claude-bridge.py's own
# header for the full design/threat-model reasoning). Empty by default:
# local tmux, byte-identical to before this change. Set
# CRT_CLAUDE_REMOTE_PORT to instead talk to a bridge server tunneled in
# on that LOCAL port (127.0.0.1 only -- potato never connects to mandark
# directly, mandark's own outbound ssh reverse-tunnels the port in).
CLAUDE_REMOTE_PORT = int(os.environ.get("CRT_CLAUDE_REMOTE_PORT", "0")) or None
SSH_CONNECT_TIMEOUT = os.environ.get("CRT_CLAUDE_REMOTE_SSH_TIMEOUT", "5")

# SSH-direct brain (2026-07-28), the successor to CLAUDE_REMOTE_PORT above.
# Set CRT_CLAUDE_SSH_HOST to an ssh alias (dexter) whose authorized_keys
# pins bin/crt-brain-shell.py as a forced command. Same two-verb protocol as
# the bridge -- only the transport differs, so everything downstream of
# capture_pane()/send_to_claude() is untouched.
#
# Why this replaced the tunnel: the reverse-tunnel shape existed because
# mandark was an intermittent laptop with no inbound path. dexter is always
# on and already runs sshd, so the tunnel bought nothing and cost a moving
# part that could drop silently. See DEXTER-MOVE.md section 2.
#
# Precedence is deliberate and checked in exactly one place (brain_mode()):
# ssh wins over port. Both set at once is a misconfiguration, not a
# fallback chain -- two brains would answer the same utterance.
CLAUDE_SSH_HOST = os.environ.get("CRT_CLAUDE_SSH_HOST", "").strip() or None
REPORTS_DIR = os.path.expanduser(os.environ.get("CRT_REPORTS_DIR", "~/reports/crt"))
REPO_DIR = os.path.expanduser(os.environ.get("CRT_REPO_DIR", "~/crt"))
QUESTIONS = os.environ.get("CRT_QUESTIONS_FILE", os.path.join(REPO_DIR, ".claude/QUESTIONS.md"))
TEST_SUITE = os.environ.get("CRT_TEST_SUITE", os.path.join(REPO_DIR, "tests/run_tests.sh"))
CALIBRATE_BIN = os.environ.get(
    "CRT_CALIBRATE_BIN", os.path.join(BIN_DIR, "crt-calibrate-display.py"))

# Lowered 3->1.5 2026-07-23 live tuning session (Zach on the mic, potato):
# the fixed idle-stability wait was most of the ~6s felt round-trip
# latency, independent of STT/whisper time. wait_for_claude_reply()'s
# grace-check (below) is the safety net against this lower threshold
# false-triggering mid-reply -- tune further by ear, this is a first
# retuning, not a final number.
CLAUDE_IDLE_SECS = float(os.environ.get("CRT_SECRETARY_IDLE_SECS", "1.5"))
CLAUDE_MAX_WAIT = float(os.environ.get("CRT_SECRETARY_MAX_WAIT", "120"))
CLAUDE_POLL = float(os.environ.get("CRT_SECRETARY_POLL", "1"))

# How many consecutive unreadable captures wait_for_claude_reply() tolerates
# before it stops waiting and says so. Not a guess that needs an ear: one or
# two misses is a tunnel hiccup worth riding out, and once the pane has been
# unreadable for CAPTURE_MISS_TOLERANCE * CLAUDE_POLL seconds there is
# nothing left to wait for -- burning the remaining CLAUDE_MAX_WAIT (120s)
# only delays the same answer.
CAPTURE_MISS_TOLERANCE = int(os.environ.get("CRT_SECRETARY_CAPTURE_MISSES", "3"))

# Window-switch on Claude escalation (2026-07-21, Zach's direct call):
# send_to_claude()/capture_pane() above type into and read from window
# 0's pane directly, regardless of which tmux window is actually
# DISPLAYED -- so with `book` as the boot-default window (crt-console.sh),
# a Claude exchange happened entirely invisibly to anyone just looking at
# the tube. `mono` (crt-monologue.sh, the pretty-print dialogue view) is
# the one window that actually shows Claude's replies -- switch there
# the moment a request escalates, and back to `book` once things go quiet
# (bin/crt-window-switcher.py, a separate background poller -- watching
# tmux's active window from inside crt-secretary.py itself doesn't work,
# since each utterance is a fresh short-lived process, gone long before
# an idle timeout could ever fire from within it) or on an explicit
# "book game"/"back to the game" voice command (the return_to_book_game
# playbook below).
BOOK_WINDOW = os.environ.get("CRT_BOOK_WINDOW_NAME", "book")
CLAUDE_VIEW_WINDOW = os.environ.get("CRT_CLAUDE_VIEW_WINDOW_NAME", "mono")
CLAUDE_ACTIVE_STATE = os.path.expanduser(
    os.environ.get("CRT_CLAUDE_ACTIVE_STATE", "~/.crt/claude-window-active.state"))


def switch_tmux_window(window_name):
    """Best-effort: a broken/absent tmux session must never crash the
    caller (e.g. this being run outside a real crt-console.sh session,
    like in tests or by hand)."""
    try:
        sh(["tmux", "select-window", "-t", "%s:%s" % (SESSION, window_name)])
    except OSError:
        pass


def touch_claude_active():
    """Records 'a Claude exchange just happened' for
    crt-window-switcher.py's idle-return check to read -- best-effort,
    same convention as every other logging write in this project (a
    broken write here shouldn't block the actual Claude routing)."""
    try:
        os.makedirs(os.path.dirname(CLAUDE_ACTIVE_STATE), exist_ok=True)
        with open(CLAUDE_ACTIVE_STATE, "w") as f:
            f.write(str(time.time()))
    except OSError:
        pass

SHORT_ANSWER_CHARS = 240  # above this, speak a one-line summary + print full text


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


# What a line that could not be spoken is prefixed with on the tube. Short,
# because it is competing for a 40-column screen with the words it is about.
UNSPOKEN_PREFIX = os.environ.get("CRT_UNSPOKEN_PREFIX", "(unspoken) ")


def speak(text, device="handset"):
    """Say something out loud. Returns True only if it was actually played.

    This used to discard crt-tts.py's exit status along with its stderr
    (sh() captures both), which mattered more here than anywhere: speech is
    this console's primary output channel, and EVERY honest-failure line the
    last three cycles added -- BRAIN_UNREACHABLE_LINE, REPLY_UNOBSERVED_LINE,
    route_claude_reply's "didn't catch a reply" -- is delivered through this
    function. A dead output device therefore silenced the reports about the
    silence, which is the worst possible place for this defect to sit."""
    if not (text or "").strip():
        # crt-tts.py exits 1 on empty input, which is correct there and is
        # not a fault to report here: nothing was meant to be said.
        return False
    r = sh(["python3", os.path.join(BIN_DIR, "crt-tts.py"), "--device", device, text])
    if r.returncode != 0:
        report_unspoken(text, r)
        return False
    return True


def report_unspoken(text, result):
    """A reply that could not be heard is not thereby a reply that has to be
    lost: put the words on the tube instead, where mono is already showing.

    Deliberately does NOT try to speak the bad news -- the one thing just
    established is that speaking does not work. It also never raises: this
    runs on the failure path of the failure path, and a traceback here would
    replace a lost sentence with a lost process."""
    detail = (result.stderr or "").strip().splitlines()
    detail = detail[-1].strip() if detail else "crt-tts.py exited %d" % result.returncode
    sys.stderr.write("[crt-secretary] SPOKE NOTHING (%s): %s\n" % (detail, text))
    try:
        sh([os.path.join(BIN_DIR, "crt-think.sh"),
            UNSPOKEN_PREFIX + text[:SHORT_ANSWER_CHARS]])
    except OSError:
        pass


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


# --- Playbook: book_game_stats -------------------------------------------
# Book Game's actual end-goal is STT training data (.claude/FOCUS.md's
# 2026-07-21 statement) -- this surfaces that progress on request
# ("how's the book game going", "trivia stats") the same locally-answered
# way `status`/`morning_report` already work, via
# bin/crt-book-game-stats.py's pure summarizer (zero Claude calls).
BOOK_GAME_STATS_TRIGGERS = (
    "book game stats", "how's the book game", "hows the book game",
    "trivia stats", "how's the training data", "hows the training data",
)
BOOK_GAME_STATS_BIN = os.environ.get(
    "CRT_BOOK_GAME_STATS_BIN", os.path.join(BIN_DIR, "crt-book-game-stats.py"))


def match_book_game_stats(text):
    return _matches_any(text, BOOK_GAME_STATS_TRIGGERS)


def handle_book_game_stats(text):
    if not os.path.exists(BOOK_GAME_STATS_BIN):
        speak("I don't have book game stats installed.")
        return "I don't have book game stats installed."
    r = sh(["python3", BOOK_GAME_STATS_BIN, "screen"])
    lines = [ln for ln in (r.stdout or "").splitlines() if ln.strip()]
    spoken = " ".join(lines) if lines else "No book game data yet."
    speak(spoken)
    full = sh(["python3", BOOK_GAME_STATS_BIN, "print-all"])
    print_full(full.stdout or "")
    return spoken


# --- Playbook: book_catalog --------------------------------------------
# BOOK-GAME.md's own vision line: the registry "documents the books for
# safe keeping... doubles as a personal library catalog, independent of
# the game." That catalog existed in books.db all along but had no way
# to actually be VIEWED until bin/crt-book-catalog.py -- distinct from
# book_game_stats above (STT-training numbers, not the catalog itself).
BOOK_CATALOG_TRIGGERS = (
    "my library", "my book library", "what books have i scanned",
    "book catalog", "list my books", "show my books",
)
BOOK_CATALOG_BIN = os.environ.get(
    "CRT_BOOK_CATALOG_BIN", os.path.join(BIN_DIR, "crt-book-catalog.py"))


def match_book_catalog(text):
    return _matches_any(text, BOOK_CATALOG_TRIGGERS)


def handle_book_catalog(text):
    if not os.path.exists(BOOK_CATALOG_BIN):
        speak("I don't have the book catalog installed.")
        return "I don't have the book catalog installed."
    r = sh(["python3", BOOK_CATALOG_BIN, "screen"])
    lines = [ln for ln in (r.stdout or "").splitlines() if ln.strip()]
    spoken = " ".join(lines) if lines else "Your library's empty so far."
    speak(spoken)
    full = sh(["python3", BOOK_CATALOG_BIN, "print-all"])
    print_full(full.stdout or "")
    return spoken


# --- Playbook: media --------------------------------------------------
# PARKING-LOT.md's second "primary product surface" job: "play the
# thing", "next", "pause" via handset voice. match_media() delegates the
# actual parsing to crt-media-player.py's parse_media_command() (its own
# pure function) instead of a separate trigger tuple here, so the two
# files can't drift on what counts as a media command.
def match_media(text):
    return media_player.parse_media_command(text) is not None


def handle_media(text):
    spoken = media_player.handle_media_command(text, MEDIA_BACKEND)
    if spoken is None:
        return None
    speak(spoken)
    return spoken


# --- Playbook: return_to_book_game --------------------------------------
# The explicit half of "switch back to book game on idle, or by command"
# (2026-07-21, Zach) -- crt-window-switcher.py handles the idle half.
# This is a locally-answered playbook like any other (no Claude call
# needed to just switch a tmux window), matched BEFORE the fallthrough
# path so it never itself triggers a switch TO the Claude view.
RETURN_TO_BOOK_GAME_TRIGGERS = (
    "book game", "back to the game", "back to book game",
    "switch to book game", "show me the book game",
)


def match_return_to_book_game(text):
    return _matches_any(text, RETURN_TO_BOOK_GAME_TRIGGERS)


def handle_return_to_book_game(text):
    switch_tmux_window(BOOK_WINDOW)
    return "back to the book game."


# Ordered: first match wins. See SUPERVISOR.md for what belongs here vs.
# what should stay a Claude call.
PLAYBOOKS = (
    ("status", match_status, handle_status),
    ("run_tests", match_run_tests, handle_run_tests),
    ("calibrate", match_calibrate, handle_calibrate),
    ("what_time", match_what_time, handle_what_time),
    ("morning_report", match_morning_report, handle_morning_report),
    # book_game_stats/book_catalog BEFORE return_to_book_game -- "book
    # game" (return_to_book_game's own trigger) is a substring of "book
    # game stats", so the more specific ones must get first shot or
    # they'd never fire (first match wins, see find_playbook below).
    ("book_game_stats", match_book_game_stats, handle_book_game_stats),
    ("book_catalog", match_book_catalog, handle_book_catalog),
    ("return_to_book_game", match_return_to_book_game, handle_return_to_book_game),
    ("media", match_media, handle_media),
)


def find_playbook(text):
    for name, match, action in PLAYBOOKS:
        if match(text):
            return name, action
    return None, None


# Remote-Claude wiring via a reverse-tunneled local socket, built
# 2026-07-23 (first cut -- an API-based version, for delegating to any
# VM rather than one specific tunnel, is the planned next step, see
# FOCUS.md). Deliberately NOT ssh-from-potato-to-mandark: mandark has no
# SSH server at all, and potato having any network path INTO mandark is
# a real vulnerability Zach flagged directly -- installing/exposing
# sshd on a personal dev laptop just so potato can reach in was
# rejected in favor of this instead. mandark's own crt-remote-claude-
# bridge.py binds 127.0.0.1-only (see that file) and mandark's own
# outbound ssh (already trusted, already working) reverse-tunnels that
# port to potato (`ssh -R <port>:localhost:<port> potato -N`) -- potato
# only ever talks to ITS OWN localhost, never to mandark directly, and
# mandark never accepts an unsolicited inbound connection. The bridge
# server's own protocol (two commands only: CAPTURE, SEND) is a much
# smaller surface than generic shell/SSH access would be, too.
#
# capture_pane()/send_to_claude() are the ONLY two functions that know
# whether Claude Code runs locally or remotely -- everything else in
# this file (playbooks, wait_for_claude_reply, earcon/composing-line
# hooks) stays completely agnostic. With CLAUDE_REMOTE_PORT unset (the
# default), these are byte-identical to the old local-only versions.
import socket as _socket


def _bridge_request(command, port, timeout=None):
    """One request, one response, newline-terminated, then close --
    dead simple by design (this is the whole protocol). Returns "" on
    any failure (timeout, connection refused because the tunnel/bridge
    isn't up) -- same tolerant-degrade posture as every other
    best-effort call in this file, never raises up into the capture
    loop."""
    timeout = timeout if timeout is not None else float(SSH_CONNECT_TIMEOUT)
    try:
        with _socket.create_connection(("127.0.0.1", port), timeout=timeout) as s:
            s.sendall((command + "\n").encode("utf-8"))
            s.shutdown(_socket.SHUT_WR)
            chunks = []
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
            return b"".join(chunks).decode("utf-8", errors="replace")
    except OSError:
        return ""


def _ssh_request(command, host, timeout=None):
    """One request line to the brain host over ssh, one response body back.

    The ssh sibling of _bridge_request(), and deliberately the same
    contract: returns "" on ANY failure (host down, key refused, ssh
    missing), never raises into the capture loop. Callers already treat ""
    as "never reached the brain", and that reading stays correct here --
    an unreachable dexter and a dropped tunnel are the same fact to potato.

    Note there is no shell on the far side: sshd runs crt-brain-shell as a
    forced command and this text arrives on ITS stdin, so `command` is data,
    not something a remote shell parses. That is why nothing here quotes or
    escapes -- there is no shell to escape for.
    """
    timeout = timeout if timeout is not None else float(SSH_CONNECT_TIMEOUT)
    argv = ["ssh", "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=%d" % max(1, int(float(SSH_CONNECT_TIMEOUT))),
            host]
    try:
        r = subprocess.run(argv, input=command + "\n", capture_output=True,
                           text=True, timeout=timeout + CLAUDE_MAX_WAIT)
    except (subprocess.TimeoutExpired, OSError):
        return ""
    # Non-zero rc with a body still carries meaning: crt-brain-shell exits 1
    # on a refused SEND but writes "ERR <detail>" first, and the caller
    # needs that detail to tell "tmux refused" from "never got there".
    return r.stdout


def brain_mode():
    """Where this console's brain lives: "ssh", "port", or "local".

    One function so the precedence question is answered once. It used to be
    an `if CLAUDE_REMOTE_PORT:` repeated at each call site, which was fine
    with two modes and would rot with three.
    """
    if CLAUDE_SSH_HOST:
        return "ssh"
    if CLAUDE_REMOTE_PORT:
        return "port"
    return "local"


def capture_pane():
    """The pane's text, or None if it could not be read (2026-07-25).

    None vs. "" is the whole point. Both paths used to collapse failure into
    "", which wait_for_claude_reply() then diffed against as if it were a
    real, empty pane -- see its docstring for what that cost. On the remote
    path an empty response IS the failure signal: _bridge_request() returns
    "" for a dropped tunnel or a stopped bridge, and mandark's own
    capture_pane() returns "" when its tmux target is gone. A live Claude
    Code pane is never legitimately empty, so nothing is lost by refusing to
    trust an empty one, and no bridge-side change is needed to tell them
    apart."""
    mode = brain_mode()
    if mode == "ssh":
        return _ssh_request("CAPTURE", CLAUDE_SSH_HOST) or None
    if mode == "port":
        return _bridge_request("CAPTURE", CLAUDE_REMOTE_PORT) or None
    if LOCAL_PANE_IS_IDLE_FACE:
        # The idle face is not an unreadable pane -- it reads perfectly, and
        # that is the danger. Its frames CHANGE on their own (the potato
        # breathes, and since 4f7c17e its caption moves every 8s), so
        # wait_for_claude_reply() would watch it "grow" and hand back the
        # caption as Claude's answer, which route_claude_reply() then speaks
        # into the earpiece. None is the honest reading: there is no brain
        # here to have a pane. send_to_claude() refuses first, so in practice
        # nothing gets this far -- this is the belt to that brace.
        return None
    r = sh(["tmux", "capture-pane", "-t", "%s:%s" % (SESSION, PANE), "-p", "-S", "-200"])
    return r.stdout if r.returncode == 0 else None


def send_to_claude(text):
    """Deliver one utterance to Claude. Returns True only if it landed.

    Both halves used to discard their result (2026-07-25). On the remote
    path that mattered most: _bridge_request() returns "" on ANY socket
    failure, so a dropped reverse tunnel or a dead bridge on mandark made
    this a silent no-op -- and handle() below went on to fire the
    "thinking" earcon and sit through the full idle wait polling a socket
    that was never going to answer, before telling the user "I sent that
    to Claude but didn't catch a reply -- check the screen", which is
    wrong twice over: nothing was sent, and the screen it points at is
    blank precisely because the brain isn't there. FOCUS.md's current top
    priority names tunnel drops as the thing to watch for; this is what
    makes one observable instead of looking like a quiet Claude."""
    mode = brain_mode()
    if mode == "ssh":
        # Same one-line protocol as the socket path, same reason: whisper
        # output is one line, but strip defensively so a stray newline
        # cannot desync the request.
        reply = _ssh_request("SEND " + text.replace("\n", " "), CLAUDE_SSH_HOST)
        if reply.strip() == "OK":
            return True
        note = reply.strip() or ("no response from the brain host %r -- "
                                 "dexter unreachable, or its key was refused"
                                 % CLAUDE_SSH_HOST)
        log_brain_unreachable(text, note)
        return False
    if mode == "port":
        # newline-terminated single-line protocol -- a real utterance
        # never legitimately contains one (whisper output is one line),
        # but strip defensively so a stray one can't desync the protocol.
        reply = _bridge_request("SEND " + text.replace("\n", " "), CLAUDE_REMOTE_PORT)
        if reply.strip() == "OK":
            return True
        # "" = never reached the bridge; "ERR ..." = reached it and tmux
        # refused. Both mean not delivered; keep the distinction in the log.
        note = reply.strip() or "no response from the bridge on port %s" % CLAUDE_REMOTE_PORT
        log_brain_unreachable(text, note)
        return False
    if LOCAL_PANE_IS_IDLE_FACE:
        # The local route with no local brain: the idle-lean layout after a
        # plain `crt-mandark.sh off` (its own help: "keep the brain
        # local/onsite (or none)"). tmux would ACCEPT these keys -- the pane
        # is real, it just holds the potato -- so the delivery check below
        # cannot catch this; the utterance would be typed onto the console's
        # own face and answered by a screensaver. This is the third way an
        # utterance never leaves the building, and it gets the same honest
        # line as a dropped tunnel because it is the same fact.
        log_brain_unreachable(text, IDLE_FACE_PANE_REPORT)
        return False
    r = sh(["tmux", "send-keys", "-t", "%s:%s" % (SESSION, PANE), "-l", text])
    if r.returncode != 0:
        log_brain_unreachable(text, (r.stderr or "").strip() or "tmux send-keys failed")
        return False
    r = sh(["tmux", "send-keys", "-t", "%s:%s" % (SESSION, PANE), "Enter"])
    if r.returncode != 0:
        log_brain_unreachable(text, (r.stderr or "").strip() or "tmux Enter failed")
        return False
    return True


# Claude Code's own TUI chrome that a raw pane-line diff cannot tell apart
# from real reply content (2026-07-28, live-confirmed on potato the first
# time a real remote reply was captured end-to-end): the echoed prompt
# ("> what you just said"), the bottom status bar ("-- INSERT --", "auto
# mode on..."), bare box-drawing border lines, and the spinner line
# ("* Baked for 2s"). None of these are ever the actual answer.
_PANE_SPINNER_CHARS = "*+~"
_PANE_BORDER_RE = re.compile(r"^[\s\-_=]*$")
_PANE_STATUS_RE = re.compile(
    r"^(--\s*INSERT\s*--|auto mode on\b|.*for agents\s*)", re.IGNORECASE)


def clean_claude_pane_reply(lines):
    """Filter a raw pane-diff line list down to just Claude's answer text.

    Best-effort, same posture as the diff it cleans up (see
    wait_for_claude_reply's docstring) -- not a real terminal parser, just
    enough pattern-matching to stop known chrome from being spoken or
    printed as if it were the answer. Safe to run on any line list,
    including one with no chrome in it at all (nothing here matches
    ordinary reply text)."""
    out = []
    for raw in lines:
        s = raw.strip()
        if not s:
            continue
        # box-drawing border lines (potato's SSH/tmux capture renders these
        # in plain ASCII, not unicode box-drawing, hence the dash/equals
        # check above rather than a unicode char class)
        if set(s) <= set("-_=─│┌┐└┘╭╮╯╰"):
            continue
        if _PANE_STATUS_RE.match(s):
            continue
        if s[0] in "❯":  # the echoed prompt line ("> ..."/❯ ...): never the reply
            continue
        if s[0] in "●✦✴✻✶✺" or s[0] in _PANE_SPINNER_CHARS:
            # answer marker ("* " / "● ") or spinner line ("✦ Baked for 2s")
            s = s.lstrip("●✦✴✻✶✺" + _PANE_SPINNER_CHARS).strip()
            if s.startswith("»"):  # "● » " marker seen live 2026-07-28
                s = s[1:].strip()
            if not s or re.match(r"^Baked for \d", s, re.IGNORECASE):
                continue
        out.append(s)
    return "\n".join(out).strip()


def wait_for_claude_reply(before_snapshot, on_partial=None):
    """Poll capture-pane until it stops changing for CLAUDE_IDLE_SECS, or
    CLAUDE_MAX_WAIT elapses. Returns (reply, status): the pane lines added
    since before_snapshot (best-effort -- a real terminal UI has spinners/
    prompt redraws that a plain diff can't fully distinguish from genuine new
    content; this is a first draft, not a robust terminal parser), and "ok"
    or "unobserved".

    "unobserved" means the send landed but this function could not watch the
    answer arrive, which is NOT the same as Claude having nothing to say
    (2026-07-25). It used to be, in two measured ways -- both with
    capture_pane() collapsing failure into "":

      - **No baseline.** handle()'s `before` capture failing, then the pane
        reading fine, made every line on it "new". A 200-line scrollback came
        back as the reply, so route_claude_reply() spoke the first 160
        characters of an old exchange into the earpiece and handed the rest
        to print_full() -- 200 lines onto a Phomemo thermal receipt printer.
      - **A drop after the send.** The tunnel going down mid-answer made
        every later capture "", so the diff came out empty and the console
        said "I sent that to Claude but didn't catch a reply -- check the
        screen" -- the same sentence, and the same two lies, that
        send_to_claude()'s own fix earlier today was about. FOCUS.md's top
        priority names tunnel drops specifically; this is the half of that
        failure that happens after the utterance is already gone.

    A failed capture is also no longer mistaken for pane growth (it used to
    reset the stability timer and fire on_partial, putting "...composing" on
    the tube on the way to reporting a reply that was never seen). Transient
    misses are tolerated up to CAPTURE_MISS_TOLERANCE consecutive polls,
    because a hiccup on the tunnel should not end a real wait; past that
    there is nothing to wait for, and returning early beats spending
    CLAUDE_MAX_WAIT to reach the same answer.

    Grace-check (added 2026-07-23 alongside lowering CLAUDE_IDLE_SECS 3->1.5):
    right before finalizing on an apparent idle break, one extra poll
    confirms the pane really has gone quiet. If it grew during that grace
    window, the stability timer resets and waiting resumes instead of
    returning a reply that got cut off mid-thought -- a lower idle
    threshold means "looks done" fires more eagerly, so this is the cheap
    insurance against acting on a false one, without needing to re-open
    an already-returned/spoken reply and append to it after the fact.

    on_partial (optional): called (best-effort, exceptions swallowed) the
    first time the pane is observed to grow after send_to_claude -- a
    foothold for a future streaming/'thinking' preview in window 1 (see
    FOCUS.md's grey-then-white-overwrite idea), not a full implementation
    of it. No-op by default."""
    if before_snapshot is None:
        return "", "unobserved"
    deadline = time.time() + CLAUDE_MAX_WAIT
    last = capture_pane()
    if last is None:
        last = before_snapshot
    stable_since = time.time()
    partial_fired = False
    misses = 0
    while time.time() < deadline:
        time.sleep(CLAUDE_POLL)
        now_snap = capture_pane()
        if now_snap is None:
            misses += 1
            if misses >= CAPTURE_MISS_TOLERANCE:
                return "", "unobserved"
            continue
        misses = 0
        if now_snap != last:
            last = now_snap
            stable_since = time.time()
            if on_partial and not partial_fired:
                partial_fired = True
                try:
                    on_partial(now_snap)
                except Exception:
                    pass
        elif time.time() - stable_since >= CLAUDE_IDLE_SECS:
            time.sleep(CLAUDE_POLL)  # grace-check, see docstring
            confirm_snap = capture_pane()
            if confirm_snap is None:
                misses += 1
                if misses >= CAPTURE_MISS_TOLERANCE:
                    return "", "unobserved"
                continue
            if confirm_snap != last:
                last = confirm_snap
                stable_since = time.time()
                continue
            break

    before_lines = before_snapshot.splitlines()
    after_lines = last.splitlines()
    # Crude diff: new trailing lines not present in the before-snapshot's
    # tail. Good enough as a first cut; a real implementation should key off
    # Claude Code's actual prompt markers instead of pure line-set diffing.
    new_lines = [ln for ln in after_lines if ln not in before_lines]
    reply = clean_claude_pane_reply(new_lines)
    return reply.strip(), "ok"


# Does anything else put Claude's reply on window 1? (2026-07-25)
#
# With the brain LOCAL, yes: bin/crt-claude-bridge.py tails Claude Code's own
# session transcript under ~/.claude/projects/ and forwards its marked lines
# to thoughts.log, which is what window 1 renders. Mirroring here too would
# double every reply -- and every reply at all, once that bridge's
# no-marked-line fallback kicks in.
#
# With the brain on mandark (CRT_CLAUDE_REMOTE_PORT, potato's live config
# since 2026-07-23) that transcript is on mandark. potato's bridge window
# tails a directory the remote Claude never writes to, so it forwards
# nothing, and NOTHING else on the success path writes the answer down:
# handle() switches the tube to `mono` to show the exchange, log_user_thought
# puts "[you] ..." there, the earpiece says the answer, and the screen the
# console just switched to stays exactly as it was. That is the same blank
# window _report_bad_news() was written to avoid on the failure path -- the
# migration moved the brain and left this half behind, the same way it left
# the scan path behind (0fc83a6) and the CTL file behind (fe46ac1).
MIRROR_REPLY_TO_TUBE = CLAUDE_REMOTE_PORT is not None


def show_reply_line(text):
    """Put what the earpiece just said onto window 1, via the same
    crt-think.sh -> thoughts.log path show_composing_line() and
    _report_bad_news() already use. Best-effort, like every other write to
    that log: a broken mirror must not cost the person the spoken answer.

    Mirrors what is SPOKEN, not the full reply: window 1 is 40x15 and fades
    from the top, and dumping a long answer there is precisely the flooding
    crt-claude-bridge.py's marker filter exists to prevent. The long case is
    already handled -- it goes to the printer."""
    if not MIRROR_REPLY_TO_TUBE:
        return
    try:
        sh([os.path.join(BIN_DIR, "crt-think.sh"), text])
    except OSError:
        pass


def route_claude_reply(reply):
    if not reply:
        line = "I sent that to Claude but didn't catch a reply -- check the screen."
        show_reply_line(line)
        speak(line)
        return
    clean = re.sub(r"\s+", " ", reply).strip()
    if len(clean) <= SHORT_ANSWER_CHARS:
        show_reply_line(clean)
        speak(clean)
    else:
        summary = clean[:160].rsplit(" ", 1)[0] + "... printing the rest."
        show_reply_line(summary)
        speak(summary)
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


BRAIN_LOG = os.path.expanduser(
    os.environ.get("CRT_BRAIN_LOG", "~/.crt/brain-unreachable.log"))

# Short on purpose: this is spoken through a handset earpiece, and it has
# to be distinguishable BY EAR from route_claude_reply()'s "didn't catch a
# reply" line -- that one means Claude was reached and said nothing useful,
# this one means the utterance never left the building.
BRAIN_UNREACHABLE_LINE = os.environ.get(
    "CRT_BRAIN_UNREACHABLE_LINE",
    "I can't reach my brain right now, so that didn't go anywhere. Try again in a moment.")

# The third of three outcomes, and it needs its own line for the same reason
# the second one does. This one means the utterance DID land -- so it must not
# claim otherwise (BRAIN_UNREACHABLE_LINE's job) and must not blame Claude for
# being quiet (route_claude_reply's job). Deliberately does not say "check the
# screen": whether the answer is on the tube is exactly what this outcome
# doesn't know.
REPLY_UNOBSERVED_LINE = os.environ.get(
    "CRT_REPLY_UNOBSERVED_LINE",
    "I sent that to Claude, but I lost my view of the answer partway through.")


def log_brain_unreachable(text, detail, verdict="NOT DELIVERED"):
    """Every utterance the brain didn't answer, with why, so a tunnel drop
    leaves evidence instead of just feeling like a quiet night. Same
    best-effort posture as log_fallthrough: a broken log write must never
    become the reason the user hears nothing.

    verdict is not decoration. The unobserved-reply caller DID deliver its
    utterance, and a line reading "NOT DELIVERED (sent, but the pane went
    unreadable)" contradicts itself -- which is the exact class of
    confidently-wrong diagnostic this project keeps finding in its own
    tooling (see crt-mandark.sh's port, 26cd8df)."""
    try:
        d = os.path.dirname(BRAIN_LOG)
        if d:
            os.makedirs(d, exist_ok=True)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(BRAIN_LOG, "a") as f:
            f.write("%s  %s  [%s]  %s\n" % (ts, verdict, detail, text))
    except OSError:
        pass
    sys.stderr.write("[crt-secretary] %s (%s): %s\n" % (verdict, detail, text))


def _report_bad_news(line):
    """Say so, out loud, immediately. bin/crt-wake-router.py's own design
    note for the `none` route already states the rule this implements --
    "the caller should give a short honest earcon/line ... NOT silence" --
    it just had no caller on this path until now."""
    play_earcon("oops")
    # handle() has already switched the tube to the `mono` window by the
    # time this runs, and mono only ever shows what reaches thoughts.log --
    # without this the screen we just switched to would sit blank, which is
    # the same silence in a different medium.
    try:
        sh([os.path.join(BIN_DIR, "crt-think.sh"), line])
    except OSError:
        pass
    speak(line)


def report_brain_unreachable():
    """The utterance never left the building."""
    _report_bad_news(BRAIN_UNREACHABLE_LINE)


def report_reply_unobserved(text):
    """The utterance landed; the answer to it could not be watched arrive.
    Logged to the same place as an undelivered one -- a tunnel that drops
    mid-answer and one that drops before the send are the same fault, and
    ~/.crt/brain-unreachable.log is where the evidence for it lives."""
    log_brain_unreachable(
        text, "the pane went unreadable before a reply was seen",
        verdict="DELIVERED, REPLY UNOBSERVED")
    _report_bad_news(REPLY_UNOBSERVED_LINE)


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
    if not send_to_claude(text):
        # Nothing was sent, so there is no call to record. Recording one
        # anyway would have booked an unconfirmed miss against this
        # utterance shape every time the tunnel was down -- teaching the
        # confidence model that the local playbook disagrees with Claude,
        # from an exchange that never happened.
        return
    reply, status = wait_for_claude_reply(before)
    if status != "ok":
        # Same reasoning one step later: an answer nobody could read is not
        # an answer that disagreed. Scoring it would poison the same state.
        return
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


# Same toggle crt-stt-solo.py already exposes (CRT_EARCON_DEVICE), read
# here too (2026-07-28) -- this file's play_earcon() previously never
# passed --device at all, so it silently fell through crt-earcon.sh's
# `${DEVICE:-default}` case to the system default ALSA device regardless
# of what the console's other earcons were routed to. One knob, both call
# sites now honor it.
EARCON_DEVICE = os.environ.get("CRT_EARCON_DEVICE", "handset")


def play_earcon(name):
    """Fire-and-forget (Popen, not sh()/run) -- an earcon must never add
    its own latency on top of the real wait it's meant to paper over.

    stderr is inherited rather than discarded (2026-07-25): crt-earcon.sh
    says nothing on success, so this is free when it works, and since
    nothing waits on the exit status its stderr is the only way a chime
    that never sounded can be noticed at all. The "oops" earcon in
    _report_bad_news is the one that matters -- an inaudible apology for an
    inaudible answer."""
    try:
        subprocess.Popen(
            [os.path.join(BIN_DIR, "crt-earcon.sh"), name, "--device", EARCON_DEVICE],
            stdout=subprocess.DEVNULL,
        )
    except OSError:
        pass


def show_composing_line(_pane_snapshot):
    """wait_for_claude_reply's on_partial hook: fires once, the first time
    the pane is observed to grow after send_to_claude -- a cheap scaffold
    toward the real streaming/'thinking' preview idea (grey partial text,
    overwritten by the final flavorful line), not that feature itself.
    Reuses the same crt-think.sh -> thoughts.log -> window 1 path
    show_filler_line() already uses, just triggered by real pane growth
    instead of a canned speculative line."""
    try:
        sh([os.path.join(BIN_DIR, "crt-think.sh"), "...composing"])
    except OSError:
        pass


def show_filler_line():
    """PARKING-LOT.md's speculative/optimistic-response idea: an instant,
    content-free acknowledgment shown via crt-think.sh (crt-monologue.sh
    already tails and displays that log) the moment a request is about to
    sit through wait_for_claude_reply's real round-trip (up to
    CLAUDE_MAX_WAIT seconds) -- gives an immediate "it's alive" feel
    instead of the screen going silent during the wait. Best-effort: a
    broken crt-think.sh call must never block the real Claude routing
    that follows it."""
    try:
        sh([os.path.join(BIN_DIR, "crt-think.sh"), speculate.pick_filler_line()])
    except OSError:
        pass


def handle(text):
    _, action = find_playbook(text)
    if action:
        confidence_route(text, action)
        return

    log_fallthrough(text)
    if SPECULATE_ENABLED:
        show_filler_line()
    switch_tmux_window(CLAUDE_VIEW_WINDOW)
    touch_claude_active()
    before = capture_pane()
    if not send_to_claude(text):
        # Before the earcon, deliberately: "thinking" is a promise that an
        # answer is coming, and sitting through CLAUDE_IDLE_SECS of polling
        # a dead socket only delays the bad news.
        report_brain_unreachable()
        return
    play_earcon("thinking")
    reply, status = wait_for_claude_reply(before, on_partial=show_composing_line)
    touch_claude_active()  # the reply itself also counts as recent activity
    if status != "ok":
        report_reply_unobserved(text)
        return
    route_claude_reply(reply)


def main():
    text = " ".join(sys.argv[1:]).strip() or sys.stdin.read().strip()
    if not text:
        sys.stderr.write("usage: crt-secretary.py <text>\n")
        sys.exit(2)
    handle(text)


if __name__ == "__main__":
    main()
