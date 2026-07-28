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
# - The CAPTION MOVES (2026-07-25, eighteenth cycle,
#   CRT_SCREENSAVER_CAPTION_MOVE_SECS, 0 pins it). The breath proves this
#   PROCESS is alive; it says nothing about the screen, which was one fixed
#   layout -- same caption, same row, same alignment -- from boot to
#   shutdown. The sibling resting screen (crt-book-console.py's shelf) was
#   fixed for exactly this last cycle, and in the idle-lean layout THIS is
#   the screen the tube boots into, so this is the one that was frozen in
#   front of anybody. Zach on that feature, quoted twice in his reply:
#   "rather than just sitting static -- the actual point of this feature",
#   "so the idle screen doesn't look frozen in the same layout every single
#   time".
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
import datetime
import importlib.util
import itertools
import os
import sys
import threading
import time

BIN_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ART = os.path.join(BIN_DIR, "..", "potato-small.txt")
# New art (2026-07-28, Zach-directed), alternated with DEFAULT_ART until
# OLD_ART_SUNSET_DATE, then DEFAULT_ART retires and this is the only art
# shown. "hardcode expiration" was the explicit instruction -- this is
# that hardcode, not a config knob: bump the date by hand (and update
# this comment) if the sunset needs to move, don't wire an env var
# around a decision meant to actually take effect.
NEW_ART = os.path.join(BIN_DIR, "..", "potato.txt")
OLD_ART_SUNSET_DATE = datetime.date(2026, 8, 27)  # 30 days out from the decision

# Two imports, both deliberately light: crt_scan_line.py pulls in `re` and
# `datetime`, crt_caption.py `re`, `random` and `unicodedata`, and nothing
# else. Loading crt-book-console.py or crt-book-game.py to reuse the same
# functions would drag sqlite3 and urllib into the window whose entire reason
# for existing is holding no brain on a 1GB Pi (POTATO.md /
# ARCHITECTURE-REVIEW-2026-07-23.md).
def _load_sibling(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(BIN_DIR, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


scan_line = _load_sibling("crt_scan_line_for_screensaver", "crt_scan_line.py")
# The second light one (2026-07-25): column measurement and caption placement,
# shared with crt-book-console.py's resting screen so both idle faces answer
# "how wide is this, and where does it go" the same way. stdlib-only, same
# reason as above -- see bin/crt_caption.py's header.
caption_lib = _load_sibling("crt_caption_for_screensaver", "crt_caption.py")


# A seconds-valued env var, junk-tolerant. These names are set by
# crt-console.sh, i.e. by shell. A bare float() on a misspelled value raises
# inside argparse's defaults -- before a single frame is drawn -- and leaves a
# bash prompt on the window that IS the console's face in the idle-lean
# layout. Negative is junk too; only 0 disables.
#
# One copy since 2026-07-25 (twentieth cycle): this was byte-for-byte
# identical to crt-book-console.py's, docstring included. bin/crt_config.py
# holds it now. Third light stdlib-only sibling loaded here, same rule as the
# two above.
crt_config = _load_sibling("crt_config_for_screensaver", "crt_config.py")
_env_secs = crt_config.env_number


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


def active_art_paths(today=None):
    """Pure function: which art file path(s) are in rotation right now.
    Before OLD_ART_SUNSET_DATE, both (alternated in main()'s loop); on or
    after it, NEW_ART only -- DEFAULT_ART (potato-small.txt) retires for
    good, not just stops being picked first. `today` is injectable so
    this is testable without waiting for the real calendar date."""
    today = today or datetime.date.today()
    if today >= OLD_ART_SUNSET_DATE:
        return [NEW_ART]
    return [DEFAULT_ART, NEW_ART]


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


def art_layout(art, width, height):
    """Where the art actually lands: (clipped lines, first row).

    Split out (2026-07-25) so the caption can be placed anywhere the art
    ISN'T, without a second copy of this arithmetic deciding where that is.
    """
    art = art[: max(1, height - 2)]  # leave a row for the caption
    # Never let a rendered line exceed the width, or it wraps on the tube
    # (the bug that made the potato look broken): if the art is wider than
    # the screen, drop leading cells rather than pad it off the edge.
    art = [caption_lib.cut_to_width(line, width) for line in art]
    return art, max(0, (height - len(art) - 1) // 2)


def caption_runs(art, width, height):
    """The runs of rows a caption may use, best first.

    Rows the art occupies are out. So is the strip ABOVE the art whenever
    there is any room below it: the top row of this tube is the most
    overscan-exposed edge (`~/.crt/display.conf`'s safe margin, which this
    window does not consume yet -- .claude/FOCUS.md backlog 5b), and the
    caption is the one line here that has to stay readable. It is the only
    thing on screen that says how to wake the console."""
    lines, top = art_layout(art, width, height)
    used = set(range(top, min(height, top + len(lines))))
    below = [r for r in range(height) if r not in used and r > max(used or {-1})]
    free = below or [r for r in range(height) if r not in used]
    return caption_lib.row_runs(free) or [[max(0, height - 1)]]


def pick_caption_slot(art, width, height, rng=None, avoid=None):
    """A (row, align) for the caption -- never the one it is in now."""
    return caption_lib.pick_slot(caption_runs(art, width, height),
                                 1, rng=rng, avoid=avoid)


def _frame_rows(art, width, height, caption, color, dim, slot=None):
    """The frame's content rows, unpadded by any overscan margin and
    with no clear-sequence prefix -- split out from render_frame()
    (2026-07-28) so a caller can shrink (width, height) for the
    calibrated safe area and then physically pad the result, the same
    two-step crt-book-console.py's redraw()/pad_for_margins() already
    does. render_frame() itself is now a thin wrapper for callers that
    don't need margin handling (tests, mostly)."""
    lines, top = art_layout(art, width, height)
    rows = [""] * max(1, height)
    style = (DIM if dim else "") + "\x1b[%sm" % color
    for i, line in enumerate(lines):
        row = top + i
        if row >= len(rows):
            break
        # clamp so leftpad + line can never exceed width (no wrap)
        w = caption_lib.display_width(line)
        rows[row] = " " * max(0, min((width - w) // 2, width - w)) + style + line + RESET
    if caption:
        row, align = slot or (len(rows) - 1, "center")
        row = min(max(0, row), len(rows) - 1)
        # Columns, not characters (bin/crt_caption.py): a caption cut and
        # centered by len() is drawn wider than the tube the moment it holds
        # anything East Asian Wide, and wraps. CRT_SCREENSAVER_CAPTION is a
        # free-text env var -- nothing stops one.
        cap = caption_lib.cut_to_width(caption, width)
        pad = width - caption_lib.display_width(cap)
        left = 0 if align == "left" else pad if align == "right" else pad // 2
        rows[row] = " " * left + DIM + "\x1b[%sm" % YELLOW + cap + RESET
    return rows


def render_frame(art, width, height, caption, color, dim, slot=None):
    """Build one full-screen frame string: cleared, art centered
    horizontally and vertically, caption at `slot` -- (row, alignment) --
    or on the last row, centered, when no slot is given.

    Exactly `height` lines, the clear sequence riding on the first one
    rather than taking a line of its own: emitting height+1 lines scrolled
    the tube by a row on every single frame, so the whole picture jumped up
    and back twice a breath. No margin handling -- see _frame_rows()'s
    docstring for the caller that wants that."""
    rows = _frame_rows(art, width, height, caption, color, dim, slot)
    return "\x1b[H\x1b[2J" + "\n".join(rows)


def load_safe_margins():
    """Same calibrated-margin loader + hard vertical floor as
    crt-book-console.py's load_safe_margins() (2026-07-28, Zach-
    directed: "splash screen doesn't look to be going through the same
    bezel margin enforcer, bottom line cut off by bezel") -- duplicated
    rather than imported (this window deliberately avoids importing
    crt-book-console.py or crt-book-game.py at all, see this file's own
    header on why: sqlite3/urllib have no business in the one window
    meant to hold no brain on a 1GB Pi). Degrades to the hard floor
    alone if crt-pager.py or the calibration file can't be read."""
    margins = {"top": 0, "bottom": 0, "left": 0, "right": 0}
    try:
        spec = importlib.util.spec_from_file_location(
            "crt_pager_margins_for_screensaver", os.path.join(BIN_DIR, "crt-pager.py"))
        pager = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pager)
        conf = os.path.expanduser(
            os.environ.get("CRT_DISPLAY_CONF", "~/.crt/display.conf"))
        margins = pager.load_display_margins(conf)
    except Exception:
        pass
    margins["top"] = max(margins.get("top", 0), MIN_VERTICAL_PAD)
    margins["bottom"] = max(margins.get("bottom", 0), MIN_VERTICAL_PAD)
    return margins


def safe_screen_size(width, height, margins):
    """(width, height) shrunk by `margins` -- pure, testable without a
    display.conf on disk. Same shape as crt-book-console.py's
    safe_screen_size()."""
    left, right = margins.get("left", 0), margins.get("right", 0)
    top, bottom = margins.get("top", 0), margins.get("bottom", 0)
    return max(1, width - left - right), max(1, height - top - bottom)


def pad_frame_rows(rows, margins, width):
    """Physically pushes already-rendered `rows` away from the tube's
    edges by `margins` -- same reasoning and same shape as
    crt-book-console.py's pad_for_margins(): shrinking the content box
    passed to _frame_rows() only makes the ART smaller/centered within
    that box, the box itself still starts at the true top-left corner
    (render_frame's own `\\x1b[H`) unless something adds real blank
    rows/columns here."""
    left = " " * max(0, margins.get("left", 0))
    padded = [left + r for r in rows]
    blank = " " * (width + margins.get("left", 0) + margins.get("right", 0))
    top = [blank] * max(0, margins.get("top", 0))
    bottom = [blank] * max(0, margins.get("bottom", 0))
    return top + padded + bottom


# Same hard floor as crt-book-console.py's MIN_VERTICAL_PAD (2026-07-28):
# at least one blank line top and bottom even with zero calibration.
MIN_VERTICAL_PAD = int(os.environ.get("CRT_SCREENSAVER_MIN_VERTICAL_PAD", "1"))


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
    # No hardcoded default here (2026-07-28): an explicit --art/
    # CRT_SCREENSAVER_ART pins ONE file, same as always (manual override
    # wins, no alternation). Left unset, active_art_paths() decides --
    # both potato-small.txt and potato.txt alternated until
    # OLD_ART_SUNSET_DATE, then potato.txt only.
    p.add_argument("--art", default=os.environ.get("CRT_SCREENSAVER_ART"))
    # "say 'potato' to wake me" removed (2026-07-28, Zach-directed) --
    # default caption is now empty. Still overridable via --caption/
    # CRT_SCREENSAVER_CAPTION for anyone who wants a caption back.
    p.add_argument("--caption", default=os.environ.get("CRT_SCREENSAVER_CAPTION", ""))
    p.add_argument("--interval", type=float,
                    default=_env_secs("CRT_SCREENSAVER_INTERVAL", 2.5))
    p.add_argument("--caption-move-secs", type=float,
                    default=_env_secs("CRT_SCREENSAVER_CAPTION_MOVE_SECS", 8.0),
                    help="how often the caption moves to a new spot; 0 pins it")
    p.add_argument("--art-rotate-secs", type=float,
                    default=_env_secs("CRT_SCREENSAVER_ART_ROTATE_SECS", 10.0),
                    help="how often the art alternates when more than one is active; 0 pins the first")
    p.add_argument("--once", action="store_true",
                    help="render a single frame and exit (for tests/preview)")
    args = p.parse_args(argv)

    art_paths = [args.art] if args.art else active_art_paths()
    arts = [load_art(path) for path in art_paths]
    art = arts[0]
    margins = load_safe_margins()

    if args.once:
        cols, rows = resolve_size()
        content_cols, content_rows = safe_screen_size(cols, rows, margins)
        frame_rows = _frame_rows(art, content_cols, content_rows, args.caption, CYAN, dim=True)
        padded = pad_frame_rows(frame_rows, margins, content_cols)
        sys.stdout.write("\x1b[H\x1b[2J" + "\n".join(padded))
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
    slot, move_at = None, 0.0
    art_idx, art_move_at = 0, 0.0
    for dim in itertools.cycle([True, False]):
        raw_cols, raw_rows = resolve_size()
        cols, rows = safe_screen_size(raw_cols, raw_rows, margins)
        # Art alternation (2026-07-28): only matters while more than one
        # art is active (see active_art_paths()/OLD_ART_SUNSET_DATE) --
        # a single-art rotation is a no-op every tick, same "automatic
        # behaviour keeps a manual escape hatch" rule as caption_move_secs
        # below (0 pins it, here to index 0 == whatever was loaded first).
        if len(arts) > 1 and args.art_rotate_secs and time.time() >= art_move_at:
            art_idx = (art_idx + 1) % len(arts)
            art = arts[art_idx]
            art_move_at = time.time() + args.art_rotate_secs
            # Force the caption slot to recompute against the NEW art's
            # geometry immediately, not on its own next tick -- the two
            # arts are different sizes, and a slot picked for one can
            # land inside the other's rows until caption_move_secs
            # catches up on its own schedule otherwise.
            move_at = 0.0
        # The caption moves (2026-07-25, eighteenth cycle). The breathing
        # proves this process is alive; it does not stop the SCREEN from
        # being one fixed layout from boot until someone speaks, which is
        # what the sibling resting screen was just fixed for -- and in the
        # idle-lean layout THIS is the screen the tube boots into, so it is
        # the one that was actually frozen in front of anybody. Zach, on the
        # book console's version of this, twice: "rather than just sitting
        # static -- the actual point of this feature", "so the idle screen
        # doesn't look frozen in the same layout every single time".
        #
        # Its own cadence, not the breath's: 8s reads as a screen with
        # something going on, 2.5s reads as a twitch. 0 pins it where it has
        # always been (last row, centered) -- an automatic behaviour keeps
        # its manual escape hatch, same rule as CRT_BOOK_IDLE_ROTATE_SECS.
        if args.caption_move_secs and time.time() >= move_at:
            slot = pick_caption_slot(art, cols, rows, avoid=slot)
            move_at = time.time() + args.caption_move_secs
        frame_rows = _frame_rows(art, cols, rows, args.caption, CYAN, dim=dim, slot=slot)
        padded = pad_frame_rows(frame_rows, margins, cols)
        sys.stdout.write("\x1b[H\x1b[2J" + "\n".join(padded))
        sys.stdout.flush()
        time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())
