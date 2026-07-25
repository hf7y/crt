#!/usr/bin/env python3
"""One home for measuring and placing a caption on this console's tube.

WHY THIS FILE EXISTS (2026-07-25, eighteenth nightly cycle).

Two windows draw a resting screen: `crt-book-console.py` (the shelf + a
caption that invites a scan) and `crt-screensaver.py` (the potato + a caption
that says how to wake it). They are the same screen to the person looking at
the tube -- whichever one the current layout boots into is "the idle screen"
-- and they had two different answers to the same two questions:

  1. How wide is this text, really? Last cycle taught the book console to
     measure in COLUMNS rather than characters (a kaomoji is 7 columns of 5
     characters, and Open Library hands back CJK titles). The screensaver
     still counted characters, in both the cut and the centering.
  2. Where does the caption go? The book console moves it around the screen
     -- Zach's direct ask, 2026-07-21, "so the idle screen doesn't look
     frozen in the same layout every single time". The screensaver pinned it
     to the last row, centered, forever.

The screensaver cannot simply import the book game to get the first answer:
`crt-book-game.py` pulls in sqlite3 and urllib, and that window's entire
reason for existing is holding NO brain on a 1GB Pi (POTATO.md). Hence a
third module that imports nothing but the standard library's smallest
pieces, the same shape `crt_scan_line.py` took when the screensaver needed
the scan-line contract (2026-07-25, fifteenth cycle).

WHAT THIS RETIRES: `crt-book-game.py`'s own definitions of char_width /
display_width / cut_to_width / elide / wrap_to_width / center_text (now
re-exported from here under the same names, so `bg.center_text` keeps
working everywhere it is already written), and `crt-book-console.py`'s
private `_place_text` / `_row_runs` / `_pick_caption_row`.
"""
import random
import re
import unicodedata

# Where a caption may sit horizontally. Moving between these is half of
# "doesn't look frozen in the same layout" -- the row is the other half.
ALIGNMENTS = ("left", "center", "right")


def char_width(ch):
    """Terminal columns one character occupies.

    2 for East Asian Wide/Fullwidth, 0 for a combining mark, 1 otherwise.
    East Asian *Ambiguous* counts as 1, which is what tmux and essentially
    every non-CJK-locale terminal do with it.

    Exists because this project lays out fixed-width screens for a 40-column
    tube by counting CHARACTERS, and the two are not the same number the
    moment anything non-Latin appears. It appears already: the idle screen's
    own enticement lines are kaomoji ('(・∀・)  got a book nearby?'), and
    U+30FB KATAKANA MIDDLE DOT is Wide -- so a caption measured at exactly
    the 30-column budget was drawn 32 columns long and wrapped on the tube.
    Book titles are the other way in: Open Library will hand back a CJK or
    fullwidth title for a perfectly ordinary scan, and 'scan any book
    nearby' is the entire premise of this feature."""
    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def display_width(text):
    """Terminal columns `text` occupies -- see char_width()."""
    return sum(char_width(c) for c in text)


def cut_to_width(text, limit):
    """`text` cut to at most `limit` terminal COLUMNS (not characters).

    A wide character straddling the boundary is dropped rather than half-
    drawn, so the result can be one column short of `limit`; callers pad."""
    if limit <= 0:
        return ""
    out, w = [], 0
    for ch in text:
        cw = char_width(ch)
        if w + cw > limit:
            break
        out.append(ch)
        w += cw
    return "".join(out)


def elide(text, limit):
    """`text` cut to `limit` COLUMNS, ending in '..' when anything was removed.

    A hard cut is indistinguishable from a broken render, which on this
    console is a real cost: 'Nineteen Eighty-Four (PR6029' -- the closing
    paren eaten by a 28-character title budget -- reads as a fault, not as
    a long title. ASCII '..' rather than an ellipsis glyph, same choice
    crt-stt-solo.py's flash makes, because this lands on a CRT through a
    console font that may not have one."""
    if limit <= 0:
        return ""
    if display_width(text) <= limit:
        return text
    if limit <= 2:
        return cut_to_width(text, limit)
    return cut_to_width(text, limit - 2) + ".."


def wrap_to_width(text, limit, max_lines=None):
    """Word-wrap `text` into lines of at most `limit` COLUMNS.

    Unlike textwrap.wrap this measures in columns (see char_width) and keeps
    the whitespace runs between words, because on this console those runs are
    load-bearing: the enticement lines put a deliberate double space after
    their kaomoji face.

    `max_lines` folds everything past the limit back onto the last kept line
    and elides it, so a caption that did not fit always SAYS it did not fit
    rather than simply stopping. A single word wider than `limit` is elided
    on its own line.

    Added 2026-07-25: the idle caption was the one piece of text on these
    screens getting a hard single-line cut while the question beside it
    wrapped, and all six enticement lines are longer than the 30-column
    content budget -- so every one of them lost its ending, and four of the
    six lost the words 'scan'/'try it' entirely. The screen whose only job is
    to ask someone to scan a book had stopped asking."""
    if limit <= 0:
        return [""]
    parts = [p for p in re.split(r"(\s+)", text) if p]
    lines, cur, gap = [], "", ""
    for part in parts:
        if part.isspace():
            if cur:
                gap = part
            continue
        if cur and display_width(cur + gap + part) <= limit:
            cur = cur + gap + part
        else:
            if cur:
                lines.append(cur)
            cur = part if display_width(part) <= limit else elide(part, limit)
        gap = ""
    if cur:
        lines.append(cur)
    if not lines:
        return [""]
    if max_lines is not None and len(lines) > max_lines:
        kept = lines[:max_lines]
        # Rejoined and elided rather than dropped: the remainder guarantees
        # the line overflows, so '..' is always what the reader sees.
        kept[-1] = elide(" ".join([kept[-1]] + lines[max_lines:]), limit)
        lines = kept
    return lines


def center_text(text, width):
    """Pure centering helper -- pads `text` with leading/trailing spaces
    to `width`. Truncates (never wraps) text longer than width, since a
    single over-length line is a caller bug, not something this helper
    should silently multi-line.

    Measured in COLUMNS since 2026-07-25 (see char_width): padding a
    fullwidth book title by character count draws a line wider than the
    pane, which wraps and pushes the screen's own bottom row off the tube."""
    w = display_width(text)
    if w >= width:
        # Still padded after the cut: dropping a straddling wide character
        # can leave the line one column short, and every caller relies on
        # these being exactly `width` columns.
        text = cut_to_width(text, width)
        return text + " " * (width - display_width(text))
    pad = width - w
    left = pad // 2
    right = pad - left
    return (" " * left) + text + (" " * right)


def place_text(text, width, align):
    """Like center_text, but left/right too -- used to move a caption around
    the screen (2026-07-21, Zach: 'move around the screen with idle bait
    rather than render in center every time') instead of always the same
    horizontal position. Always exactly `width` columns."""
    text = cut_to_width(text, width)
    pad = width - display_width(text)
    if align == "left":
        return text + " " * pad
    if align == "right":
        return " " * pad + text
    left = pad // 2
    return " " * left + text + " " * (pad - left)


def row_runs(rows):
    """Pure function: sorted row numbers -> lists of CONSECUTIVE rows.

    A multi-row caption needs an unbroken stretch. Art sits in the vertical
    middle of both idle screens, so the free rows come in two blocks (above
    and below it) and 'pick a random free row' would happily start a 3-row
    caption one row above the art and write the other two straight through
    it."""
    runs = []
    for r in sorted(rows):
        if runs and r == runs[-1][-1] + 1:
            runs[-1].append(r)
        else:
            runs.append([r])
    return runs


def slots(runs, block_rows=1):
    """Every (row, align) a `block_rows`-tall caption can legally occupy.

    Runs too short for the block are dropped -- unless that leaves nothing at
    all, in which case they are all kept and the caller draws what fits (a
    screen too short for its own caption degrades instead of raising; never
    happens on the real tube)."""
    fitting = [run for run in runs if len(run) >= block_rows] or list(runs)
    out = []
    for run in fitting:
        for row in run[:max(1, len(run) - block_rows + 1)]:
            for align in ALIGNMENTS:
                out.append((row, align))
    return out


def pick_slot(runs, block_rows=1, rng=None, avoid=None):
    """A random (row, align) for a caption -- never `avoid`, if there is any
    other choice.

    `avoid` is the slot the caption is in RIGHT NOW. Excluding it is the
    difference between "randomised" and "visibly moved": an independent draw
    each time will re-pick the current slot every so often, and on a screen
    whose caption text is fixed (the screensaver's is) that repaint is
    indistinguishable from a dead process. Zach, on this feature, twice:
    "rather than just sitting static -- the actual point of this feature",
    "so the idle screen doesn't look frozen in the same layout every single
    time"."""
    rng = rng or random
    candidates = slots(runs, block_rows)
    if not candidates:
        return (0, "center")
    return rng.choice([s for s in candidates if s != avoid] or candidates)
