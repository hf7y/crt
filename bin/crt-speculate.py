#!/usr/bin/env python3
# PARKING-LOT.md's "speculative/optimistic response": an instant local
# filler shown while a request escalates to Claude (see crt-secretary.py's
# CRT_SECRETARY_SPECULATE wiring). Distinct from crt-predict.py (guesses
# what was SAID, not the answer). NOT an AI call; tests/test_speculate.py.
import random

# A handful of warm/curious-register lines (EXPRESSIVE-TONE.md's table),
# not one fixed phrase -- see tests/test_speculate.py's pool-size/variety
# cases. Deliberately short and content-free: this says nothing about
# what's being asked, only that something's happening.
FILLER_LINES = (
    "let me think on that...",
    "one sec, working on it...",
    "hm, give me a moment...",
    "on it...",
    "checking...",
)


def pick_filler_line(rng=None):
    """Pure function: a random instant filler line for the warm/curious
    register. No categorization by request content (a v1 simplification,
    not a broken promise -- PARKING-LOT.md's sketch floated per-category
    fillers as a nice-to-have, not a requirement; variety alone already
    avoids the single-canned-phrase problem)."""
    rng = rng or random
    return rng.choice(FILLER_LINES)
