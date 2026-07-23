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
import argparse
import itertools
import os
import sys
import time

BIN_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ART = os.path.join(BIN_DIR, "..", "potato-small.txt")

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
    pad_top = max(0, (height - len(art) - 1) // 2)
    out = ["\x1b[H\x1b[2J"]
    style = (DIM if dim else "") + "\x1b[%sm" % color
    for _ in range(pad_top):
        out.append("")
    for line in art:
        left = max(0, (width - _display_len(line)) // 2)
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
    cols, rows = resolve_size()

    if args.once:
        sys.stdout.write(render_frame(art, cols, rows, args.caption, CYAN, dim=True))
        sys.stdout.write("\n")
        sys.stdout.flush()
        return 0

    for dim in itertools.cycle([True, False]):
        sys.stdout.write(render_frame(art, cols, rows, args.caption, CYAN, dim=dim))
        sys.stdout.flush()
        time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())
