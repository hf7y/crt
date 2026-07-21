#!/usr/bin/env python3
# Auto-returns tmux focus to the `book` window once a Claude exchange on
# the `mono` window has gone idle -- the other half of "switch back to
# book game on idle, or by command" (2026-07-21, Zach's direct ask).
# crt-secretary.py's handle() switches TO `mono` (and touches
# CLAUDE_ACTIVE_STATE) the moment a request escalates to Claude, and the
# `return_to_book_game` playbook handles the explicit voice-command half
# -- this script is the idle half, and has to be a SEPARATE background
# process: crt-secretary.py itself runs as a fresh short-lived process
# per utterance (Popen'd from crt-stt-solo.py), gone long before any
# idle timeout could fire from inside it.
#
# Deliberately conservative about WHEN to switch back: only when the
# currently-DISPLAYED tmux window is actually `mono` (never yank focus
# away from something else someone deliberately switched to by hand,
# e.g. mid-calibration or checking `bookanswer`'s pane) AND the last
# Claude activity is more than IDLE_SECS old.
#
# NOT an AI call -- pure local tmux queries + a state-file read, same
# "90% offline supervisor" spirit as everything else in this project.
#
# STATUS: NOT hardware-verified. should_return_to_book_game() is a pure
# function covered by tests/test_window_switcher.py; the real tmux
# polling loop has never been run against a live session.
#
# Usage: crt-window-switcher.py   (run as its own background tmux window)
# Env:
#   CRT_TMUX_SESSION (default claude)
#   CRT_BOOK_WINDOW_NAME (default book), CRT_CLAUDE_VIEW_WINDOW_NAME (default mono)
#   CRT_CLAUDE_ACTIVE_STATE (default ~/.crt/claude-window-active.state)
#   CRT_WINDOW_SWITCHER_IDLE_SECS (default 30) -- how long mono stays
#     focused after the last Claude activity before auto-returning
#   CRT_WINDOW_SWITCHER_POLL_SECS (default 2)
import os
import subprocess
import time

SESSION = os.environ.get("CRT_TMUX_SESSION", "claude")
BOOK_WINDOW = os.environ.get("CRT_BOOK_WINDOW_NAME", "book")
CLAUDE_VIEW_WINDOW = os.environ.get("CRT_CLAUDE_VIEW_WINDOW_NAME", "mono")
CLAUDE_ACTIVE_STATE = os.path.expanduser(
    os.environ.get("CRT_CLAUDE_ACTIVE_STATE", "~/.crt/claude-window-active.state"))
IDLE_SECS = float(os.environ.get("CRT_WINDOW_SWITCHER_IDLE_SECS", "30"))
POLL_SECS = float(os.environ.get("CRT_WINDOW_SWITCHER_POLL_SECS", "2"))


def read_claude_active_state(path=None):
    """Pure-ish (only reads a file): the last time crt-secretary.py
    touched CLAUDE_ACTIVE_STATE, or None if it's missing/malformed --
    treated as "no recent activity", never a crash."""
    path = path or CLAUDE_ACTIVE_STATE
    try:
        with open(path) as f:
            return float(f.read().strip())
    except (OSError, ValueError):
        return None


def should_return_to_book_game(active_window, last_active, now, idle_secs, claude_view_window):
    """Pure function: the whole decision. Only ever return True when
    `mono` (or whatever CLAUDE_VIEW_WINDOW is configured as) is the
    window CURRENTLY DISPLAYED -- if someone's switched elsewhere by
    hand, this never yanks focus away from that. `last_active is None`
    (state file missing/never written) means no known Claude activity,
    so there's nothing to time out from -- don't switch."""
    if active_window != claude_view_window:
        return False
    if last_active is None:
        return False
    return (now - last_active) >= idle_secs


def get_active_window(session=None):
    session = session or SESSION
    try:
        r = subprocess.run(
            ["tmux", "display-message", "-p", "-t", session, "#{window_name}"],
            capture_output=True, text=True,
        )
        return r.stdout.strip() if r.returncode == 0 else None
    except OSError:
        return None


def switch_to_book_window():
    try:
        subprocess.run(["tmux", "select-window", "-t", "%s:%s" % (SESSION, BOOK_WINDOW)])
    except OSError:
        pass


def main():
    while True:
        time.sleep(POLL_SECS)
        active = get_active_window()
        last_active = read_claude_active_state()
        if should_return_to_book_game(active, last_active, time.time(), IDLE_SECS, CLAUDE_VIEW_WINDOW):
            switch_to_book_window()


if __name__ == "__main__":
    main()
