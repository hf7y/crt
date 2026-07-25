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

SCANNER_LOG = os.path.expanduser(os.environ.get("CRT_SCANNER_LOG", "~/.crt/scanner.log"))
IDLE_SECS = float(os.environ.get("CRT_BOOK_CONSOLE_IDLE_SECS", "20"))
POLL_SECS = float(os.environ.get("CRT_BOOK_CONSOLE_POLL_SECS", "0.5"))
WAIT_HINT_SECS = float(os.environ.get("CRT_BOOK_CONSOLE_WAIT_HINT_SECS", "8"))
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
    horizontal position."""
    text = text[:width]
    pad = width - len(text)
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
    every single time."""
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
    caption_row = rng.choice(available_rows) if available_rows else min(height - 1, start + len(art_lines) + 1)
    align = rng.choice(("left", "center", "right"))
    caption = (bg.pick_entice_line(rng=rng) if rng.random() < 0.5
               else f"{book_count} book(s) registered -- scan one!")
    # HARD RULE (2026-07-21, Zach): never more than MAX_CONTENT_WIDTH
    # (30) characters of actual text, even on a wider screen -- entice
    # lines especially can run well past that.
    lines[caption_row] = _place_text(caption[:bg.MAX_CONTENT_WIDTH], width, align)
    return [bg.wrap_color(l, bg.COLOR_TITLE) for l in lines]


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
    title = f"{row['title']} ({row['lcc']})" if row.get("lcc") else row["title"]
    lines = bg.render_question_screen(title, question, width, height)
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
    width, height = bg.detect_screen_size()

    def book_count():
        return conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]

    stdin_q = queue.Queue()
    threading.Thread(target=stdin_reader, args=(stdin_q,), daemon=True).start()

    training_tail = open_training_tail(bg.TRAINING_LOG)
    pending_isbn = None  # isbn of the question currently on screen, if any
    pending_row = None   # that question's own row, kept around to redraw with the waiting hint
    hint_shown = False   # whether the cat_reading waiting hint has already fired for this question

    draw(render_idle_screen(book_count(), width, height))
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
            draw(render_scan_error(isbn, width, height))
            pending_isbn = None
            pending_row = None
        else:
            draw(render_scan_result(row, width, height))
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
            draw(render_answer_result(title, row, width, height))
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
            draw(render_scan_result(pending_row, width, height, show_waiting_hint=True))
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
                    draw(render_idle_screen(book_count(), width, height))

            if line is not None:
                if line in self_written_lines:
                    self_written_lines.remove(line)
                else:
                    isbn = parse_scanner_log_line(line)
                    if isbn is not None:
                        show_scan(isbn)

            if not showing_idle and time.time() - last_scan_at >= IDLE_SECS:
                draw(render_idle_screen(book_count(), width, height))
                showing_idle = True
                release_tube()


if __name__ == "__main__":
    main()
