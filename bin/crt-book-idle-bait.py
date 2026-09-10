#!/usr/bin/env python3
# Book Game idle-bait: pops a line into thoughts.log when the room's been
# quiet a while -- see BOOK-GAME-STYLE.md's "Idle-bait quotes" section.
# Mirrors bin/crt-idle-bait.sh's shape (poll, check quiet-time, append a
# line) but reuses bin/crt-book-game.py's registry/quote/entice logic --
# see tests/test_book_idle_bait.py.
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
# Junk-tolerant (env_number's own docstring covers why): a bare int()/float()
# here used to raise at IMPORT on one shell typo, killing this window with
# `; exec bash` in its place. Witnessed by test_config_fixups_path.py's
# TestATypoDoesNotTakeAWindowDown::test_the_idle_bait_window_still_loads_at_its_defaults.
IDLE_SECS = crt_config.env_number("CRT_BOOK_IDLE_BAIT_SECS", 180.0)
# Positive floor, not 0 -- a poll interval on the sole mic reader's box must
# not become a hot while-True. env_number's docstring covers the general
# rule; TestEnvNumber::test_a_positive_floor_rejects_zero witnesses it here.
POLL_SECS = crt_config.env_number("CRT_BOOK_IDLE_BAIT_POLL", 10.0, minimum=0.1)
ENTICE_RATE = crt_config.env_number("CRT_BOOK_ENTICE_RATE", 0.4)
# THIRD register (2026-07-28, Zach-directed): bg.pick_bibquotes_line()
# reads a LOCAL cache of bibliothecaire's quotes.txt, synced separately by
# bin/crt-bibquotes-sync.sh -- see tests/test_bibquotes.py for the no-network
# rule. Fraction of quote-shaped rounds that pull from bibquotes instead of
# a registered book's own quote when BOTH are available; with an empty
# registry, bibquotes fills the "quote" register on its own regardless of
# this rate -- witnessed by
# TestIdleBaitMixesInBibquotes::test_empty_registry_still_shows_bibquotes_regardless_of_mix_rate.
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
    # of this loop; the rest of the body never got it. The guard now wraps
    # the whole body, not just the log
    # write.
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
