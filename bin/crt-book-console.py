#!/usr/bin/env python3
# Book Game's own tmux window -- wired into crt-console.sh alongside
# mono/bridge/stt. Tails ~/.crt/scanner.log (crt-scanner-feed.py already
# writes every scan there unfiltered, SCANNER.md's "log first" pattern)
# for new ISBN-shaped lines, looks each one up/registers it via
# bin/crt-book-game.py's existing functions, and renders the centered
# question screen (BOOK-GAME-STYLE.md) directly to this window's pane.
#
# Deliberately DISPLAY-ONLY for this pass, same "standalone first, merge
# later" caution as BOOK-GAME.md's own roadmap: it shows the question,
# it does not grade a spoken answer (that still needs
# `crt-book-game.py --answer` run by hand, or a future secretary-
# playbook/window-0 wiring -- BOOK-GAME.md roadmap step 3, not this
# pass). This window's whole job is "the scan happened, here's what to
# ask" -- grading stays out of scope here.
#
# STATUS: NOT hardware-verified. Tailing/parsing/rendering are pure
# functions covered by tests/test_book_console.py against a fixture
# scanner.log; the live tail-follow loop and the real 40x15 terminal
# have never been checked by eye (same caveat as every other window in
# crt-console.sh).
#
# Usage: crt-book-console.py   (run as its own tmux window, see
#   crt-console.sh's `book` window)
# Env:
#   CRT_SCANNER_LOG (default ~/.crt/scanner.log)
#   CRT_BOOK_CONSOLE_IDLE_SECS (default 20) -- how long a scan result
#     stays on screen before falling back to the idle shelf display
import importlib.util
import json
import os
import sys
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
    (posing a question) per BOOK-GAME-STYLE.md."""
    questions = json.loads(row["questions_json"] or "[]")
    question = questions[0] if questions else {"text": "(no question on file)", "options": []}
    lines = bg.render_question_screen(row["title"], question, width, height)
    return [bg.wrap_color(l, bg.COLOR_QUESTION) if l.strip() else l for l in lines]


def handle_scan(conn, isbn, fetcher=None, quote_fetcher=None):
    """Looks up/registers `isbn` if new, returns the registry row either
    way (register_book's own cache-on-insert semantics mean a re-scan
    never re-queries or re-generates a question, and never re-scrapes a
    quote). `quote_fetcher` is separate from `fetcher` since the Wikiquote
    scrape hits a different API shape than the Open Library lookup --
    tests inject each independently."""
    existing = bg.get_book(conn, isbn)
    if existing is not None:
        return existing
    book = bg.fetch_book_metadata(isbn, fetcher=fetcher)
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


def main():
    conn = bg.get_db()
    width, height = bg.detect_screen_size()

    def book_count():
        return conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]

    draw(render_idle_screen(book_count(), width, height))
    last_scan_at = 0.0
    showing_idle = True

    for line in tail_new_lines(SCANNER_LOG):
        if line is not None:
            isbn = parse_scanner_log_line(line)
            if isbn is not None:
                row = handle_scan(conn, isbn)
                draw(render_scan_result(row, width, height))
                last_scan_at = time.time()
                showing_idle = False

        if not showing_idle and time.time() - last_scan_at >= IDLE_SECS:
            draw(render_idle_screen(book_count(), width, height))
            showing_idle = True


if __name__ == "__main__":
    main()
