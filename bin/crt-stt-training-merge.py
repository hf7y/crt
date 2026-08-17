#!/usr/bin/env python3
# The actual "STT training in the background" mechanism (2026-07-21,
# Zach's direct ask) -- until this file, generate_candidate_fixups()
# only ever printed candidates for a HUMAN to copy-paste into
# bin/stt-fixups.json by hand (crt-book-game-stats.py's export-fixups
#   [rest: vault:crt/header-archaeology-20260817.md]
import importlib.util
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

_store_spec = importlib.util.spec_from_file_location(
    "crt_fixups_store_for_training_merge", os.path.join(BIN_DIR, "crt_fixups_store.py"))
fixups_store = importlib.util.module_from_spec(_store_spec)
_store_spec.loader.exec_module(fixups_store)

# Was os.environ.get("CRT_STT_FIXUPS_PATH", ...) -- its own spelling, which
# no reader of this file used. Both spellings now resolve here, canonical
# first; see bin/crt_config.py.
FIXUPS_PATH = crt_config.fixups_path()
MIN_REPEATS = int(os.environ.get("CRT_STT_TRAINING_MIN_REPEATS", "2"))
MERGE_INTERVAL_SECS = float(os.environ.get("CRT_STT_TRAINING_MERGE_INTERVAL_SECS", "600"))


def load_fixups_file(path):
    """Tolerant read -- missing/malformed file means 'start from empty',
    never a crash (same convention as crt-stt-solo.py's own load_fixups).
    Thin alias for crt_fixups_store.read() since 2026-07-25; kept as a name
    because the tests and this file's own history use it."""
    return fixups_store.read(path)


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

    # The merge happens INSIDE crt_fixups_store.update()'s lock, against the
    # file as it is at that instant. Reading first and merging afterwards is
    # what let this loop's 600s tick silently drop a word a human had
    # confirmed by ear in the seconds between -- see that module's header.
    added = []

    def merge(existing):
        merged, new = merge_candidates(existing, candidates)
        added[:] = new
        return merged if new else None

    fixups_store.update(fixups_path, merge)
    return added


def main():
    loop = "--loop" in sys.argv
    # The two modes want OPPOSITE failure behaviour, and before 2026-07-25
    # both got the one-shot's:
    #   - one-shot (a person or a script ran it): a raising pass must exit
    #     non-zero. Swallowing it would be an exit-0 no-op, which this
    #   [rest: vault:crt/header-archaeology-20260817.md]
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
