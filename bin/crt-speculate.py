#!/usr/bin/env python3
# The "speculative/optimistic response" idea from PARKING-LOT.md: a cheap,
# instant, local filler line shown the moment a request is about to
# escalate to Claude, so the console feels alive during the real wait
# (wait_for_claude_reply()'s poll loop) -- see crt-secretary.py's
# CRT_SECRETARY_SPECULATE wiring for where this fires. Distinct from
# crt-predict.py (which guesses what was SAID); this guesses nothing about
# the answer's content. NOT an AI call. NOT hardware-verified --
# pick_filler_line() is pure and covered by tests/test_speculate.py.
import random

# A handful of warm/curious-register lines (EXPRESSIVE-TONE.md's table),
# not one fixed phrase -- repeating the exact same filler every time
# would read as a canned loading spinner, not a voice. Deliberately
# short and content-free: this says nothing about what's being asked,
# only that something's happening.
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
