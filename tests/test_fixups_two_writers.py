#!/usr/bin/env python3
# Two writers, one file (2026-07-25, twelfth nightly cycle).
#
# bin/stt-fixups.json is what this console has learned about how this room
# says its wake word, and it has two writers -- crt-calibration-game.py (a
# human confirming a mishear by ear) and crt-stt-training-merge.py's
# `stttrain` window (unattended, every 600s) -- plus a live reader, the wake
# gate itself, re-reading on every utterance since 0ccdf13. Since 24a94ac
# the two writers agree on which file they are writing.
#
# Both did read-modify-write-whole-file through a temp path named
# `<file>.tmp`. The same one. Two things follow:
#
#   LOST UPDATE. Each computes its new dict from a snapshot read moments
#   earlier and writes the WHOLE file. The later write silently drops
#   whatever the earlier one added -- and what the calibration game adds is
#   a human-confirmed wake-word alias, which this project cannot re-derive,
#   only re-earn by someone standing at the mic saying a word until it is
#   misheard the same way twice.
#
#   TORN FILE. open(tmp, "w") truncates. A merge tick landing inside a
#   calibration save truncates that save's half-written temp, and whichever
#   os.replace() runs puts the wreckage where the real file was.
#
# This file deliberately does NOT import bin/crt_fixups_store.py, so it runs
# against the parent as well as against the fix -- the point is what the two
# real writers do to one real file, not what a new module claims about it.
import importlib.util
import json
import os
import tempfile
import threading
import time
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN_DIR = os.path.join(REPO, "bin")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, os.path.join(BIN_DIR, path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_json(path):
    with open(path) as f:
        return json.load(f)


def read_raw(path):
    with open(path) as f:
        return f.read()


class TestTheTwoRealWriters(unittest.TestCase):
    def write_fixups(self, data):
        with open(self.path, "w") as f:
            json.dump(data, f)

    def game_save(self, fragment, target, similarity):
        """One confirmed mishear, saved the way the module at hand saves it.

        The parent has save_fixups(data, path) and does the read inline in
        offer_to_save(); the fix has save_fixup(fragment, ...), which does
        the read itself, inside the lock. Both mean "a human just confirmed
        this word" -- these tests are about what happens to the FILE, not
        about which name the function has, so the parent's own read-then-
        write sequence is reproduced here rather than skipped."""
        if hasattr(self.game, "save_fixup"):
            return self.game.save_fixup(fragment, target, similarity, self.path)
        try:
            with open(self.path) as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        data[fragment] = {
            "intent": target,
            "confidence": "confirmed",
            "type": "calibration-game",
            "note": "confirmed live via crt-calibration-game.py, %.0f%% similarity"
                    % (similarity * 100),
        }
        return self.game.save_fixups(data, self.path)

    """The defect where it actually lives: crt-calibration-game.py and
    crt-stt-training-merge.py, against one file. Fails against the parent,
    where each reads a snapshot and writes the whole file back."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "stt-fixups.json")
        self.merge = _load("crt_stt_training_merge_store", "crt-stt-training-merge.py")
        self.game = _load("crt_calibration_game_store", "crt-calibration-game.py")
        self.training_log = os.path.join(self._tmp.name, "training.jsonl")
        open(self.training_log, "w").close()
        self.candidates = {"friction": {"intent": "fiction",
                                        "type": "book-game-observed"}}
        self.merge.stats.generate_candidate_fixups = \
            lambda mismatches, min_repeats=2: dict(self.candidates)

    def test_a_merge_tick_does_not_erase_a_word_a_human_just_confirmed(self):
        # The realistic collision: someone is in the calibration game
        # confirming a mishear by ear at the moment the `stttrain` window's
        # 600s tick fires. A human-confirmed wake-word alias is the
        # strongest evidence this project collects and cannot be
        # re-derived -- only re-earned at the mic.
        self.write_fixups({"_comment": "keep me", "read about": {"intent": "ring the bell",
                                                          "confidence": "confirmed"}})
        saver = threading.Thread(
            target=self.game_save, args=("slide", "claude", 0.81))
        real_merge_candidates = self.merge.merge_candidates
        fired = []

        def merge_candidates_hook(existing, candidates):
            # Called after the read and before the write in BOTH shapes. In
            # the parent the saver runs to completion here, against no lock,
            # and the write below then clobbers it. Under the store the
            # saver blocks on the flock until this update finishes -- so it
            # is joined outside, never here, or the fixed version deadlocks
            # against itself.
            if not fired:
                fired.append(True)
                saver.start()
                time.sleep(0.05)
            return real_merge_candidates(existing, candidates)

        self.merge.merge_candidates = merge_candidates_hook
        try:
            self.merge.run_merge_pass(fixups_path=self.path,
                                      training_log_path=self.training_log)
        finally:
            self.merge.merge_candidates = real_merge_candidates
            saver.join(timeout=10)
        self.assertFalse(saver.is_alive())

        final = read_json(self.path)
        self.assertIn("slide", final)            # the human's confirmation
        self.assertIn("friction", final)         # the unattended merge
        self.assertIn("read about", final)       # what was already there
        self.assertIn("_comment", final)
        self.assertEqual(final["slide"]["confidence"], "confirmed")
        self.assertEqual(final["friction"]["confidence"], "auto")

    def test_both_writers_use_a_temp_name_no_other_process_can_share(self):
        seen = []
        real_replace = os.replace

        def spy(src, dst):
            seen.append(src)
            return real_replace(src, dst)

        os.replace = spy
        try:
            self.game_save("slide", "claude", 0.81)
            self.merge.run_merge_pass(fixups_path=self.path,
                                      training_log_path=self.training_log)
        finally:
            os.replace = real_replace
        self.assertEqual(len(seen), 2)
        for src in seen:
            self.assertTrue(src.endswith(".%d.tmp" % os.getpid()), src)

    def test_the_two_writers_agree_on_the_files_format(self):
        # They had drifted to indent 2 and indent 4, so whichever wrote last
        # reflowed the whole git-tracked file and buried its one real change.
        self.game_save("slide", "claude", 0.81)
        after_game = read_raw(self.path)
        self.merge.run_merge_pass(fixups_path=self.path,
                                  training_log_path=self.training_log)
        after_merge = read_raw(self.path)
        self.assertIn('\n  "slide"', after_game)
        self.assertIn('\n  "slide"', after_merge)
        self.assertTrue(after_game.endswith("}\n"))
        self.assertTrue(after_merge.endswith("}\n"))


if __name__ == "__main__":
    unittest.main()
