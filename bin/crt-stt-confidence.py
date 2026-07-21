#!/usr/bin/env python3
# Decides, per recognized utterance, whether it still needs a Claude call to
# be understood/handled -- or whether this room's history has seen it (or its
# normalized shape) often enough that a local/cheap path can take it instead.
#
# THE IDEA (Zach, 2026-07-21, live voice session): at first, every utterance
# should go to Claude -- there's no local model yet. Over time, as specific
# utterance shapes recur (the same control phrases, the same handful of
# real requests this console actually gets), the probability of needing
# Claude for THAT SHAPE decays exponentially toward a floor (never to zero --
# an occasional re-check catches drift/hallucination in the local answer).
# Genuinely new/unseen phrasing always starts back at probability 1.0 --
# decay is per-key, not a blanket session-wide clock, so novelty is never
# silently swallowed just because the system as a whole has "matured".
#
# THIS FILE IS THE DECISION FUNCTION ONLY, not the router. It answers
# "should this utterance still cost a Claude call?" -- wiring that answer
# into an actual skip-Claude path is crt-secretary.py's job (its local-answer
# playbooks already exist; this is what should eventually gate whether they
# get tried before Claude, and let hit counts grow for playbooks that already
# handle a phrase correctly). See STT-CONFIDENCE.md for the full design and
# open questions (confirmation signal, decay constants, per-key vs semantic
# clustering).
#
# STATUS 2026-07-21: fresh scaffold, unit-tested against synthetic data
# (tests/test_stt_confidence.py) -- NOT yet wired into the live STT/secretary
# pipeline. Do that once the confirmation-signal question (see the doc) has
# a real answer, not before -- decaying based on an unconfirmed guess would
# just teach the system to be confidently wrong faster.
import json
import os
import re

STATE_PATH = os.environ.get("CRT_STT_CONFIDENCE_STATE",
                             os.path.expanduser("~/.crt/stt-confidence.json"))

# Tuned to feel right at "small repeated vocabulary" scale (see
# STT-MECHANISM.md) -- not measured against real traffic yet. After ~8
# confirmed hits on the same shape, call probability is already under 1%;
# the floor keeps a long-tail spot-check alive forever.
DECAY_RATE = 0.55
FLOOR_P = 0.03
INITIAL_P = 1.0

_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")


def normalize_key(text):
    """Same style of normalization as bin/stt-fixups.json's keys: lowercase,
    punctuation stripped, whitespace collapsed. Two utterances that normalize
    to the same key are treated as "the same shape" for decay purposes."""
    t = _PUNCT_RE.sub("", text.lower())
    return _WS_RE.sub(" ", t).strip()


def load_state(path=None):
    path = path or STATE_PATH
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state, path=None):
    path = path or STATE_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    os.replace(tmp, path)


def call_probability(key, state):
    """P(this utterance shape still needs Claude), given how many times it's
    been seen and confirmed-correct locally before. Unknown key -> 1.0."""
    entry = state.get(key)
    if not entry:
        return INITIAL_P
    hits = entry.get("confirmed_hits", 0)
    p = INITIAL_P * (DECAY_RATE ** hits)
    return max(FLOOR_P, p)


def should_call_claude(text, state, rng):
    """rng: anything with .random() -> [0,1), e.g. random.Random(seed) for
    deterministic tests, or the `random` module itself live."""
    key = normalize_key(text)
    return rng.random() < call_probability(key, state)


def record_confirmed(text, state):
    """Call after a local (non-Claude) handling of this utterance shape is
    confirmed correct -- e.g. the user didn't correct/repeat themselves, or
    an explicit confirmation signal fired. Increments the hit count, which is
    what actually drives the decay. See STT-CONFIDENCE.md: what counts as
    "confirmed" is still an open question, deliberately not answered here."""
    key = normalize_key(text)
    entry = state.setdefault(key, {"confirmed_hits": 0, "claude_hits": 0})
    entry["confirmed_hits"] += 1
    return state


def record_claude_call(text, state):
    """Call whenever an utterance shape actually went to Claude (whether by
    decision or because it's still new) -- separate counter from
    confirmed_hits so the state also tells you how much a shape has been
    SEEN, independent of whether it's been confirmed as locally-handleable
    yet."""
    key = normalize_key(text)
    entry = state.setdefault(key, {"confirmed_hits": 0, "claude_hits": 0})
    entry["claude_hits"] += 1
    return state


if __name__ == "__main__":
    import sys
    state = load_state()
    if len(sys.argv) > 1 and sys.argv[1] == "show":
        print(json.dumps(state, indent=2, sort_keys=True))
    else:
        print("Usage: crt-stt-confidence.py show", file=sys.stderr)
        sys.exit(1)
