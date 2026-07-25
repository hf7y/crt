#!/usr/bin/env python3
# What a scan looks like, in every direction -- one source (2026-07-25,
# fifteenth cycle).
#
# WHY THIS EXISTS. The barcode scanner is a USB HID keyboard: it types into
# whichever tmux window has focus (SCANNER.md's "2026-07-21 late session"
# finding, proven live). That makes "a scan line" a contract between
# processes, not a detail of one file:
#
#   the window that HAS focus   sees bare digits + Enter on its own stdin,
#                               and has to hand the scan on
#   ~/.crt/scanner.log          'ISO_TIMESTAMP\tISBN' -- the audit trail
#                               AND, since crt-scanner-feed.py was retired
#                               (de37a06), the only channel between a
#                               window that catches a scan and the window
#                               that draws the question
#   crt-book-console.py         reads both, and is the only writer of the
#                               log until now
#
# crt-screensaver.py is now a second writer of that log (it holds focus in
# the idle-lean layout, so scans land on IT), and a second opinion about
# what an ISBN looks like or what a log line looks like would break the
# funnel silently -- a scan forwarded in a shape the reader rejects is
# indistinguishable from no scan at all. Same anti-drift move as
# crt_wake_gate.py: the readers and the writers ask one module.
#
# Deliberately free of heavy imports: the screensaver is the face of the
# NO-brain-attached layout on a 1GB Pi (POTATO.md), and pulling
# crt-book-game.py in for a regex would drag sqlite3/urllib into the idle
# window. crt-book-game.py's own is_isbn_like() delegates here instead.
import datetime
import re

ISBN_RE = re.compile(r"\d{9}[\dXx]|\d{13}")


def is_isbn_like(text):
    """Pure function: does `text` look like a bare ISBN-10/13 (optional
    trailing check-digit 'X')? Shared by every entry point a scan can
    arrive through -- crt-book-game.py's parse_scan_line (tmux-delivered,
    prefixed), crt-book-console.py (scanner.log and its own stdin), and
    crt-screensaver.py (stdin while it holds focus) -- so they cannot
    drift on what counts as a valid scan."""
    return bool(re.fullmatch(ISBN_RE, text.strip()))


def parse_scanner_log_line(line):
    """Pure function: 'ISO_TIMESTAMP\\tTEXT' per scan (unprefixed, unlike
    the tmux '[scan] ' delivery crt-book-game.py's parse_scan_line
    handles) -- pulls TEXT back out, or None if the line isn't tab-shaped
    or TEXT isn't ISBN-like. The exact inverse of format_scan_log_line."""
    line = line.rstrip("\n")
    if "\t" not in line:
        return None
    _, text = line.split("\t", 1)
    text = text.strip()
    return text if is_isbn_like(text) else None


def parse_stdin_scan_line(line):
    """Pure function: a scan landing directly in a window's own stdin is
    bare digits + Enter -- the terminal's line-discipline (cooked mode)
    buffers the scanner's fast keystrokes and delivers them as one line on
    Enter, the same way a human pressing Enter would, no special handling
    needed on the reading end. No tab prefix to strip (unlike scanner.log's
    shape) -- just validate it's ISBN-shaped."""
    text = line.strip()
    return text if is_isbn_like(text) else None


def format_scan_log_line(isbn, timestamp=None):
    """Pure function: the exact 'ISO_TIMESTAMP\\tTEXT' shape
    parse_scanner_log_line() expects. Every window that catches a scan it
    cannot draw itself writes this shape and lets the `book` window pick it
    up -- crt-book-console.py for its own stdin, crt-screensaver.py for
    the idle face's."""
    ts = timestamp or datetime.datetime.now().isoformat(timespec="seconds")
    return "%s\t%s\n" % (ts, isbn)
