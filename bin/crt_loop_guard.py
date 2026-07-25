#!/usr/bin/env python3
# One reason a background window on this console goes quiet: its loop body
# raised once and the whole `while True` ended.
#
# crt-console.sh runs eight long-lived Python windows and wraps each in
# `; exec bash`, so a dead loop does not close its window -- it leaves a
# shell prompt sitting where the console's face used to be, and nothing
# anywhere says so. Cycles 9 and 10 (2026-07-25) each filed this and each
# deferred it to "the supervisor question". This module is the half of that
# question which does NOT need a supervisor: an exception that a *later*
# iteration would have been fine after should not end the loop at all.
#
# Split it that way and the two halves are genuinely different jobs:
#   - transient, per-iteration: one sqlite hiccup, one malformed row, one
#     ENOSPC on the SD card -> skip that iteration, SAY SO, keep going.
#     That is this file, and it needs nothing but the process itself.
#   - the process is gone (killed, or raised outside the loop) -> only
#     something outside it can notice. Still ranked-backlog item 8, [hw].
#
# WHAT IT DELIBERATELY DOES NOT DO:
#   - It does not sleep. Pacing stays where the caller can see it; a guard
#     that quietly inserted a backoff would make a hot loop look healthy.
#     The caller's loop must already have its own poll/sleep -- all four
#     current callers do (blocking tail, POLL_SECS, MERGE_INTERVAL_SECS).
#   - It does not catch BaseException. KeyboardInterrupt and SystemExit
#     pass straight through, so Ctrl-C and a deliberate stop still stop
#     (the distinction cycle 2 drew for crt-stt-solo.py's own shutdown).
#   - It does not guard the *iterator* of a `for` loop, only the body. A
#     generator that raises while producing the next item still ends the
#     loop; wrap the iteration itself if that matters.
#
# Reporting follows the convention the rest of bin/ already settled on:
# once per distinct cause (window 1 fades the person's own words off the
# top, so a repeating fault must not own the screen), on stdout AND on
# ~/.crt/thoughts.log, and a recovery line naming how many were swallowed
# so nothing this suppressed is left without a trace.
#
# Env:
#   CRT_THOUGHT_LOG (default ~/.crt/thoughts.log) -- same channel every
#     other honest-failure line in this project goes to.
#   CRT_LOOP_GUARD_TRACEBACK (default 0) -- 1 to also dump full frames to
#     the window's own pane. Off by default because one of these windows
#     (`book`) has the tube itself for a pane.
import os
import time
import traceback

THOUGHT_LOG = os.path.expanduser(os.environ.get("CRT_THOUGHT_LOG", "~/.crt/thoughts.log"))

# The tube is 40 columns and crt-monologue.py textwraps rather than
# truncates, so an untrimmed sqlite/OSError message would eat several of
# the 15 rows on its own. Enough to tell two causes apart, not enough to
# take the screen.
DETAIL_MAX = 70


def describe(exc):
    """Pure: the short, stable identity of a failure. Used both for the
    report text and as the de-duplication key, so 'distinct cause' means
    exactly what the person reads."""
    msg = " ".join(str(exc).split())
    if len(msg) > DETAIL_MAX:
        msg = msg[:DETAIL_MAX - 3] + "..."
    return "%s: %s" % (type(exc).__name__, msg) if msg else type(exc).__name__


def failure_report(name, exc):
    """Pure string builder, so the wording is testable with no console.
    Names the window, because the person reading window 1 needs to know
    which of the eight is limping -- and says it kept going, because the
    alternative reading ('it died') is the one this file exists to make
    false."""
    return "[!] %s skipped one -- %s (still running)" % (name, describe(exc))


def recovery_report(name, count):
    """Pure. A swallowed error with no trace is the failure mode this
    project keeps rediscovering, so recovery states the count rather than
    just going quiet.

    Says the WINDOW recovered, deliberately, not that the failing call
    works again: a loop whose next iteration legitimately does less (an
    idle-bait tick that finds the room noisy and skips straight past the
    part that raised) still counts as a clean iteration here. The honest
    claim is 'this loop is running and not throwing', which is the claim
    made."""
    return "[ok] %s recovered after %d skipped" % (name, count)


def announce(line, log_path=None):
    """Best-effort append to the log crt-monologue.py renders on window 1.
    Same convention as every other logging write here: a broken log write
    must never be the thing that ends the loop we are protecting."""
    log_path = log_path or THOUGHT_LOG
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a") as f:
            f.write("%s  %s\n" % (time.strftime("%H:%M:%S"), line))
    except OSError:
        pass


class LoopGuard:
    """Wraps one iteration of a background loop.

        guard = LoopGuard("bookanswer")
        for line in tail:
            with guard:
                ...body that may raise...

    An iteration that raises is reported and skipped; the loop continues.
    `guard.failures` counts every iteration ever skipped, `guard.streak`
    the current consecutive run (0 once one succeeds).
    """

    def __init__(self, name, report=None, log_path=None, verbose=None, echo=True):
        self.name = name
        self.failures = 0
        self.streak = 0
        self._reported = None
        self._log_path = log_path
        self._echo = echo
        self._report = report if report is not None else self._default_report
        # OFF by default. `book` is the window crt-console.sh boots selected,
        # so that pane's stdout/stderr IS the tube -- a traceback there is
        # painted over the console's face and stays until the next draw(),
        # which may be a long time if nothing is scanned. The one-line report
        # already carries the exception type and message; set
        # CRT_LOOP_GUARD_TRACEBACK=1 when you are attached to a window and
        # want the frames.
        self.verbose = bool(int(os.environ.get("CRT_LOOP_GUARD_TRACEBACK", "0"))) \
            if verbose is None else verbose

    def _default_report(self, line):
        # echo=False for any window whose stdout is a drawn screen rather
        # than scrollback: the line would land in the middle of the frame
        # and sit there. Window 1 still gets it, which is where this
        # project puts its bad news anyway.
        if self._echo:
            print(line, flush=True)
        announce(line, self._log_path)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            if self.streak:
                # Only after a real recovery, and only once: the streak is
                # cleared here so a later fault reports fresh.
                self._report(recovery_report(self.name, self.streak))
                self.streak = 0
                self._reported = None
            return False
        if not issubclass(exc_type, Exception):
            # KeyboardInterrupt, SystemExit, GeneratorExit: not ours.
            return False
        self.failures += 1
        self.streak += 1
        detail = describe(exc)
        if detail != self._reported:
            self._reported = detail
            if self.verbose:
                traceback.print_exception(exc_type, exc, tb)
            self._report(failure_report(self.name, exc))
        return True
