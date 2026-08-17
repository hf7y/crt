#!/usr/bin/env python3
# Offline "which near-misses keep recurring" pass for the wake pool
# (2026-07-21, Zach's direct ask): crt-stt-solo.py's gate logs every
# ungated utterance that also missed the wake pool to
# CRT_WAKE_NEARMISS_LOG (one raw lowercased utterance per line). This
#   [rest: vault:crt/header-archaeology-20260817.md]
import os
import sys
from collections import Counter

NEARMISS_LOG = os.environ.get("CRT_WAKE_NEARMISS_LOG",
                                os.path.expanduser("~/.crt/wake-pool-nearmisses.log"))
MIN_REPEATS = int(os.environ.get("CRT_WAKE_TALLY_MIN_REPEATS", "2"))


def load_nearmiss_lines(path=None):
    """Tolerant read: missing file yields an empty list, never a crash."""
    path = path or NEARMISS_LOG
    try:
        with open(path) as f:
            return [ln.strip() for ln in f if ln.strip()]
    except OSError:
        return []


def tally_nearmisses(lines, min_repeats=2):
    """Pure function: counts exact-text repeats, returns (text, count)
    pairs at or above min_repeats, most frequent first. A single one-off
    near-miss is just noise; repetition is the same cheap local signal
    crt-stt-training-merge.py's generate_candidate_fixups() already uses
    for book-game mishears."""
    counts = Counter(lines)
    surfaced = [(text, n) for text, n in counts.items() if n >= min_repeats]
    surfaced.sort(key=lambda pair: (-pair[1], pair[0]))
    return surfaced


def main():
    top = None
    if "--top" in sys.argv:
        top = int(sys.argv[sys.argv.index("--top") + 1])
    lines = load_nearmiss_lines()
    surfaced = tally_nearmisses(lines, min_repeats=MIN_REPEATS)
    if top:
        surfaced = surfaced[:top]
    if not surfaced:
        print("No recurring wake-pool near-misses yet.")
        return
    print(f"Recurring near-misses (min {MIN_REPEATS} repeats) -- review, don't auto-add:")
    for text, count in surfaced:
        print(f"  {count:3d}x  {text}")


if __name__ == "__main__":
    main()
