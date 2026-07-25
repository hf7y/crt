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
# Claude activity is more than IDLE_SECS old AND this process has not
# already returned from THAT SAME exchange (2026-07-25 -- without the
# third condition, walking up and pressing prefix+1 to read window 1 an
# hour later bounced you back to `book` inside one poll, forever, because
# an ancient last_active passes an idle test just as well as a recent one
# does. An exchange is spent once it has been returned from; only
# crt-secretary.py touching the state file again re-arms this).
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
#   CRT_THOUGHT_LOG (default ~/.crt/thoughts.log) -- where a failed
#     select-window says so, since window 1 is what it leaves you on
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
THOUGHT_LOG = os.path.expanduser(os.environ.get("CRT_THOUGHT_LOG", "~/.crt/thoughts.log"))


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


def should_return_to_book_game(active_window, last_active, now, idle_secs,
                               claude_view_window, returned_from=None):
    """Pure function: the whole decision. Only ever return True when
    `mono` (or whatever CLAUDE_VIEW_WINDOW is configured as) is the
    window CURRENTLY DISPLAYED -- if someone's switched elsewhere by
    hand, this never yanks focus away from that. `last_active is None`
    (state file missing/never written) means no known Claude activity,
    so there's nothing to time out from -- don't switch.

    `returned_from` is the last_active value this process has ALREADY
    returned to `book` from, and it closes a hole in "never yank focus
    away from something someone chose by hand" (2026-07-25): that
    protection only ever covered windows OTHER than mono. Window 1 is the
    one background window CLAUDE.md says is meant to be looked at, and
    every honest-failure line this project writes lands there. Reaching it
    with prefix+1 an hour after the last exchange used to bounce straight
    back to `book` within one poll -- last_active was ancient, so the idle
    test was trivially true and stayed true forever. An exchange that has
    already been returned from is spent; only a fresh touch of the state
    file (a real new escalation, crt-secretary.py's touch_claude_active)
    re-arms the auto-return."""
    if active_window != claude_view_window:
        return False
    if last_active is None:
        return False
    if returned_from is not None and last_active == returned_from:
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


def select_window(target):
    """Move tmux's focus to `target` ('session:window'). Returns
    (ok, detail). The old version discarded tmux's exit status and its
    stderr, so a select-window that could never work -- no such window,
    session renamed, the server gone -- looked exactly like one that did,
    and the only symptom was a tube that stayed on `mono` forever. Same
    distinction the rest of this console has been learning to make: 'it did
    not happen' is not 'nothing to do'.

    Generic since 2026-07-25: crt-book-console.py brings the `book` window
    to the front when a scan lands on it, and hands the tube back to the
    idle face afterwards, and a second copy of this exit-status handling in
    that file would be one more place to forget it."""
    try:
        r = subprocess.run(["tmux", "select-window", "-t", target],
                           capture_output=True, text=True)
    except OSError as e:
        return False, "could not run tmux: %s" % e
    if r.returncode != 0:
        detail = next((ln.strip() for ln in reversed((r.stderr or "").splitlines())
                       if ln.strip()), "tmux exited %d" % r.returncode)
        return False, detail
    return True, None


def switch_to_book_window():
    """This loop's own move: back to `book` after an idle Claude exchange."""
    return select_window("%s:%s" % (SESSION, BOOK_WINDOW))


def switch_failure_report(target, detail):
    """Pure string builder, so the wording is testable without a tmux
    server. Short: it lands on a 40-column tube."""
    return "[!] stuck on this window -- can't reach %s: %s" % (target, detail)


def announce(line, log_path=None):
    """Best-effort append to the log crt-monologue.py renders on window 1
    -- which is `mono` itself, the very window a failed switch leaves you
    stranded on. Same convention as every other logging write here: a
    broken log write must never stop the polling loop."""
    log_path = log_path or THOUGHT_LOG
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a") as f:
            f.write("%s  %s\n" % (time.strftime("%H:%M:%S"), line))
    except OSError:
        pass


def main():
    returned_from = None
    reported = None
    while True:
        time.sleep(POLL_SECS)
        active = get_active_window()
        last_active = read_claude_active_state()
        if not should_return_to_book_game(active, last_active, time.time(),
                                          IDLE_SECS, CLAUDE_VIEW_WINDOW, returned_from):
            continue
        ok, detail = switch_to_book_window()
        if ok:
            # Only now is this exchange spent. Marking it before the switch
            # succeeded would turn one failed tmux call into a permanent
            # stop, which is the failure this loop exists to avoid.
            returned_from, reported = last_active, None
            continue
        # Once per distinct cause, not once per poll: this loop wakes every
        # two seconds, and window 1 fades the person's own words out from
        # the top.
        if detail != reported:
            reported = detail
            line = switch_failure_report("%s:%s" % (SESSION, BOOK_WINDOW), detail)
            print(line)
            announce(line)


if __name__ == "__main__":
    main()
