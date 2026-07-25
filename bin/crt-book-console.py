#!/usr/bin/env python3
# Book Game's own tmux window -- wired into crt-console.sh alongside
# mono/bridge/stt. Reads scans from TWO sources and treats either as a
# real scan event: (1) ~/.crt/scanner.log (crt-scanner-feed.py's
# dexter-bridge path, SCANNER.md), and (2) this window's OWN STDIN --
# added 2026-07-21 after the hands-on agent confirmed LIVE on crt-vm that
# the scanner's raw USB-keyboard keystrokes land directly in whichever
# tmux window has focus (SCANNER.md's "2026-07-21 late session" finding),
# and that this window never read them, so a real scan on the `book`
# window silently did nothing. Stdin is now the PRIMARY path in practice
# (works with zero dexter/network dependency); scanner.log stays wired in
# case the dexter bridge is ever fixed later -- see .claude/FOCUS.md's
# "NEXT" entry for the full writeup of why this pivot happened.
#
# Deliberately DISPLAY-ONLY for this pass, same "standalone first, merge
# later" caution as BOOK-GAME.md's own roadmap: it shows the question,
# it does not grade a spoken answer directly (that's
# bin/crt-book-answer-listen.py's job, watching ~/.crt/stt.log
# separately, or `crt-book-game.py --answer` run by hand).
#
# STATUS: NOT hardware-verified past the hands-on agent's live
# confirmation that the GAP existed -- this fix itself (stdin reading)
# has not yet been watched working against a real scan. Tailing/parsing/
# rendering are pure functions covered by tests/test_book_console.py.
#
# FOCUS (2026-07-25): this window brings ITSELF to the front when a scan
# lands, and hands the tube back to the idle face when the question times
# out. It used to assume it always had focus -- true only while `book` was
# the boot-default window. The idle-lean layout (CRT_NO_IDLE_CLAUDE=1, live
# on potato) boots with the screensaver selected instead, so a scan drew
# its question onto a window nobody was looking at.
#
# Usage: crt-book-console.py   (run as its own tmux window, see
#   crt-console.sh's `book` window, now also the boot-default window)
# Env:
#   CRT_SCANNER_LOG (default ~/.crt/scanner.log)
#   CRT_BOOK_CONSOLE_IDLE_SECS (default 20) -- how long a scan result
#     stays on screen before falling back to the idle shelf display
#   CRT_BOOK_IDLE_ROTATE_SECS (default 8, 0 disables) -- how often the
#     resting screen redraws itself in a new position with a new caption
#   CRT_TMUX_SESSION / CRT_BOOK_WINDOW_NAME -- read via
#     crt-window-switcher.py, so both processes agree on which window this
#     is
#   CRT_IDLE_FACE_WINDOW -- the window to hand focus back to when a
#     question times out (set by crt-console.sh's idle-lean branch; empty
#     means this window is itself the idle face, and focus stays here)
import collections
import datetime
import importlib.util
import json
import os
import queue
import random
import sys
import threading
import time

BIN_DIR = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("crt_book_game", os.path.join(BIN_DIR, "crt-book-game.py"))
bg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bg)

_guard_spec = importlib.util.spec_from_file_location(
    "crt_loop_guard_for_book_console", os.path.join(BIN_DIR, "crt_loop_guard.py"))
loop_guard = importlib.util.module_from_spec(_guard_spec)
_guard_spec.loader.exec_module(loop_guard)

_scan_spec = importlib.util.spec_from_file_location(
    "crt_scan_line_for_book_console", os.path.join(BIN_DIR, "crt_scan_line.py"))
scan_line = importlib.util.module_from_spec(_scan_spec)
_scan_spec.loader.exec_module(scan_line)

# Loaded for its tmux-focus helpers, not its polling loop (which never runs
# here): that file is where this project keeps the "which window is which,
# and how do you move focus to it" knowledge, and a second copy of
# select-window-and-check-the-exit-status is exactly the drift the last two
# cycles have been paying off elsewhere.
_ws_spec = importlib.util.spec_from_file_location(
    "crt_window_switcher_for_book_console", os.path.join(BIN_DIR, "crt-window-switcher.py"))
window_switcher = importlib.util.module_from_spec(_ws_spec)
_ws_spec.loader.exec_module(window_switcher)

def _env_secs(name, default):
    """A seconds-valued env var, junk-tolerant. These names are set by
    crt-console.sh, i.e. by shell, and a bare float() on a misspelled value
    raises at IMPORT time -- before main() draws anything -- leaving a bash
    prompt on the one window that is the console's face. Same failure the
    game's own size vars were carrying until bg.detect_screen_size() grew
    _env_dim() last cycle. Negative is junk too; only 0 disables (see
    IDLE_ROTATE_SECS)."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        val = float(raw)
    except ValueError:
        return default
    return val if val >= 0 else default


SCANNER_LOG = os.path.expanduser(os.environ.get("CRT_SCANNER_LOG", "~/.crt/scanner.log"))
IDLE_SECS = _env_secs("CRT_BOOK_CONSOLE_IDLE_SECS", 20.0)
POLL_SECS = _env_secs("CRT_BOOK_CONSOLE_POLL_SECS", 0.5)
WAIT_HINT_SECS = _env_secs("CRT_BOOK_CONSOLE_WAIT_HINT_SECS", 8.0)
# How often the resting screen redraws itself. render_idle_screen() picks a
# fresh caption and a fresh position every call -- see its docstring, which
# quotes Zach on both halves -- and until 2026-07-25 main() called it once and
# then only on a scan's timeout, so the "rotating" idle-bait was a still frame
# from boot until somebody scanned. The thing it is there to talk them into.
# 8s: long enough to read a 30-character enticement twice, short enough that
# the screen is visibly alive. 0 disables (a tube that must hold one frame
# gets to -- same escape-hatch rule as CRT_AUDIO_DEV over device-by-name).
IDLE_ROTATE_SECS = _env_secs("CRT_BOOK_IDLE_ROTATE_SECS", 8.0)
# Which window is the idle face, when it is not this one. Set by
# crt-console.sh's idle-lean branch (CRT_NO_IDLE_CLAUDE=1 -> the potato
# screensaver on window 0), by the same `if` that selects it at boot, so
# the index is written once. Empty = this window IS the idle face (the
# historical layout), and there is nothing to hand the tube back to.
IDLE_FACE_WINDOW = os.environ.get("CRT_IDLE_FACE_WINDOW", "").strip()


# The scan-line contract itself moved to bin/crt_scan_line.py (2026-07-25):
# this window is no longer the only writer of scanner.log -- crt-screensaver.py
# forwards the scans that land on IT (see that file's header and crt_scan_line's).
# Re-exported under the same names rather than call sites updated: these are
# what tests/test_book_console.py and this file's own main() already say.
parse_scanner_log_line = scan_line.parse_scanner_log_line
parse_stdin_scan_line = scan_line.parse_stdin_scan_line
format_scan_log_line = scan_line.format_scan_log_line


def _place_text(text, width, align):
    """Pure function: like bg.center_text, but supports left/right
    alignment too -- used to move the idle caption around the screen
    (2026-07-21, Zach: 'move around the screen with idle bait rather
    than render in center every time') instead of always the same
    horizontal position.

    Measured in COLUMNS, not characters (2026-07-25, see bg.char_width):
    the enticement lines are kaomoji, and '(・∀・)' is 7 columns of 5
    characters -- so a caption cut to the 30-character content budget was
    padded as if it were 30 columns and drawn 32, wrapping on the tube."""
    text = bg.cut_to_width(text, width)
    pad = width - bg.display_width(text)
    if align == "left":
        return text + " " * pad
    if align == "right":
        return " " * pad + text
    left = pad // 2
    return " " * left + text + " " * (pad - left)


def render_idle_screen(book_count, width, height, rng=None):
    """Pure function: the resting display -- shelf art + a book count,
    per BOOK-GAME-STYLE.md's suggested 'shelf as a periodic flourish'
    use of the ASCII art library. Caption rotates between the plain
    count and a random enticement line (bg.pick_entice_line) so the
    resting screen actively invites a new scan rather than just sitting
    static -- the actual point of this feature, 2026-07-21 direction.

    Caption POSITION also moves around the screen (2026-07-21, Zach's
    direct ask) -- previously always the same fixed row directly under
    the shelf art, centered; now a random row (never overlapping the
    title or the art itself) and random left/center/right alignment each
    draw, so the idle screen doesn't look frozen in the same layout
    every single time.

    "Each draw" was doing no work until 2026-07-25: main() drew this screen at
    boot and then only when a scan timed out, so the resting screen picked one
    caption at one position and held it -- frozen in exactly the same layout
    every single time, which is what both paragraphs above exist to prevent.
    CRT_BOOK_IDLE_ROTATE_SECS is what calls this again."""
    rng = rng or random
    lines = [" " * width for _ in range(height)]
    lines[0] = bg.center_text("BOOK GAME", width)
    art = bg.get_ascii_art("shelf") or ""
    art_lines = art.splitlines()
    start = max(1, (height - len(art_lines)) // 2)
    art_rows = set()
    for i, l in enumerate(art_lines):
        row = start + i
        if 0 <= row < height:
            lines[row] = bg.center_text(l, width)
            art_rows.add(row)

    available_rows = [r for r in range(1, height) if r not in art_rows]
    align = rng.choice(("left", "center", "right"))
    caption = (bg.pick_entice_line(rng=rng) if rng.random() < 0.5
               else f"{book_count} book(s) registered -- scan one!")
    # HARD RULE (2026-07-21, Zach): never more than MAX_CONTENT_WIDTH
    # (30) columns of actual text, even on a wider screen -- entice
    # lines especially can run well past that.
    #
    # WRAPPED, not cut, since 2026-07-25. Every one of the six enticement
    # lines is longer than 30 columns, so a single-line cut took the end off
    # all six -- and with it the words "scan one", "try it?", "scan it" from
    # four of them. The resting screen's entire job is to ask for a scan and
    # it had been asking "( closed book ) -> ( scanner )". The question
    # screen beside it has wrapped its text all along (bg.render_question_
    # screen's textwrap call); this was the one line still being guillotined.
    def wrapped(rows):
        return bg.wrap_to_width(caption, bg.MAX_CONTENT_WIDTH, max_lines=rows)

    runs = _row_runs(available_rows)
    tallest = max((len(r) for r in runs), default=0)
    if tallest:
        # Shortened to the room actually available rather than written over
        # the art -- wrap_to_width elides what it drops, so a caption that
        # had to give something up says so.
        block = wrapped(min(CAPTION_MAX_ROWS, tallest))
        caption_row = _pick_caption_row(runs, len(block), rng)
    else:
        # A screen too short to have any free row (never on the real tube;
        # here so a small `height` degrades instead of raising).
        block = wrapped(1)
        caption_row = min(height - 1, start + len(art_lines) + 1)
    for i, l in enumerate(block):
        row = caption_row + i
        if 0 <= row < height:
            lines[row] = _place_text(l, width, align)
    return [bg.wrap_color(l, bg.COLOR_TITLE) for l in lines]


# The caption gets at most this many rows. Three covers the longest
# enticement line whole at a 30-column budget; a fourth would start
# crowding a 15-row tube that also holds a title and the shelf.
CAPTION_MAX_ROWS = 3


def _row_runs(rows):
    """Pure function: sorted row numbers -> lists of CONSECUTIVE rows.

    A multi-row caption needs an unbroken stretch. The shelf art sits in the
    vertical middle, so the free rows come in two blocks (above and below it)
    and 'pick a random free row' would happily start a 3-row caption one row
    above the art and write the other two straight through it."""
    runs = []
    for r in sorted(rows):
        if runs and r == runs[-1][-1] + 1:
            runs[-1].append(r)
        else:
            runs.append([r])
    return runs


def _pick_caption_row(runs, block_rows, rng):
    """Pure function: a random start row with `block_rows` consecutive free
    rows from it. Keeps the caption moving around the screen (2026-07-21,
    Zach) without ever landing on the art. Callers size the block to the
    tallest run first, so at least one run always fits."""
    candidates = [run for run in runs if len(run) >= block_rows]
    run = rng.choice(candidates or runs)
    return rng.choice(run[:max(1, len(run) - block_rows + 1)])


def scan_title(row, width):
    """Pure function: the title line for a scanned book -- '<title> (<lcc>)'
    when the call number fits, a shortened title with the call number intact
    when it doesn't, and the bare title when there isn't room for both.

    Composed against bg.title_budget() rather than handed over whole and
    truncated downstream (2026-07-25). Truncating the composed string is
    what produced 'Nineteen Eighty-Four (PR6029' on the tube -- a dangling
    open paren, which reads as a broken render rather than a long title.

    The call number is what gets protected when something has to give: the
    person is holding the book, so its name is the part they already know,
    and BOOK-GAME.md's resolved v1 decision was that this screen IS how the
    LCC gets shown at all (the physical-label option was demoted). Below
    MIN_TITLE_CHARS of title left, that trade stops being worth it and the
    call number goes instead -- a screen headed '.. (PR6029)' names nothing.
    """
    budget = bg.title_budget(width)
    title = row["title"]
    lcc = row.get("lcc")
    if not lcc:
        return bg.elide(title, budget)
    suffix = " (%s)" % lcc
    # Columns, not characters (2026-07-25): a CJK title is half as many
    # characters as it is columns, so len() said it fit, the composed line
    # went to center_text over-wide, and got cut -- reproducing the dangling
    # 'Nineteen Eighty-Four (PR6029' fragment this function exists to prevent,
    # for exactly the books whose titles this console cannot re-read at a
    # glance. Open Library returns them for perfectly ordinary scans.
    room = budget - bg.display_width(suffix)
    if room >= bg.display_width(title):
        return title + suffix
    if room >= MIN_TITLE_CHARS:
        return bg.elide(title, room) + suffix
    return bg.elide(title, budget)


# Below this many characters of the actual book title, keeping the LCC call
# number costs more than it's worth -- see scan_title().
MIN_TITLE_CHARS = 8


def render_scan_result(row, width, height, show_waiting_hint=False):
    """Pure function: the question screen for a freshly-scanned or
    already-registered book, colored in the warm/curious register
    (posing a question) per BOOK-GAME-STYLE.md. Title includes the
    best-effort LCC call number in parens when known -- BOOK-GAME.md's
    resolved v1 decision was "just display the computed LCC number on
    the CRT" instead of printing a physical label (Bluetooth-through-VM
    risk, demoted), but that decision was never actually wired into this
    screen until now; `crt-book-game.py`'s own CLI has printed it to
    stdout all along, this was the real console gap.

    `show_waiting_hint=True` overlays the `cat_reading` ASCII art into
    the bottom rows -- BOOK-GAME-STYLE.md named this exact pairing
    ("cat_reading while waiting on an answer") when the art library was
    built, but there was no real "waiting" period to attach it to until
    the hands-on agent wired `render_answer_result()` in (main() now
    genuinely sits on the question screen for a stretch before a graded
    answer lands, or doesn't). Overlaid onto the LAST rows of the
    already-rendered screen (usually blank padding below the centered
    question block) rather than a full re-layout -- a first-draft
    approximation that can overlap a very long wrapped question on a
    tall answer-options block; acceptable for a first pass, not
    reworked here."""
    questions = json.loads(row["questions_json"] or "[]")
    question = questions[0] if questions else {"text": "(no question on file)", "options": []}
    lines = bg.render_question_screen(scan_title(row, width), question, width, height)
    if show_waiting_hint:
        art_lines = (bg.get_ascii_art("cat_reading") or "").splitlines()
        start = height - len(art_lines)
        for i, art_line in enumerate(art_lines):
            row_i = start + i
            if 0 <= row_i < height:
                lines[row_i] = bg.center_text(art_line, width)
    return [bg.wrap_color(l, bg.COLOR_QUESTION) if l.strip() else l for l in lines]


def render_answer_result(title, row, width, height):
    """Pure function: shown on the book window itself right after a
    spoken answer gets graded. Found live 2026-07-21: grading already
    worked end to end (crt-book-answer-listen.py hears the answer,
    grades it, announces it), but the announcement only ever landed in
    ~/.crt/thoughts.log (the `mono` window) -- invisible to anyone
    actually watching `book`, which never reacted to a graded answer at
    all and just sat on the question forever. Same phrasing register as
    crt-book-answer-listen.py's format_result_line(), rendered as a full
    screen instead of a log line -- `correct_content is None` covers an
    ungradeable fallback question (nothing to grade, neutral ack)."""
    lines = [" " * width for _ in range(height)]
    lines[0] = bg.center_text("BOOK GAME", width)
    cw = bg.MAX_CONTENT_WIDTH  # HARD RULE 2026-07-21: cap actual text, not just line width
    if row.get("correct_content") is None:
        block = [bg.center_text(f"logged your answer for {title}."[:cw], width)]
        color = bg.COLOR_QUESTION
    elif row["correct_content"]:
        block = [
            bg.center_text("correct!", width),
            bg.center_text(f"{title}: {row['expected']}"[:cw], width),
        ]
        color = bg.COLOR_CORRECT
    else:
        block = [
            bg.center_text("nope.", width),
            bg.center_text(f"it was {row['expected']} -- {title}"[:cw], width),
        ]
        color = bg.COLOR_WRONG
    start = max(1, (height - len(block)) // 2)
    for i, l in enumerate(block):
        r = start + i
        if 0 <= r < height:
            lines[r] = l
    return [bg.wrap_color(l, color) if l.strip() else l for l in lines]


def render_scan_error(isbn, width, height):
    """Pure function: shown when a scan's ISBN lookup fails (unknown
    ISBN, network error -- see ScanLookupFailed). Clipped register
    (COLOR_WRONG, EXPRESSIVE-TONE.md) -- a real miss, not the warm/
    curious register a normal question gets, but still short and
    matter-of-fact per CLAUDE.md's terse-persona rule, not an alarming
    error dump. Same 3-line vertical-center shape render_question_screen
    uses, so the game's rhythm doesn't visually jolt on a miss."""
    lines = [" " * width for _ in range(height)]
    lines[0] = bg.center_text("BOOK GAME", width)
    block = [
        bg.center_text("couldn't find that book.", width),
        bg.center_text(f"(isbn {isbn})", width),
        bg.center_text("try another one!", width),
    ]
    start = max(1, (height - len(block)) // 2)
    for i, l in enumerate(block):
        row = start + i
        if 0 <= row < height:
            lines[row] = l
    return [bg.wrap_color(l, bg.COLOR_WRONG) if l.strip() else l for l in lines]


class ScanLookupFailed(Exception):
    """Raised by handle_scan() when fetch_book_metadata() itself failed
    (unknown ISBN -- a real 404 from Open Library, confirmed live against
    the real API -- or a network/timeout error). Deliberately a distinct
    exception type, not a bare re-raise of whatever urllib threw, so
    main() can catch exactly this and only this without accidentally
    swallowing a real bug elsewhere in handle_scan (e.g. a sqlite error)."""
    pass


def handle_scan(conn, isbn, fetcher=None, quote_fetcher=None, training_log_path=None):
    """Looks up/registers `isbn` if new, returns the registry row either
    way (register_book's own cache-on-insert semantics mean a re-scan
    never re-queries or re-generates a question, and never re-scrapes a
    quote). `quote_fetcher` is separate from `fetcher` since the Wikiquote
    scrape hits a different API shape than the Open Library lookup --
    tests inject each independently.

    Raises ScanLookupFailed (not whatever urllib raised) if the ISBN
    lookup itself fails -- confirmed live that Open Library 404s on an
    unrecognized ISBN (not a hypothetical: this is the EXPECTED outcome
    for a huge fraction of real scans, since the whole point of this
    feature is inviting someone to scan "any book nearby," and plenty of
    real barcodes -- out-of-print books, non-ISBN products, magazines,
    a network hiccup -- will never resolve. Previously uncaught here,
    which would have crashed the whole `book` window (now the
    boot-default tmux window) on the very first scan that didn't
    perfectly match Open Library's catalog -- the same failure class as
    the earlier missing-`random`-import crash, just guaranteed to
    recur constantly instead of being a one-off bug.

    `training_log_path` is injectable (default None -> bg.TRAINING_LOG,
    the real file) purely so tests can point the tier-decision read
    (see pick_response_tier()) at an isolated temp path instead of
    silently reading whatever's really in ~/.crt/book-game-training.jsonl
    on the machine running the suite -- same test-hermeticity class as
    the earlier ~/.crt/thoughts.log pollution fix."""
    existing = bg.get_book(conn, isbn)
    if existing is not None:
        # The row is cached; the SCAN is not. Without this, re-scanning a
        # book already on the shelf still put its question on the tube but
        # left no trace anywhere that a scan had just happened, so
        # crt-book-answer-listen.py -- which derives "a question is pending"
        # from a timestamp -- never graded the answer someone then spoke.
        return bg.touch_scan(conn, isbn) or existing
    try:
        book = bg.fetch_book_metadata(isbn, fetcher=fetcher)
    except Exception as e:
        raise ScanLookupFailed(str(e)) from e
    source = bg.pick_question_source()
    total_rounds, stt_accuracy = bg._recent_training_stats(training_log_path)
    tier = bg.pick_response_tier(total_rounds, stt_accuracy)
    question = bg.generate_template_question(book, tier=tier)
    quote = bg.scrape_quote(book["title"], fetcher=quote_fetcher)
    return bg.register_book(conn, book, questions=[question], question_source=source, quote=quote)


def draw(lines):
    sys.stdout.write("\x1b[H\x1b[2J")
    sys.stdout.write("\n".join(lines))
    sys.stdout.flush()


def tail_new_lines(path):
    """Generator: yields new lines appended to `path` as they arrive,
    starting from the current end of file (like `tail -f`, not `tail`) --
    only ever want scans that happen while this window is running, not a
    replay of every scan since the log began. Yields None (not just
    sleeping silently) on every empty poll too, so a caller can use each
    tick to check its own idle timeout regardless of whether a line
    actually arrived."""
    # Open (creating if absent) up front rather than polling
    # os.path.exists() first -- polling first has a real race, seeking to
    # the END of a file that appeared *between* the exists() check and
    # the open() would silently skip whatever was written in that gap
    # (hit exactly this in manual testing: a fast writer can create the
    # file with its first line already in it before this loop notices).
    # mkdir first: on a freshly-imaged VM ~/.crt/ may not exist yet even
    # though crt-scanner-feed.py itself always mkdir's before writing --
    # if THIS process is the first thing to touch ~/.crt/ (e.g. started
    # before any scan has ever landed), open(path, "a") alone raises
    # FileNotFoundError. Hit live 2026-07-21: the window showed nothing
    # but a blinking cursor because the traceback scrolled off a 15-row
    # tmux pane before anyone could read it -- see main()'s crash-log
    # wrapper below for the fix to THAT half of the problem too.
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a"):
        pass  # ensure it exists, without truncating/duplicating scanner.log's own writes
    # errors="replace": a barcode scanner is a keyboard-emulating device
    # and a bad read can put arbitrary bytes into scanner.log. Raised here
    # in the generator, a UnicodeDecodeError is outside main()'s LoopGuard
    # (which wraps the body only), and this is the window the console boots
    # selected -- one bad scan must not leave a bash prompt on the tube.
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        f.seek(0, os.SEEK_END)
        while True:
            line = f.readline()
            if line:
                yield line
            else:
                time.sleep(POLL_SECS)
                yield None


STDIN_DEAD = object()  # sentinel: see stdin_reader()
THOUGHT_LOG = os.path.expanduser(os.environ.get("CRT_THOUGHT_LOG", "~/.crt/thoughts.log"))


def parse_training_row(line):
    """Pure function: one book-game-training.jsonl line (see
    crt-book-game.py's log_training_row) -> the parsed dict, or None if
    the line is malformed/not a dict/missing 'isbn' -- tolerant, since a
    torn write (crash mid-append) shouldn't crash this reader."""
    try:
        row = json.loads(line)
    except ValueError:
        return None
    if not isinstance(row, dict) or "isbn" not in row:
        return None
    return row


def open_training_tail(path):
    """Opens book-game-training.jsonl positioned at end-of-file for a
    non-blocking per-tick readline() in main()'s own loop -- deliberately
    NOT tail_new_lines()'s generator shape (that one sleeps internally
    on an empty poll), since main() already ticks via SCANNER_LOG's own
    tail_new_lines and a second internally-sleeping generator would
    compound the poll interval every iteration for no benefit; a plain
    readline() against a regular file returns '' immediately with
    nothing new, no blocking involved."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a"):
        pass
    f = open(path, "r", encoding="utf-8", errors="replace")   # see tail_new_lines
    f.seek(0, os.SEEK_END)
    return f


def announce(line, log_path=None):
    """Best-effort append to ~/.crt/thoughts.log -- the channel
    crt-monologue.py renders on window 1, the one background window
    CLAUDE.md says is meant to be looked at. Same convention as every other
    logging write here: a broken log write must never stop the loop that is
    already dealing with a bigger problem. Written in the clipped/
    COLOR_WRONG register (a real problem, not a game event)."""
    log_path = log_path or THOUGHT_LOG
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a") as f:
            f.write(bg.wrap_color("  " + line, bg.COLOR_WRONG) + "\n")
    except OSError:
        pass


def warn_stdin_dead():
    """Surfaces the otherwise-invisible stdin_reader death (see its own
    docstring) on ~/.crt/thoughts.log -- the same channel crt-monologue.sh
    already tails -- in the clipped/COLOR_WRONG register (a real problem,
    not a game event). Best-effort: a broken log write must never crash
    the main loop that's already dealing with a bigger problem."""
    try:
        os.makedirs(os.path.dirname(THOUGHT_LOG), exist_ok=True)
        with open(THOUGHT_LOG, "a") as f:
            f.write(bg.wrap_color(
                "  stdin scan reader died -- scanning via keyboard/scanner "
                "stopped working (scanner.log fallback still active). "
                "restart the book window to recover.", bg.COLOR_WRONG) + "\n")
    except OSError:
        pass


def book_window_target():
    """'session:window' for this window itself, from the same two env vars
    crt-window-switcher.py resolves them from -- so "which window is the
    book window" has one answer across both processes."""
    return "%s:%s" % (window_switcher.SESSION, window_switcher.BOOK_WINDOW)


def should_release_tube(active_window, holding, idle_face_window=None,
                        book_window=None):
    """Pure function: may this window hand focus back to the idle face now
    that its question has timed out?

    Three conditions, and the middle one is the point. `idle_face_window`
    empty means this window IS the idle face (the historical layout) --
    there is nowhere to hand it back to. `holding` false means this window
    never took focus for the scan in the first place, so it has nothing to
    give. And `active_window` must still be this window: if someone walked
    up and switched to `mono` or `bookanswer` by hand mid-question, taking
    the tube off them would be exactly the yank crt-window-switcher.py's
    own decision function refuses to do."""
    idle_face_window = IDLE_FACE_WINDOW if idle_face_window is None else idle_face_window
    book_window = window_switcher.BOOK_WINDOW if book_window is None else book_window
    if not idle_face_window or not holding:
        return False
    return active_window == book_window


def focus_failure_report(target, detail):
    """Pure string builder, so the wording is testable without a tmux
    server. This is the honest version of the failure it describes: the
    question (or the answer screen) really did render, on a window nobody
    is looking at. Short -- it lands on a 40-column tube."""
    return "[!] scanned, but can't bring %s to the screen: %s" % (target, detail)


def stdin_reader(q):
    """Runs in a background thread: sys.stdin iteration blocks line by
    line (terminal cooked mode already buffers a scan's fast keystrokes
    until Enter, so this sees one complete line per scan, same as a
    human typing) -- pushes each raw line onto `q` for the main loop to
    drain non-blockingly, so a blocked stdin read can never stall the
    scanner.log tail or the idle-screen timeout tick.

    Without the try/finally below, this thread dying (stdin hits EOF --
    e.g. the tmux pane's stdin gets closed/reattached -- or any other
    read error) was a SILENT failure: the thread just ends, the main
    loop keeps running and looks perfectly healthy (idle/quote screens
    still rotate normally), but stdin-based scanning -- the primary scan
    path now, per the file header -- quietly stops working forever for
    the rest of this process's life, with zero visible indication.
    Pushing STDIN_DEAD lets main() surface that instead of it being
    invisible; it does not attempt to reopen/recover stdin, since once a
    pipe's closed there's generally nothing meaningful to reopen it to."""
    try:
        for line in sys.stdin:
            q.put(line)
    except Exception:
        # Suppressed, not re-raised -- a background reader thread dying
        # loudly wouldn't help anyone; STDIN_DEAD + warn_stdin_dead() is
        # the actual visibility mechanism, not a stderr traceback nobody
        # watching this pane's scrollback would see.
        pass
    finally:
        q.put(STDIN_DEAD)


def main():
    conn = bg.get_db()
    # Re-measured every tick below, not once here. crt-console.sh creates this
    # window with `tmux new-window -d` and only runs `exec tmux attach` at the
    # very end, after every window exists -- so this process starts inside a
    # DETACHED session, which tmux sizes 80x24 whatever the tube actually is.
    # Sizing once at startup cached that 80x24 for the life of the process, so
    # every screen this window draws (the shelf, the question, the graded
    # answer, a failed lookup) was laid out 80 wide and 24 tall and wrapped
    # itself into unreadable ribbon on the 40x15 tube -- and never recovered,
    # because nothing measured again.
    #
    # Third window to have this exact bug and the last one still holding it:
    # crt-screensaver.py was fixed on 2026-07-23 (re-read every frame) and
    # crt-monologue.py in 6aecc39. This is the one that draws the question.
    width, height = bg.detect_screen_size()
    # How to draw the screen currently on the tube, again, at whatever size
    # the tube turns out to be. Set by redraw() at every draw site; called
    # again when the measurement changes.
    current_frame = None

    def redraw(render):
        """Draw a frame and remember how to draw it at a different size.

        `render` takes (width, height) and returns the lines. Anything else
        it needs is bound at the call site as a default argument, not read
        from this scope on the repaint -- a question that has since timed
        out must not come back on a resize."""
        nonlocal current_frame
        current_frame = render
        draw(render(width, height))

    def book_count():
        return conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]

    stdin_q = queue.Queue()
    threading.Thread(target=stdin_reader, args=(stdin_q,), daemon=True).start()

    training_tail = open_training_tail(bg.TRAINING_LOG)
    pending_isbn = None  # isbn of the question currently on screen, if any
    pending_row = None   # that question's own row, kept around to redraw with the waiting hint
    hint_shown = False   # whether the cat_reading waiting hint has already fired for this question

    last_idle_draw_at = 0.0

    def draw_idle():
        nonlocal last_idle_draw_at
        redraw(lambda w, h: render_idle_screen(book_count(), w, h))
        last_idle_draw_at = time.time()

    draw_idle()
    last_scan_at = 0.0
    showing_idle = True
    holding_tube = False   # did THIS window take focus for the scan on screen?
    focus_reported = None  # last take-focus failure announced, once per cause

    def take_tube():
        """Bring this window to the front, because a scan just landed and
        the question is about to be drawn on it.

        The funnel assumed this could never be needed: `book` was the
        boot-default window, so it always had focus (crt-console.sh's own
        2026-07-21 note). The idle-lean layout (CRT_NO_IDLE_CLAUDE=1, live
        on potato) selects the screensaver instead, and nothing put the
        tube back -- so a scan drew its question onto a window nobody was
        looking at, and the tube kept showing a sleeping potato. Focus is
        also one hand-switch away from `mono` in EITHER layout.

        Not a yank: a scan is a deliberate physical act by the person
        standing at the console, and showing them the question is the thing
        they just asked for. Same posture crt-secretary.py already takes
        when an utterance escalates to Claude."""
        nonlocal holding_tube, focus_reported
        target = book_window_target()
        ok, detail = window_switcher.select_window(target)
        if ok:
            holding_tube = True
            focus_reported = None
        elif detail != focus_reported:
            # Once per distinct cause, not once per scan: this is the line
            # that tells someone their scan DID register and they simply
            # cannot see it, which is worth saying -- and worth saying only
            # once, since window 1 fades the person's own words out from
            # the top.
            focus_reported = detail
            announce(focus_failure_report(target, detail))

    def release_tube():
        """Hand the tube back to the idle face once the question has timed
        out, if this window took it and still holds it (see
        should_release_tube). A failed release is deliberately not
        announced: the consequence is that the tube stays on this window's
        own idle shelf screen, which is a perfectly good idle face and was
        the only one for most of this project's life -- nothing is lost or
        invisible, unlike a failed take."""
        nonlocal holding_tube
        if should_release_tube(window_switcher.get_active_window(), holding_tube):
            window_switcher.select_window("%s:%s" % (window_switcher.SESSION,
                                                     IDLE_FACE_WINDOW))
        holding_tube = False

    def show_scan(isbn):
        nonlocal last_scan_at, showing_idle, pending_isbn, pending_row, hint_shown
        try:
            row = handle_scan(conn, isbn)
        except ScanLookupFailed:
            redraw(lambda w, h, i=isbn: render_scan_error(i, w, h))
            pending_isbn = None
            pending_row = None
        else:
            redraw(lambda w, h, r=row: render_scan_result(r, w, h))
            pending_isbn = isbn
            pending_row = row
            hint_shown = False
        # After the draw either way -- a failed lookup ("couldn't find that
        # book") is just as invisible on an unfocused window as a question,
        # and leaves the person waiting on a tube that never changed.
        take_tube()
        last_scan_at = time.time()
        showing_idle = False

    def check_training_log():
        # Non-blocking: readline() on a regular file returns '' the
        # instant there's nothing new, never blocks. Drains everything
        # currently available each tick, same "don't starve" shape as
        # the stdin queue above.
        nonlocal last_scan_at, pending_isbn, pending_row
        while True:
            line = training_tail.readline()
            if not line:
                break
            row = parse_training_row(line)
            if row is None or row["isbn"] != pending_isbn:
                continue
            title_row = bg.get_book(conn, row["isbn"])
            title = title_row["title"] if title_row else row["isbn"]
            redraw(lambda w, h, t=title, r=row: render_answer_result(t, r, w, h))
            last_scan_at = time.time()
            pending_isbn = None  # only react once per active question
            pending_row = None

    def maybe_show_waiting_hint():
        # BOOK-GAME-STYLE.md named "cat_reading while waiting on an
        # answer" -- there was no real waiting period to attach it to
        # until render_answer_result existed (see that function's own
        # docstring). Fires once per question, WAIT_HINT_SECS after the
        # scan, without resetting last_scan_at -- the idle timeout still
        # counts from the original scan, showing the hint doesn't extend
        # how long the question stays on screen.
        nonlocal hint_shown
        if (pending_isbn is not None and not hint_shown
                and time.time() - last_scan_at >= WAIT_HINT_SECS):
            redraw(lambda w, h, r=pending_row:
                   render_scan_result(r, w, h, show_waiting_hint=True))
            hint_shown = True

    # Tracks scanner.log lines THIS process just wrote for a stdin-sourced
    # scan (see log_stdin_scan below) -- small bound since only ever a
    # couple writes are in flight before tail_new_lines catches up. Without
    # this, the write would come back around through tail_new_lines(
    # SCANNER_LOG) next iteration and get processed a SECOND time as if it
    # were an independent scan (double handle_scan() call, double
    # quote-scrape/Gemini-question-generation cost, wrong idle timing).
    self_written_lines = collections.deque(maxlen=8)

    def log_stdin_scan(isbn):
        line = format_scan_log_line(isbn)
        try:
            os.makedirs(os.path.dirname(SCANNER_LOG), exist_ok=True)
            with open(SCANNER_LOG, "a") as f:
                f.write(line)
            self_written_lines.append(line)
        except OSError:
            pass

    stdin_alive = True
    # tail_new_lines' own docstring points at "main()'s crash-log wrapper
    # below" as the fix for a traceback scrolling off this 15-row pane.
    # There was no such wrapper -- grep it, the comment outlived whatever
    # was meant to satisfy it. This is it, and it does two jobs at once on
    # the one window that IS the console's face (crt-console.sh boots with
    # `book` selected): the loop no longer ends on a single raising scan,
    # and the cause goes to window 1 in one short line instead of a
    # traceback nobody can read here.
    #
    # Everything reachable below can raise for reasons that are entirely
    # transient: book_count()/handle_scan()/get_book() all hit sqlite,
    # check_training_log() parses a file another process is appending to,
    # and draw() writes to a terminal. Losing the whole window to one of
    # those is much worse than losing one scan.
    # echo=False: draw() owns this pane's stdout (it homes the cursor and
    # clears, then paints), and a report printed into the middle of that
    # frame would sit on the tube until the next draw -- which, once the
    # idle screen is already up, may not come for a long time. The line
    # still reaches window 1, the window CLAUDE.md says is meant to be
    # looked at.
    guard = loop_guard.LoopGuard("book", echo=False)
    for line in tail_new_lines(SCANNER_LOG):
        with guard:
            check_training_log()
            maybe_show_waiting_hint()
            # Drain any stdin-sourced scans first, non-blocking -- stdin is
            # the primary path in practice now (see file header), scanner.log
            # is the fallback, so neither should starve the other.
            while stdin_alive:
                try:
                    stdin_line = stdin_q.get_nowait()
                except queue.Empty:
                    break
                if stdin_line is STDIN_DEAD:
                    warn_stdin_dead()
                    stdin_alive = False
                    break
                isbn = parse_stdin_scan_line(stdin_line)
                if isbn is not None:
                    log_stdin_scan(isbn)
                    show_scan(isbn)
                elif showing_idle:
                    # A non-ISBN-shaped line (bad scan, stray keystrokes, a
                    # library-card barcode, whatever) still gets echoed to the
                    # pane by the terminal's own cooked-mode echo -- draw()
                    # only runs on a recognized scan or the idle-timeout tick,
                    # so without this the stray text just sits there forever
                    # under the idle screen with no self-healing redraw. Only
                    # while idle: an unmatched line during an active question
                    # screen shouldn't interrupt it.
                    draw_idle()

            if line is not None:
                if line in self_written_lines:
                    self_written_lines.remove(line)
                else:
                    isbn = parse_scanner_log_line(line)
                    if isbn is not None:
                        show_scan(isbn)

            if not showing_idle and time.time() - last_scan_at >= IDLE_SECS:
                draw_idle()
                showing_idle = True
                release_tube()

            # The resting screen, again, somewhere else. render_idle_screen()
            # moves the caption and swaps between the book count and an
            # enticement line on every call, and nothing ever called it twice:
            # the console picked one layout at boot and held it until a scan
            # landed. Idle-bait is the funnel's FIRST link and it was a
            # photograph of itself.
            #
            # Guarded on showing_idle, so a question someone is reading is
            # never painted over -- the rotation belongs to the resting screen
            # only. draw_idle() restamps the clock, so the timeout branch above
            # and this one cannot double-draw in the same tick.
            elif showing_idle and IDLE_ROTATE_SECS and (
                    time.time() - last_idle_draw_at >= IDLE_ROTATE_SECS):
                draw_idle()

            # The tube's real geometry, asked again every tick (~POLL_SECS).
            # Cheap -- one ioctl, or one env read when crt-console.sh pins
            # CRT_COLS/CRT_ROWS -- and the only thing that ever corrects the
            # 80x24 this process was born believing. Repainting on the change
            # rather than only at the next draw matters because there may not
            # BE a next draw: in the historical layout `book` is the boot
            # default and its idle shelf screen is what the tube holds until
            # somebody scans something.
            size = bg.detect_screen_size()
            if size != (width, height):
                width, height = size
                if current_frame is not None:
                    draw(current_frame(width, height))


if __name__ == "__main__":
    main()
