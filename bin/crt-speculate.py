#!/usr/bin/env python3
# The "speculative/optimistic response" idea from PARKING-LOT.md: show a
# cheap, instant, local filler line the moment a request is about to
# escalate to Claude, so the console feels alive during the real
# wait (`wait_for_claude_reply`'s poll loop, up to CLAUDE_MAX_WAIT
# seconds) instead of going silent. Distinct from bin/crt-predict.py
# (which predicts what was SAID, i.e. the STT text) -- this predicts
# nothing about the content of the answer, just acknowledges instantly
# in the warm/curious register (EXPRESSIVE-TONE.md) while the real one
# is on its way.
#
# Only worth using on the Claude-escalation path, not a locally-answered
# playbook -- a filler for something that already answers instantly is
# pointless (PARKING-LOT.md's own conclusion). See crt-secretary.py's
# CRT_SECRETARY_SPECULATE wiring for where this actually gets called.
#
# NOT an AI call -- pure local text, zero network/API cost, same
# "minimize live calls" spirit as everything else in this project.
#
# STATUS: NOT hardware-verified. pick_filler_line() is a pure function
# covered by tests/test_speculate.py; never watched on a real screen
# during a real Claude round-trip.
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
