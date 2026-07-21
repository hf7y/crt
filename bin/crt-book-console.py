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
# Usage: crt-book-console.py   (run as its own tmux window, see
#   crt-console.sh's `book` window, now also the boot-default window)
# Env:
#   CRT_SCANNER_LOG (default ~/.crt/scanner.log)
#   CRT_BOOK_CONSOLE_IDLE_SECS (default 20) -- how long a scan result
#     stays on screen before falling back to the idle shelf display
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

SCANNER_LOG = os.path.expanduser(os.environ.get("CRT_SCANNER_LOG", "~/.crt/scanner.log"))
IDLE_SECS = float(os.environ.get("CRT_BOOK_CONSOLE_IDLE_SECS", "20"))
POLL_SECS = float(os.environ.get("CRT_BOOK_CONSOLE_POLL_SECS", "0.5"))


def parse_scanner_log_line(line):
    """Pure function: crt-scanner-feed.py writes 'ISO_TIMESTAMP\\tTEXT'
    per scan (unprefixed, unlike the tmux '[scan] ' delivery
    parse_scan_line() handles) -- pulls TEXT back out, or None if the
    line isn't tab-shaped or TEXT isn't ISBN-like."""
    line = line.rstrip("\n")
    if "\t" not in line:
        return None
    _, text = line.split("\t", 1)
    text = text.strip()
    return text if bg.is_isbn_like(text) else None


def parse_stdin_scan_line(line):
    """Pure function: a scan landing directly in this window's own stdin
    is bare digits + Enter -- the terminal's line-discipline (cooked
    mode) buffers the scanner's fast keystrokes and delivers them as one
    line on Enter, the same way a human pressing Enter would, no special
    handling needed on this end. No tab prefix to strip (unlike
    scanner.log's shape) -- just validate it's ISBN-shaped."""
    text = line.strip()
    return text if bg.is_isbn_like(text) else None


def render_idle_screen(book_count, width, height, rng=None):
    """Pure function: the resting display -- shelf art + a book count,
    per BOOK-GAME-STYLE.md's suggested 'shelf as a periodic flourish'
    use of the ASCII art library. Caption rotates between the plain
    count and a random enticement line (bg.pick_entice_line) so the
    resting screen actively invites a new scan rather than just sitting
    static -- the actual point of this feature, 2026-07-21 direction."""
    rng = rng or random
    lines = [" " * width for _ in range(height)]
    lines[0] = bg.center_text("BOOK GAME", width)
    art = bg.get_ascii_art("shelf") or ""
    art_lines = art.splitlines()
    start = max(1, (height - len(art_lines)) // 2)
    for i, l in enumerate(art_lines):
        row = start + i
        if 0 <= row < height:
            lines[row] = bg.center_text(l, width)
    caption_row = min(height - 1, start + len(art_lines) + 1)
    caption = (bg.pick_entice_line(rng=rng) if rng.random() < 0.5
               else f"{book_count} book(s) registered -- scan one!")
    lines[caption_row] = bg.center_text(caption[:width], width)
    return [bg.wrap_color(l, bg.COLOR_TITLE) for l in lines]


def render_scan_result(row, width, height):
    """Pure function: the question screen for a freshly-scanned or
    already-registered book, colored in the warm/curious register
    (posing a question) per BOOK-GAME-STYLE.md. Title includes the
    best-effort LCC call number in parens when known -- BOOK-GAME.md's
    resolved v1 decision was "just display the computed LCC number on
    the CRT" instead of printing a physical label (Bluetooth-through-VM
    risk, demoted), but that decision was never actually wired into this
    screen until now; `crt-book-game.py`'s own CLI has printed it to
    stdout all along, this was the real console gap."""
    questions = json.loads(row["questions_json"] or "[]")
    question = questions[0] if questions else {"text": "(no question on file)", "options": []}
    title = f"{row['title']} ({row['lcc']})" if row.get("lcc") else row["title"]
    lines = bg.render_question_screen(title, question, width, height)
    return [bg.wrap_color(l, bg.COLOR_QUESTION) if l.strip() else l for l in lines]


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


def handle_scan(conn, isbn, fetcher=None, quote_fetcher=None):
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
    recur constantly instead of being a one-off bug."""
    existing = bg.get_book(conn, isbn)
    if existing is not None:
        return existing
    try:
        book = bg.fetch_book_metadata(isbn, fetcher=fetcher)
    except Exception as e:
        raise ScanLookupFailed(str(e)) from e
    source = bg.pick_question_source()
    question = bg.generate_template_question(book)
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
    with open(path, "r") as f:
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

    draw(render_idle_screen(book_count(), width, height))
    last_scan_at = 0.0
    showing_idle = True

    def show_scan(isbn):
        nonlocal last_scan_at, showing_idle
        try:
            row = handle_scan(conn, isbn)
        except ScanLookupFailed:
            draw(render_scan_error(isbn, width, height))
        else:
            draw(render_scan_result(row, width, height))
        last_scan_at = time.time()
        showing_idle = False

    stdin_alive = True
    for line in tail_new_lines(SCANNER_LOG):
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
                show_scan(isbn)

        if line is not None:
            isbn = parse_scanner_log_line(line)
            if isbn is not None:
                show_scan(isbn)

        if not showing_idle and time.time() - last_scan_at >= IDLE_SECS:
            draw(render_idle_screen(book_count(), width, height))
            showing_idle = True


if __name__ == "__main__":
    main()
