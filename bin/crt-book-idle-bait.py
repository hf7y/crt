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

_guard_spec = importlib.util.spec_from_file_location(
    "crt_loop_guard_for_book_idle", os.path.join(BIN_DIR, "crt_loop_guard.py"))
loop_guard = importlib.util.module_from_spec(_guard_spec)
_guard_spec.loader.exec_module(loop_guard)

_cfg_spec = importlib.util.spec_from_file_location(
    "crt_config_for_book_idle", os.path.join(BIN_DIR, "crt_config.py"))
crt_config = importlib.util.module_from_spec(_cfg_spec)
_cfg_spec.loader.exec_module(crt_config)

THOUGHT_LOG = os.path.expanduser(os.environ.get("CRT_THOUGHT_LOG", "~/.crt/thoughts.log"))
STT_LOG = os.path.expanduser(os.environ.get("CRT_STT_LOG", "~/.crt/stt.log"))
# Junk-tolerant since 2026-07-25 (twentieth cycle). These were bare
# int()/float() calls at module scope, so one typo in a value crt-console.sh
# passes from shell raised at IMPORT -- taking down the funnel's FIRST link
# before it ever ran, with `; exec bash` leaving a prompt in its place and no
# bait, no scan, no question and no training row after it. The two windows
# further down the funnel were fixed for exactly this in earlier cycles; this
# is the one that was still carrying it. See bin/crt_config.py's env_number.
IDLE_SECS = crt_config.env_number("CRT_BOOK_IDLE_BAIT_SECS", 180.0)
# A positive floor, not 0: this one is a POLL interval, and zero here is not
# an escape hatch, it is a hot while-True on a 1GB Pi that is also the sole
# mic reader's box. Nothing else in this file has that shape.
POLL_SECS = crt_config.env_number("CRT_BOOK_IDLE_BAIT_POLL", 10.0, minimum=0.1)
ENTICE_RATE = crt_config.env_number("CRT_BOOK_ENTICE_RATE", 0.4)
# THIRD register (2026-07-28, Zach-directed: "idlebait also show page92
# excerpts via \\192.168.0.27\bibquotes") -- bg.pick_bibquotes_line()
# reads a LOCAL cache of bibliothecaire's published quotes.txt (synced
# separately by bin/crt-bibquotes-sync.sh; NEVER hits the network from
# here, same NON-API-BY-DESIGN rule as pick_idle_quote() above). Fraction
# of quote-shaped rounds (i.e. rounds that already passed the entice
# check) that pull from bibquotes instead of a registered book's own
# quote, when BOTH are available. When the registry is empty but
# bibquotes has content, bibquotes fills the "quote" register on its
# own -- an empty scan history no longer means only enticements ever
# show.
BIBQUOTES_RATE = crt_config.env_number("CRT_BOOK_BIBQUOTES_RATE", 0.3)


def pick_and_format_line(conn, rng=None):
    """Pure-ish (only touches the given conn, and bg.BIBQUOTES_LOCAL_PATH
    for a local file read): returns a colored idle-bait line -- an
    enticement nudge (warm/curious register, EXPRESSIVE-TONE.md), a quote
    about an already-scanned book, or a bibliothecaire page-92 excerpt
    (both wistful/quiet register), per the mixing rule in the file
    header. Never None: with nothing to quote at all (empty registry AND
    no bibquotes cache), always gets an enticement line instead of
    silently producing nothing."""
    rng = rng or random
    picked = bg.pick_idle_quote(conn, rng=rng)
    bibquote = bg.pick_bibquotes_line(rng=rng)
    have_quote_source = picked is not None or bibquote is not None
    if not have_quote_source or rng.random() < ENTICE_RATE:
        return bg.wrap_color("  " + bg.pick_entice_line(rng=rng), bg.COLOR_QUESTION)
    # Both available: mix via BIBQUOTES_RATE. Only one available: use it,
    # no dice roll needed.
    if bibquote is not None and (picked is None or rng.random() < BIBQUOTES_RATE):
        quote, attribution = bibquote
        line = f'  ~ "{quote}" -- {attribution}'
    else:
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
    # append_thought_line() above already learned this lesson for ONE line
    # of this loop; the rest of the body never got it. Still unguarded
    # until 2026-07-25: pick_and_format_line() reaches sqlite through
    # pick_idle_quote(), and the getmtime() below is a plain
    # exists-then-stat race -- stt.log removed between the two raises
    # FileNotFoundError. Either one ended idle-bait, which is step ONE of
    # the funnel: no bait, no scan, no question, no training row.
    # The loop's own POLL_SECS sleep is deliberately INSIDE the guard's
    # reach only in the sense that it runs first -- pacing is unchanged
    # whether the body raises or not.
    guard = loop_guard.LoopGuard("bookidle")
    while True:
        time.sleep(POLL_SECS)
        with guard:
            last = os.path.getmtime(STT_LOG) if os.path.exists(STT_LOG) else 0
            if time.time() - last < IDLE_SECS:
                continue
            line = pick_and_format_line(conn)
            append_thought_line(line)
            time.sleep(IDLE_SECS)


if __name__ == "__main__":
    main()
