#!/usr/bin/env python3
# Book Game idle-bait: pops a cached book quote into thoughts.log when
# the room's been quiet a while -- see BOOK-GAME-STYLE.md's "Idle-bait
# quotes" section. Mirrors bin/crt-idle-bait.sh's shape (poll, check
# quiet-time, append a line) but reuses bin/crt-book-game.py's registry
# and quote logic instead of a hardcoded LINES array, and matches
# crt-idle-teaser.sh's ANSI color-per-register convention (EXPRESSIVE-
# TONE.md) instead of plain text.
#
# NON-API BY DESIGN: pick_idle_quote() (crt-book-game.py) only ever reads
# books.db (cached at scan time) or the small local FALLBACK_QUOTES pool
# -- no network call, no Claude call, at idle-bait time. Every round's
# quote cost was already paid once, at scan time, not here.
#
# STATUS: NOT hardware-verified -- polling loop untested against a real
# quiet room. pick_and_format_quote_line() is a pure function covered by
# tests/test_book_game.py's TestIdleQuotes cases (via crt-book-game.py)
# plus this file's own formatting test.
#
# Usage: crt-book-idle-bait.py   (run as its own tmux pane/background loop)
import importlib.util
import os
import time

BIN_DIR = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("crt_book_game", os.path.join(BIN_DIR, "crt-book-game.py"))
bg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bg)

THOUGHT_LOG = os.path.expanduser(os.environ.get("CRT_THOUGHT_LOG", "~/.crt/thoughts.log"))
STT_LOG = os.path.expanduser(os.environ.get("CRT_STT_LOG", "~/.crt/stt.log"))
IDLE_SECS = int(os.environ.get("CRT_BOOK_IDLE_BAIT_SECS", "180"))
POLL_SECS = int(os.environ.get("CRT_BOOK_IDLE_BAIT_POLL", "10"))


def pick_and_format_quote_line(conn, rng=None):
    """Pure-ish (only touches the given conn): returns a colored,
    wistful/quiet-register idle-bait line, or None if the registry is
    empty. Kept separate from the polling loop so it's directly
    testable."""
    picked = bg.pick_idle_quote(conn, rng=rng)
    if picked is None:
        return None
    title, quote = picked
    line = f'  ~ "{quote}" -- {title}'
    return bg.wrap_color(line, bg.COLOR_QUOTE)


def main():
    conn = bg.get_db()
    while True:
        time.sleep(POLL_SECS)
        last = os.path.getmtime(STT_LOG) if os.path.exists(STT_LOG) else 0
        if time.time() - last < IDLE_SECS:
            continue
        line = pick_and_format_quote_line(conn)
        if line is None:
            continue
        os.makedirs(os.path.dirname(THOUGHT_LOG), exist_ok=True)
        with open(THOUGHT_LOG, "a") as f:
            f.write(line + "\n")
        time.sleep(IDLE_SECS)


if __name__ == "__main__":
    main()
