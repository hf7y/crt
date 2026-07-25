#!/usr/bin/env python3
# The actual "STT training in the background" mechanism (2026-07-21,
# Zach's direct ask) -- until this file, generate_candidate_fixups()
# only ever printed candidates for a HUMAN to copy-paste into
# bin/stt-fixups.json by hand (crt-book-game-stats.py's export-fixups
# mode). This closes that loop: periodically re-computes candidates from
# the accumulated Book Game training log and merges new ones directly
# into the live stt-fixups.json, unattended.
#
# HONEST SCOPE NOTE, read before assuming this "trains the STT engine":
# stt-fixups.json today has exactly ONE consumer -- crt-stt-solo.py's
# addressed_to_console() wake-word gate, and even there ONLY entries
# whose "intent" equals the wake word ("claude") do anything at all (see
# that function). A Book-Game-derived entry like "friction" -> intent
# "fiction" is NOT a wake-word variant, so merging it changes nothing
# live today -- it's real, correct plumbing for whenever stt-fixups.json
# gets a broader consumer (e.g. a general mishear-correction layer), not
# a claim that book-game answer accuracy improves the moment this runs.
# What it DOES do usefully today: if the same mechanism ever surfaces a
# genuine wake-word variant (someone repeatedly says "claude" and it's
# consistently misheard as some new fragment), that candidate would
# auto-merge and become load-bearing for the gate immediately.
#
# Merged entries get "confidence": "auto" (a THIRD tier, distinct from
# hand-authored "confirmed" and export-fixups.py's manual-review
# "candidate") so a human glancing at the file can still tell what
# arrived unattended vs. what's actually been verified -- never silently
# upgrades an entry to "confirmed" on its own.
#
# NOT an AI call -- pure local JSON read/merge/write, same as everything
# else in this pipeline.
#
# STATUS: NOT hardware-verified against real accumulated training data
# (no real scan has been graded yet as of this writing). merge_candidates()
# is a pure function covered by tests/test_stt_training_merge.py.
#
# Usage: crt-stt-training-merge.py          # one merge pass, then exit
#        crt-stt-training-merge.py --loop    # repeat every MERGE_INTERVAL_SECS
# Env:
#   CRT_STT_FIXUPS (canonical) or CRT_STT_FIXUPS_PATH (legacy, still
#     honoured) -- default bin/stt-fixups.json, next to this script.
#     Resolved in bin/crt_config.py so the readers cannot disagree.
#   CRT_STT_TRAINING_MIN_REPEATS (default 2, same as generate_candidate_fixups)
#   CRT_STT_TRAINING_MERGE_INTERVAL_SECS (default 600, only used with --loop)
import importlib.util
import json
import os
import sys
import time

BIN_DIR = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("crt_book_game_stats", os.path.join(BIN_DIR, "crt-book-game-stats.py"))
stats = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stats)

_guard_spec = importlib.util.spec_from_file_location(
    "crt_loop_guard_for_training_merge", os.path.join(BIN_DIR, "crt_loop_guard.py"))
loop_guard = importlib.util.module_from_spec(_guard_spec)
_guard_spec.loader.exec_module(loop_guard)

_cfg_spec = importlib.util.spec_from_file_location(
    "crt_config_for_training_merge", os.path.join(BIN_DIR, "crt_config.py"))
crt_config = importlib.util.module_from_spec(_cfg_spec)
_cfg_spec.loader.exec_module(crt_config)

# Was os.environ.get("CRT_STT_FIXUPS_PATH", ...) -- its own spelling, which
# no reader of this file used. Both spellings now resolve here, canonical
# first; see bin/crt_config.py.
FIXUPS_PATH = crt_config.fixups_path()
MIN_REPEATS = int(os.environ.get("CRT_STT_TRAINING_MIN_REPEATS", "2"))
MERGE_INTERVAL_SECS = float(os.environ.get("CRT_STT_TRAINING_MERGE_INTERVAL_SECS", "600"))


def load_fixups_file(path):
    """Tolerant read -- missing/malformed file means 'start from empty',
    never a crash (same convention as crt-stt-solo.py's own load_fixups)."""
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def merge_candidates(existing, candidates):
    """Pure function: adds each candidate not already present as a key
    into `existing`, tagged confidence:"auto" (never touches or upgrades
    an entry that's already there, confirmed or otherwise -- a human's
    prior judgment always wins over an unattended merge). Returns
    (merged_dict, added_keys) so the caller knows whether a write is
    even needed."""
    merged = dict(existing)
    added = []
    for key, info in candidates.items():
        if key in merged:
            continue
        entry = dict(info)
        entry["confidence"] = "auto"
        merged[key] = entry
        added.append(key)
    return merged, added


def run_merge_pass(fixups_path=None, training_log_path=None, min_repeats=None):
    """One full pass: load current fixups, compute fresh candidates from
    the training log, merge, write back only if something actually
    changed. Returns the list of newly-added keys (empty if nothing
    new)."""
    fixups_path = fixups_path or FIXUPS_PATH
    min_repeats = min_repeats if min_repeats is not None else MIN_REPEATS
    rows = stats.load_training_rows(training_log_path)
    mismatches = stats.summarize_training(rows)["mismatches"]
    candidates = stats.generate_candidate_fixups(mismatches, min_repeats=min_repeats)

    existing = load_fixups_file(fixups_path)
    merged, added = merge_candidates(existing, candidates)
    if added:
        tmp_path = fixups_path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(merged, f, indent=2, sort_keys=True)
        os.replace(tmp_path, fixups_path)
    return added


def main():
    loop = "--loop" in sys.argv
    # The two modes want OPPOSITE failure behaviour, and before 2026-07-25
    # both got the one-shot's:
    #   - one-shot (a person or a script ran it): a raising pass must exit
    #     non-zero. Swallowing it would be an exit-0 no-op, which this
    #     project's build discipline names first.
    #   - --loop (the `stttrain` tmux window, every MERGE_INTERVAL_SECS for
    #     as long as the console is up): a raising pass must NOT end the
    #     loop. run_merge_pass() writes bin/stt-fixups.json, so ENOSPC on a
    #     Pi's SD card -- the realistic one -- used to end unattended STT
    #     learning for the rest of the console's uptime, silently, leaving
    #     a bash prompt in that window.
    # Since 0ccdf13 the wake gate re-reads that file live, so a merge that
    # keeps running now actually reaches the gate without a restart, which
    # is exactly why this loop surviving is worth more than it used to be.
    guard = loop_guard.LoopGuard("stttrain") if loop else None
    while True:
        if guard is None:
            report_merge(run_merge_pass())
        else:
            with guard:
                report_merge(run_merge_pass())
        if not loop:
            break
        time.sleep(MERGE_INTERVAL_SECS)


def report_merge(added):
    if added:
        print(f"[crt-stt-training-merge] auto-merged {len(added)} candidate(s): {', '.join(added)}")


if __name__ == "__main__":
    main()
