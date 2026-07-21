#!/usr/bin/env python3
# Book Game idle-bait: pops a line into thoughts.log when the room's been
# quiet a while -- see BOOK-GAME-STYLE.md's "Idle-bait quotes" section.
# Mirrors bin/crt-idle-bait.sh's shape (poll, check quiet-time, append a
# line) but reuses bin/crt-book-game.py's registry/quote/entice logic
# instead of a hardcoded LINES array, and matches crt-idle-teaser.sh's
# ANSI color-per-register convention (EXPRESSIVE-TONE.md) instead of
# plain text.
#
# TWO REGISTERS, not one (2026-07-21 direction -- the actual point of
# this feature is enticing a NEW scan, not just admiring old ones):
#   - Enticement lines (bg.pick_entice_line): "come scan a book" nudges,
#     always available even with an empty registry -- an empty books.db
#     used to mean this script silently did nothing at all, a real gap
#     for a fresh install with zero scans yet.
#   - Quote lines (bg.pick_idle_quote): only once at least one book is
#     registered, celebrating what's already been scanned.
# Mixed via ENTICE_RATE so an established registry keeps getting pulled
# toward new scans instead of only ever showing off old ones.
#
# NON-API BY DESIGN: neither path ever calls Claude or hits the network
# at idle-bait time -- pick_idle_quote() only reads books.db (cached at
# scan time) or the small local FALLBACK_QUOTES pool, and pick_entice_line
# is pure static text.
#
# STATUS: NOT hardware-verified -- polling loop untested against a real
# quiet room. pick_and_format_line() is a pure function covered by
# tests/test_book_idle_bait.py.
#
# Usage: crt-book-idle-bait.py   (run as its own tmux pane/background loop)
# Env:
#   CRT_BOOK_ENTICE_RATE (default 0.4) -- fraction of idle-bait rounds
#     that show an enticement line instead of a quote, when the registry
#     is non-empty (always 1.0 when the registry IS empty -- nothing to
#     quote yet).
import importlib.util
import os
import random
import time

BIN_DIR = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("crt_book_game", os.path.join(BIN_DIR, "crt-book-game.py"))
bg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bg)

THOUGHT_LOG = os.path.expanduser(os.environ.get("CRT_THOUGHT_LOG", "~/.crt/thoughts.log"))
STT_LOG = os.path.expanduser(os.environ.get("CRT_STT_LOG", "~/.crt/stt.log"))
IDLE_SECS = int(os.environ.get("CRT_BOOK_IDLE_BAIT_SECS", "180"))
POLL_SECS = int(os.environ.get("CRT_BOOK_IDLE_BAIT_POLL", "10"))
ENTICE_RATE = float(os.environ.get("CRT_BOOK_ENTICE_RATE", "0.4"))


def pick_and_format_line(conn, rng=None):
    """Pure-ish (only touches the given conn): returns a colored idle-
    bait line -- an enticement nudge (warm/curious register, EXPRESSIVE-
    TONE.md) or a quote about an already-scanned book (wistful/quiet
    register), per the mixing rule in the file header. Never None: an
    empty registry always gets an enticement line instead of silently
    producing nothing."""
    rng = rng or random
    picked = bg.pick_idle_quote(conn, rng=rng)
    if picked is None or rng.random() < ENTICE_RATE:
        return bg.wrap_color("  " + bg.pick_entice_line(rng=rng), bg.COLOR_QUESTION)
    title, quote = picked
    line = f'  ~ "{quote}" -- {title}'
    return bg.wrap_color(line, bg.COLOR_QUOTE)


def append_thought_line(line):
    """Best-effort append to thoughts.log -- a broken write must never
    crash this loop (same convention as crt-secretary.py's
    log_fallthrough and crt-book-answer-listen.py's announce()).
    Previously this write sat directly in main()'s while-True loop with
    NO try/except at all -- a single failure (disk full, permission
    hiccup) would have silently killed this whole background idle-bait
    loop forever, the same invisible-failure shape as the stdin-reader
    and log_training_row bugs found in prior passes over this funnel."""
    try:
        os.makedirs(os.path.dirname(THOUGHT_LOG), exist_ok=True)
        with open(THOUGHT_LOG, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def main():
    conn = bg.get_db()
    while True:
        time.sleep(POLL_SECS)
        last = os.path.getmtime(STT_LOG) if os.path.exists(STT_LOG) else 0
        if time.time() - last < IDLE_SECS:
            continue
        line = pick_and_format_line(conn)
        append_thought_line(line)
        time.sleep(IDLE_SECS)


if __name__ == "__main__":
    main()
