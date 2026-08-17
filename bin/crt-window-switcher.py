#!/usr/bin/env python3
# Auto-returns tmux focus to the `book` window once a Claude exchange on
# the `mono` window has gone idle -- the other half of "switch back to
# book game on idle, or by command" (2026-07-21, Zach's direct ask).
# crt-secretary.py's handle() switches TO `mono` (and touches
#   [rest: vault:crt/header-archaeology-20260817.md]
import os
import subprocess
import time

SESSION = os.environ.get("CRT_TMUX_SESSION", "claude")
BOOK_WINDOW = os.environ.get("CRT_BOOK_WINDOW_NAME", "book")
CLAUDE_VIEW_WINDOW = os.environ.get("CRT_CLAUDE_VIEW_WINDOW_NAME", "mono")
# Same var, same meaning as crt-book-console.py's CRT_IDLE_FACE_WINDOW
# (2026-07-28): under the idle-lean layout (CRT_NO_IDLE_CLAUDE=1) the
# real resting state is the screensaver, not `book`. Landing on `book`
# instead left the console stuck there -- crt-book-console.py's own
#   [rest: vault:crt/header-archaeology-20260817.md]
IDLE_FACE_WINDOW = os.environ.get("CRT_IDLE_FACE_WINDOW", "").strip()
RETURN_WINDOW = IDLE_FACE_WINDOW or BOOK_WINDOW
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
    """This loop's own move after an idle Claude exchange: back to the
    real idle face (screensaver) when the idle-lean layout says there is
    one, else the historical `book` target."""
    return select_window("%s:%s" % (SESSION, RETURN_WINDOW))


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
            line = switch_failure_report("%s:%s" % (SESSION, RETURN_WINDOW), detail)
            print(line)
            announce(line)


if __name__ == "__main__":
    main()
