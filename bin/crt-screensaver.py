#!/usr/bin/env python3
# The potato screensaver: what the CRT shows while the console is idle and
# holding NO Claude brain (see POTATO.md). Renders Zach's braille-art
# potato (potato-small.txt) centered on the 40x15 tube, breathing gently,
# with a small caption line. On wake the console switches away from this
#   [rest: vault:crt/header-archaeology-20260817.md]
import argparse
import importlib.util
import os
import random
import sys
import threading
import time

BIN_DIR = os.path.dirname(os.path.abspath(__file__))
# 2026-07-28, Zach-directed, in three steps same session:
#   1. potato.txt introduced, alternated with the old potato-small.txt
#      until a 30-day sunset.
#   2. "hard prefer the new potato.txt, sunset old potato_small.txt
#   [rest: vault:crt/header-archaeology-20260817.md]
DEFAULT_ART = os.path.join(BIN_DIR, "..", "potato.txt")
NEW_ART = os.path.join(BIN_DIR, "..", "potato2.txt")

# Two imports, both deliberately light: crt_scan_line.py pulls in `re` and
# `datetime`, crt_caption.py `re`, `random` and `unicodedata`, and nothing
# else. Loading crt-book-console.py or crt-book-game.py to reuse the same
# functions would drag sqlite3 and urllib into the window whose entire reason
# for existing is holding no brain on a 1GB Pi (POTATO.md /
# vault:crt/ARCHITECTURE-REVIEW-2026-07-23.md).
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
#   [rest: vault:crt/header-archaeology-20260817.md]
crt_config = _load_sibling("crt_config_for_screensaver", "crt_config.py")
_env_secs = crt_config.env_number


SCANNER_LOG = os.path.expanduser(os.environ.get("CRT_SCANNER_LOG", "~/.crt/scanner.log"))
THOUGHT_LOG = os.path.expanduser(os.environ.get("CRT_THOUGHT_LOG", "~/.crt/thoughts.log"))
# Sleep/wake (2026-07-28, Zach-directed): "have potato 2 for long
# stretches 'potato is asleep' ... on any sound, volume over threshold,
# go to the blink animation ... potato wakes up. then have a >60s
# silence resulting in sleep again." Reuses crt-stt-solo.py's own
#   [rest: vault:crt/header-archaeology-20260817.md]
STT_LOG = os.path.expanduser(os.environ.get("CRT_STT_LOG", "~/.crt/stt.log"))
GATE_LOG = os.path.expanduser(os.environ.get("CRT_STT_GATE_LOG", "~/.crt/gate.log"))
SLEEP_SILENCE_SECS = _env_secs("CRT_SCREENSAVER_SLEEP_SILENCE_SECS", 60.0)

FALLBACK_ART = [
    "   .-\"\"\"\"-.",
    "  /  .-. .\\",
    " |  (   ) |",
    "  \\  `-' /",
    "   `----'",
]

CYAN, YELLOW, WHITE = "36", "33", "37"
DIM, BOLD, RESET = "\x1b[2m", "\x1b[1m", "\x1b[0m"

# Potato-colored variety for the ART ONLY (2026-07-28, Zach-directed,
# three passes now): "tan, brown, logos don't need to be exactly read
# safe" -> "more potato colored (brown, yellow, golden)" -> LIVE, on the
# real CRT: "should not be flashing between grey and red... red is no
#   [rest: vault:crt/header-archaeology-20260817.md]
LOGO_COLORS = [
    c.strip() for c in os.environ.get(
        "CRT_SCREENSAVER_LOGO_COLORS", "38;5;100,38;5;94,38;5;137"
    ).split(",")
    if c.strip()
] or [WHITE]

# Sentinel for _frame_rows()'s `color` param: a real yellow-through-
# brown BLEND across the art's own rows, not one flat shade per frame
# (2026-07-28, live, Zach: "colors are wrong... can get mixed color
# output yellow and brown and inbetween?"). The discrete per-tick
# LOGO_COLORS rotation this replaced picked ONE color for the whole
# frame; this picks one PER ROW, sampled evenly across LOGO_COLORS
# top-to-bottom, so a single frame shows the actual gradient.
GRADIENT = "gradient"


def gradient_colors(n, palette=None, offset=0):
    """n colors sampled evenly across `palette` (default LOGO_COLORS),
    top-to-bottom, then rotated by `offset` positions (2026-07-28, live,
    Zach: "rotating gradient of olive, brown, tan (all at once, but the
    gradient crossover changes)" -- a static row->color mapping read as
    flat; the crossover point between colors needs to actually move
    over time). Pure/deterministic given n/palette/offset -- the
    ROTATION over time is main()'s job (a slowly-incrementing offset
    counter), not this function's; same "no hidden state" rule as the
    unrotated version this replaces."""
    palette = list(palette or LOGO_COLORS)
    if n <= 0:
        return []
    if n == 1 or len(palette) == 1:
        return [palette[offset % len(palette)]] * n
    return [palette[(round(i * (len(palette) - 1) / (n - 1)) + offset) % len(palette)]
           for i in range(n)]


# Blink model (2026-07-28, Zach-directed): "make the shimmer stay long
# on potato.txt with a quick potato2.txt, random delay, about 80-90% on
# potato one. this is a blink. shouldn't be predictable, just a flash."
# REPLACES the earlier fixed-cadence art_idx cycling entirely -- a
#   [rest: vault:crt/header-archaeology-20260817.md]
BLINK_PROBABILITY = float(os.environ.get("CRT_SCREENSAVER_BLINK_PROBABILITY", "0.15"))
REST_HOLD_RANGE = (4.0, 14.0)   # seconds potato.txt is held between blink rolls
# 2026-07-28, live, Zach: "blink should be on the order of a human
# blink" -- a real eye blink is ~0.1-0.4s. The old (0.3, 0.9) range was
# already close, but with the old 2.5s --interval default the loop
# could never repaint fast enough to show a hold this short as a quick
# flash -- it just ate a full frame or two, reading as "far too long".
# See --interval's own default change below; this range only reads as
# a real blink once the loop repaints faster than the hold itself.
BLINK_HOLD_RANGE = (0.1, 0.35)   # seconds potato2.txt is held during a blink


def next_blink_state(rng=None):
    """Pure: (is_blink, hold_secs) for the state that should start now.
    Call again once hold_secs has elapsed to get what comes after.
    is_blink=False means arts[0] (potato.txt, resting); True means
    arts[1] (potato2.txt, a brief flash). BLINK_HOLD_RANGE is much
    shorter than REST_HOLD_RANGE, so even a BLINK_PROBABILITY as high
    as 0.15 per decision still spends well under 15% of real TIME on
    the blink frame -- comfortably inside Zach's "80-90% on potato one"
    without the two numbers needing to match directly."""
    rng = rng or random
    if rng.random() < BLINK_PROBABILITY:
        return True, rng.uniform(*BLINK_HOLD_RANGE)
    return False, rng.uniform(*REST_HOLD_RANGE)


def last_sound_at(stt_log=None, gate_log=None):
    """The more recent of STT_LOG/GATE_LOG's mtime, or None if neither
    exists yet (nothing has ever been heard on this box). Pure given the
    two paths; reads the filesystem, no other side effects."""
    times = []
    for p in (stt_log or STT_LOG, gate_log or GATE_LOG):
        try:
            times.append(os.path.getmtime(p))
        except OSError:
            pass
    return max(times) if times else None


def is_asleep(now, stt_log=None, gate_log=None, silence_secs=None):
    """True if potato should be shown asleep (frozen on potato2.txt) --
    no sound heard yet at all, or the most recent sound was more than
    `silence_secs` (default SLEEP_SILENCE_SECS) ago. Pure given `now`
    (injectable so this is testable without waiting on a real clock)."""
    silence_secs = SLEEP_SILENCE_SECS if silence_secs is None else silence_secs
    last = last_sound_at(stt_log, gate_log)
    if last is None:
        return True
    return (now - last) >= silence_secs


def frame_color_for_state(asleep):
    """The `color` arg _frame_rows() should get for this tick (2026-07-28,
    live, Zach: "sleeping potato should stay grey. let's try multicolor
    yellow, brown, tan for wake potato"). Sleep stays plain WHITE/grey,
    deliberately NOT the gradient -- only the awake/blinking state gets
    the (still being live-tuned, see LOGO_COLORS' own comment on the
    CRT_SCREENSAVER_LOGO_COLORS override) color treatment. Pure/trivial
    on purpose: kept as a real function rather than an inline ternary so
    the sleep/awake color split has its own test, not just an assertion
    buried in a live-process integration test."""
    return WHITE if asleep else GRADIENT


def frame_dim_for_state(asleep, cycled_dim):
    """The `dim` arg _frame_rows() should get for this tick (2026-07-28,
    live, Zach: "make sleep potato stop blinking"). The art itself was
    already frozen on arts[1] while asleep, but the loop's own DIM/
    normal breathing cycle kept alternating regardless -- a second,
    separate kind of "blinking" Zach was still seeing. Asleep always
    gets True (a static dim frame reads as resting, not off); awake
    passes through whatever the loop's own breathing cycle says."""
    return True if asleep else cycled_dim


def active_art_paths(today=None):
    """Pure function: which art file path(s) are in rotation right now --
    always both (2026-07-28: potato.txt/potato2.txt are a permanent
    animation pair, not an old-vs-new deprecation window). `today`
    accepted and ignored, kept only so callers from the prior sunset-
    based design don't need to change their call shape."""
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


def art_layout(art, width, height, reserve_caption=True):
    """Where the art actually lands: (clipped lines, first row).

    Split out (2026-07-25) so the caption can be placed anywhere the art
    ISN'T, without a second copy of this arithmetic deciding where that is.

    `reserve_caption` (2026-07-28, live fix): the 2-row reservation used
    to be unconditional, which was harmless while the default caption
    was always non-empty text -- but the same session's caption-removal
    change (default caption now "") plus the overscan safe-margin fix
    (content height already shrunk once) stacked into potato.txt's real
    13-line art losing its bottom 2 lines to a reservation for a caption
    that was never going to be drawn. Callers that know there's no
    caption text this frame pass False and get the full height back."""
    reserve = 2 if reserve_caption else 0
    art = art[: max(1, height - reserve)]
    # Never let a rendered line exceed the width, or it wraps on the tube
    # (the bug that made the potato look broken): if the art is wider than
    # the screen, drop leading cells rather than pad it off the edge.
    art = [caption_lib.cut_to_width(line, width) for line in art]
    return art, max(0, (height - len(art) - 1) // 2)


def caption_runs(art, width, height, reserve_caption=True):
    """The runs of rows a caption may use, best first.

    Rows the art occupies are out. So is the strip ABOVE the art whenever
    there is any room below it: the top row of this tube is the most
    overscan-exposed edge (now actually enforced -- see load_safe_
    margins()/pad_frame_rows(), 2026-07-28), and the caption is the one
    line here that has to stay readable. It is the only thing on screen
    that says how to wake the console, when one is configured at all."""
    lines, top = art_layout(art, width, height, reserve_caption=reserve_caption)
    used = set(range(top, min(height, top + len(lines))))
    below = [r for r in range(height) if r not in used and r > max(used or {-1})]
    free = below or [r for r in range(height) if r not in used]
    return caption_lib.row_runs(free) or [[max(0, height - 1)]]


def pick_caption_slot(art, width, height, rng=None, avoid=None, reserve_caption=True):
    """A (row, align) for the caption -- never the one it is in now."""
    return caption_lib.pick_slot(caption_runs(art, width, height, reserve_caption=reserve_caption),
                                 1, rng=rng, avoid=avoid)


def _frame_rows(art, width, height, caption, color, dim, slot=None, gradient_offset=0):
    """The frame's content rows, unpadded by any overscan margin and
    with no clear-sequence prefix -- split out from render_frame()
    (2026-07-28) so a caller can shrink (width, height) for the
    calibrated safe area and then physically pad the result, the same
    two-step crt-book-console.py's redraw()/pad_for_margins() already
    does. render_frame() itself is now a thin wrapper for callers that
    don't need margin handling (tests, mostly). `gradient_offset` only
    matters when color is GRADIENT -- see gradient_colors()."""
    lines, top = art_layout(art, width, height, reserve_caption=bool(caption))
    rows = [""] * max(1, height)
    line_colors = (gradient_colors(len(lines), offset=gradient_offset) if color == GRADIENT
                  else [color] * len(lines))
    for i, line in enumerate(lines):
        row = top + i
        if row >= len(rows):
            break
        # clamp so leftpad + line can never exceed width (no wrap)
        w = caption_lib.display_width(line)
        style = (DIM if dim else "") + "\x1b[%sm" % line_colors[i]
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
    # 2026-07-28, live, Zach: "general timing of animation is too slow" --
    # a 2.5s repaint cadence meant a 0.3-0.9s blink hold (BLINK_HOLD_RANGE)
    # could never actually be SEEN as short; the loop just repainted once
    # or twice during it and moved on, reading as a long hold rather than
    #   [rest: vault:crt/header-archaeology-20260817.md]
    p.add_argument("--interval", type=float,
                    default=_env_secs("CRT_SCREENSAVER_INTERVAL", 0.15))
    p.add_argument("--caption-move-secs", type=float,
                    default=_env_secs("CRT_SCREENSAVER_CAPTION_MOVE_SECS", 8.0),
                    help="how often the caption moves to a new spot; 0 pins it")
    # --art-rotate-secs removed (2026-07-28): art alternation moved from
    # a fixed cadence to the blink model (next_blink_state(), see
    # BLINK_PROBABILITY/REST_HOLD_RANGE/BLINK_HOLD_RANGE) and color
    # moved from a discrete per-tick rotation to a static gradient (see
    # GRADIENT/gradient_colors()) -- neither one is driven by a single
    # interval anymore, so the flag had nothing left to control.
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
        frame_rows = _frame_rows(art, content_cols, content_rows, args.caption, GRADIENT, dim=True)
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
    art_move_at = 0.0
    was_asleep = False
    # Rotating gradient (2026-07-28, live, Zach: "instead of flash to
    # grey, have rotating gradient of olive, brown, tan (all at once,
    # but the gradient crossover changes)"). gradient_offset only
    # advances while awake -- sleep already renders flat WHITE
    #   [rest: vault:crt/header-archaeology-20260817.md]
    gradient_offset = 0
    gradient_move_at = 0.0
    GRADIENT_ROTATE_SECS = float(os.environ.get("CRT_SCREENSAVER_GRADIENT_ROTATE_SECS", "3.0"))
    # Breathing dim pulse (pre-existing feature): used to be one
    # `itertools.cycle([True, False])` step per loop iteration, which
    # was fine when --interval defaulted to 2.5s (a 5s breathing cycle)
    # but ties the pulse's cadence directly to the repaint rate. Now
    #   [rest: vault:crt/header-archaeology-20260817.md]
    dim = True
    dim_move_at = 0.0
    BREATHE_SECS = float(os.environ.get("CRT_SCREENSAVER_BREATHE_SECS", "2.5"))
    while True:
        if time.time() >= dim_move_at:
            dim = not dim
            dim_move_at = time.time() + BREATHE_SECS
        raw_cols, raw_rows = resolve_size()
        cols, rows = safe_screen_size(raw_cols, raw_rows, margins)
        # Sleep/wake (2026-07-28): frozen on arts[1] (potato2.txt,
        # "potato is asleep") after SLEEP_SILENCE_SECS with no sound
        # heard (is_asleep() reads crt-stt-solo.py's own STT_LOG/
        # GATE_LOG mtimes -- see that function's docstring for why this
        #   [rest: vault:crt/header-archaeology-20260817.md]
        asleep = len(arts) > 1 and is_asleep(time.time())
        if asleep:
            if not was_asleep:
                art = arts[1]
                move_at = 0.0
            art_move_at = time.time() + 1.0  # re-check soon in case sound arrives
        elif was_asleep:
            art_move_at = 0.0  # force a fresh blink roll on waking, not a stale one
        was_asleep = asleep
        # Blink (2026-07-28, replaces the earlier fixed-cadence art_idx
        # cycling): mostly arts[0] (potato.txt), rare short unpredictable
        # flashes to arts[1] (potato2.txt) -- see next_blink_state()'s
        # own docstring. Only meaningful with 2 arts (the permanent
        # potato.txt/potato2.txt pair); an explicit single --art pins
        # art at index 0 forever, same "manual escape hatch" rule as
        # caption_move_secs below.
        if not asleep and len(arts) > 1 and time.time() >= art_move_at:
            is_blink, hold = next_blink_state()
            art = arts[1] if is_blink else arts[0]
            art_move_at = time.time() + hold
            # Force the caption slot to recompute against the NEW art's
            # geometry immediately, not on its own next tick -- the two
            # arts are different sizes, and a slot picked for one can
            # land inside the other's rows until caption_move_secs
            # catches up on its own schedule otherwise.
            move_at = 0.0
        # Color: a real gradient across the art's own rows, not one flat
        # shade per frame (2026-07-28, live, replacing an earlier
        # discrete per-tick LOGO_COLORS rotation -- Zach: "colors are
        # wrong... can get mixed color output yellow and brown and
        #   [rest: vault:crt/header-archaeology-20260817.md]
        if args.caption_move_secs and time.time() >= move_at:
            slot = pick_caption_slot(art, cols, rows, avoid=slot,
                                     reserve_caption=bool(args.caption))
            move_at = time.time() + args.caption_move_secs
        if not asleep and time.time() >= gradient_move_at:
            gradient_offset += 1
            gradient_move_at = time.time() + GRADIENT_ROTATE_SECS
        frame_color = frame_color_for_state(asleep)
        frame_dim = frame_dim_for_state(asleep, dim)
        frame_rows = _frame_rows(art, cols, rows, args.caption, frame_color, dim=frame_dim, slot=slot,
                                 gradient_offset=gradient_offset)
        padded = pad_frame_rows(frame_rows, margins, cols)
        sys.stdout.write("\x1b[H\x1b[2J" + "\n".join(padded))
        sys.stdout.flush()
        time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())
