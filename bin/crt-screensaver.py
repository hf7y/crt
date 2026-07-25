#!/usr/bin/env python3
# The potato screensaver: what the CRT shows while the console is idle and
# holding NO Claude brain (see POTATO.md). Renders Zach's braille-art
# potato (potato-small.txt) centered on the 40x15 tube, breathing gently,
# with a small caption line. On wake the console switches away from this
# window to whichever brain crt-wake-router.py chose.
#
# Design notes:
# - Art comes from an external file so the drawing lives with Zach, not in
#   this code (default: ../potato-small.txt next to bin/). If it's missing
#   or unreadable we fall back to a tiny inline spud rather than crash --
#   a dark screen is worse than an ugly one.
# - CRT-safe colors ONLY (CLAUDE.md hard rule): yellow/magenta/cyan/white
#   + dim/bold. NO 31/32/34/91/92/94 -- saturated primaries smear on the
#   real tube. The potato is dim cyan; the caption is dim yellow.
# - "Breathing" is just alternating dim/normal on the same frame, cheap
#   and calm -- not a flashy animation. This is a screensaver, not a demo.
#
# IT ALSO CATCHES SCANS (2026-07-25, fifteenth nightly cycle). The barcode
# scanner is a USB HID keyboard: it types into whichever tmux window has
# FOCUS (SCANNER.md's "2026-07-21 late session" finding, proven live), which
# is why crt-console.sh made `book` the boot-default window. The idle-lean
# layout selects THIS window instead -- so on potato, every scan has been
# typing bare digits into a screensaver that never read its own stdin, and
# the Book Game funnel's first link (idle-bait -> SCAN -> question) has been
# dead in the only layout that actually boots there. A scan produced
# nothing: no question, no answer window, no training row.
#
# Forwarding, not handling: an ISBN-shaped line goes into ~/.crt/scanner.log
# in the exact shape crt-book-console.py already tails (bin/crt_scan_line.py
# owns that contract for both ends), and the `book` window draws the
# question and brings itself to the front. This window stays what it is --
# an idle face with no brain, no database, and no book logic.
import argparse
import importlib.util
import itertools
import os
import sys
import threading
import time

BIN_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ART = os.path.join(BIN_DIR, "..", "potato-small.txt")

# The one import, and deliberately the light one: crt_scan_line.py pulls in
# `re` and `datetime` and nothing else. Loading crt-book-console.py or
# crt-book-game.py to reuse the same two functions would drag sqlite3 and
# urllib into the window whose entire reason for existing is holding no
# brain on a 1GB Pi (POTATO.md / ARCHITECTURE-REVIEW-2026-07-23.md).
_scan_spec = importlib.util.spec_from_file_location(
    "crt_scan_line_for_screensaver", os.path.join(BIN_DIR, "crt_scan_line.py"))
scan_line = importlib.util.module_from_spec(_scan_spec)
_scan_spec.loader.exec_module(scan_line)

SCANNER_LOG = os.path.expanduser(os.environ.get("CRT_SCANNER_LOG", "~/.crt/scanner.log"))
THOUGHT_LOG = os.path.expanduser(os.environ.get("CRT_THOUGHT_LOG", "~/.crt/thoughts.log"))

FALLBACK_ART = [
    "   .-\"\"\"\"-.",
    "  /  .-. .\\",
    " |  (   ) |",
    "  \\  `-' /",
    "   `----'",
]

CYAN, YELLOW, WHITE = "36", "33", "37"
DIM, BOLD, RESET = "\x1b[2m", "\x1b[1m", "\x1b[0m"


def load_art(path):
    """Return the art as a list of lines. Never raises -- falls back to a
    tiny inline potato if the file is missing/unreadable."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = [ln.rstrip("\n") for ln in f]
        # Drop trailing blank lines so centering isn't thrown off.
        while lines and not lines[-1].strip():
            lines.pop()
        return lines if lines else list(FALLBACK_ART)
    except OSError:
        return list(FALLBACK_ART)


def resolve_size():
    """Env override > real terminal size > 40x15 hardware fallback, same
    precedence crt-pager.py/crt-monologue.sh use."""
    try:
        cols = int(os.environ.get("CRT_COLS", "0"))
        rows = int(os.environ.get("CRT_ROWS", "0"))
    except ValueError:
        cols = rows = 0
    if cols and rows:
        return cols, rows
    try:
        sz = os.get_terminal_size()
        return sz.columns, sz.lines
    except OSError:
        return 40, 15


def render_frame(art, width, height, caption, color, dim):
    """Build one full-screen frame string: cleared, art centered
    horizontally and vertically, caption on the last row."""
    art = art[: max(1, height - 2)]  # leave a row for the caption
    # Never let a rendered line exceed the width, or it wraps on the tube
    # (the bug that made the potato look broken): if the art is wider than
    # the screen, drop leading cells rather than pad it off the edge.
    art = [line[:width] if _display_len(line) > width else line for line in art]
    pad_top = max(0, (height - len(art) - 1) // 2)
    out = ["\x1b[H\x1b[2J"]
    style = (DIM if dim else "") + "\x1b[%sm" % color
    for _ in range(pad_top):
        out.append("")
    for line in art:
        # clamp so leftpad + line can never exceed width (no wrap)
        left = max(0, min((width - _display_len(line)) // 2, width - _display_len(line)))
        out.append(" " * left + style + line + RESET)
    if caption:
        cap = caption[:width]
        left = max(0, (width - len(cap)) // 2)
        # blank-fill down to the last row, then the caption
        for _ in range(max(0, height - len(art) - pad_top - 1)):
            out.append("")
        out.append(" " * left + DIM + "\x1b[%sm" % YELLOW + cap + RESET)
    return "\n".join(out)


def _display_len(s):
    # Braille cells are single-width; this is just len() but kept as a seam
    # in case wider glyphs ever get used in the art.
    return len(s)


def forward_scan(isbn, log_path=None):
    """Append one scan to scanner.log, in crt-book-console.py's own shape.
    Returns (ok, detail) rather than swallowing the error: a scan this
    window catches and then loses is invisible twice over -- the person
    sees the potato both before and after -- so the caller has something
    honest to say about it."""
    log_path = log_path or SCANNER_LOG
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a") as f:
            f.write(scan_line.format_scan_log_line(isbn))
    except OSError as e:
        return False, str(e)
    return True, None


def scan_failure_report(isbn, detail):
    """Pure string builder, testable without a filesystem. Names the ISBN:
    it is the one thing the person can act on (scan it again, or type it
    into crt-book-game.py by hand). Short -- 40-column tube."""
    return "[!] caught scan %s but couldn't pass it on: %s" % (isbn, detail)


def announce(line, log_path=None):
    """Best-effort append to thoughts.log, the channel crt-monologue.py
    renders on window 1. Best-effort in the strict sense: this runs on the
    forwarding thread of a screensaver, and a full disk must not take the
    idle face down with it."""
    log_path = log_path or THOUGHT_LOG
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a") as f:
            f.write("%s  %s\n" % (time.strftime("%H:%M:%S"), line))
    except OSError:
        pass


def scan_forwarder(stream=None, log_path=None, on_line=None):
    """Blocking loop, run on a daemon thread: read this window's own stdin
    and forward anything ISBN-shaped to scanner.log.

    Non-ISBN input is dropped, not forwarded -- scanner.log is an audit
    trail of scans, and stray keystrokes are not scans. The terminal's own
    cooked-mode echo will have painted them onto the frame, which the
    animation loop clears on its next repaint (<= --interval seconds), so
    the screen self-heals without this thread doing anything about it.

    Errors are reported once per distinct cause, the same rule
    crt-window-switcher.py uses for a failed select-window: this loop wakes
    on every scan, and window 1 fades the person's own words out from the
    top. `on_line` is a test seam."""
    stream = stream if stream is not None else sys.stdin
    reported = None
    for line in stream:
        isbn = scan_line.parse_stdin_scan_line(line)
        if isbn is None:
            continue
        ok, detail = forward_scan(isbn, log_path)
        if ok:
            reported = None
        elif detail != reported:
            reported = detail
            announce(scan_failure_report(isbn, detail))
        if on_line is not None:
            on_line(isbn, ok)


def main(argv=None):
    p = argparse.ArgumentParser(description="Potato idle screensaver for the CRT.")
    p.add_argument("--art", default=os.environ.get("CRT_SCREENSAVER_ART", DEFAULT_ART))
    p.add_argument("--caption", default=os.environ.get("CRT_SCREENSAVER_CAPTION",
                                                        "say 'potato' to wake me"))
    p.add_argument("--interval", type=float,
                    default=float(os.environ.get("CRT_SCREENSAVER_INTERVAL", "2.5")))
    p.add_argument("--once", action="store_true",
                    help="render a single frame and exit (for tests/preview)")
    args = p.parse_args(argv)

    art = load_art(args.art)

    if args.once:
        cols, rows = resolve_size()
        sys.stdout.write(render_frame(art, cols, rows, args.caption, CYAN, dim=True))
        sys.stdout.write("\n")
        sys.stdout.flush()
        return 0

    # A daemon thread, so a blocked stdin read can never stall the
    # breathing animation, and stdin reaching EOF (the thread simply ends)
    # can never keep the process alive. Deliberately NOT started for
    # --once, which is a render-a-frame-and-exit preview.
    threading.Thread(target=scan_forwarder, daemon=True).start()

    # Re-read the terminal size EVERY frame, not once at startup: a tmux
    # window created detached defaults to 80x24 and only resizes to the
    # real 40x15 once the client attaches. Reading once at boot cached 80
    # and centered for it, so lines wrapped on the tube. Cheap to redo.
    for dim in itertools.cycle([True, False]):
        cols, rows = resolve_size()
        sys.stdout.write(render_frame(art, cols, rows, args.caption, CYAN, dim=dim))
        sys.stdout.flush()
        time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())
