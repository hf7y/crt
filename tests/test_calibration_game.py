#!/usr/bin/env python3
# The calibration game's confirm prompt (2026-07-25, twenty-first cycle).
#
# bin/crt-calibration-game.py is the one place a HUMAN can teach the wake
# gate a new alias by ear -- FOCUS.md's second top-priority item, running
# live in tmux window 9 on potato -- and until this file it had no test at
# all.
#
# What it does with the answer is load-bearing. A saved entry goes into
# bin/stt-fixups.json at `"confidence": "confirmed"`, and crt-stt-solo.py's
# gate acts on any entry whose `intent` is the wake word with no further
# review (see crt_wake_gate.py). So the words the prompt will accept are
# effectively the words that can be wired into the live gate by typing.
#
# It accepted any word the tailer had EVER heard -- which, since the Tailer
# deliberately runs for the whole session (including through this blocking
# prompt), is every word said in the room since the game launched. The list
# on screen is bounded to real near-misses; the acceptance was not. Typing
# "about" -- 18% similar, never offered -- wrote it as a confirmed mishear
# of "claude", and the console then woke on "what is this book about".
#
# The two are now one thing: save_candidates() computes what is offered AND
# what is accepted, from a snapshot, so the set on screen and the set the
# answer is checked against cannot differ -- in content or in time.
import importlib.util
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN_DIR = os.path.join(REPO, "bin")


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(BIN_DIR, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class CalibrationGameTestCase(unittest.TestCase):
    """Each case gets its own fixups file, pointed at through the same env
    var crt_config.fixups_path() reads, so nothing here can touch a real
    ~/.crt or the repo's tracked bin/stt-fixups.json."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.fixups = os.path.join(self.tmp, "stt-fixups.json")
        self._env = dict(os.environ)
        os.environ["CRT_STT_FIXUPS"] = self.fixups
        os.environ["CRT_STT_LOG"] = os.path.join(self.tmp, "stt.log")
        self.game = _load("crt_calibration_game_under_test", "crt-calibration-game.py")
        self.gate = _load("crt_wake_gate_under_test", "crt_wake_gate.py")

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)

    def answer(self, seen, target, typed):
        """Run offer_to_save() with `typed` at the prompt, returning what it
        printed. stdin is the real input() path, not a stubbed function."""
        old_stdin = sys.stdin
        sys.stdin = io.StringIO(typed + "\n")
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                self.game.offer_to_save(seen, target)
        finally:
            sys.stdin = old_stdin
        return buf.getvalue()

    def on_disk(self):
        if not os.path.exists(self.fixups):
            return {}
        with open(self.fixups) as f:
            return json.load(f)


class OfferedCandidates(CalibrationGameTestCase):
    def test_a_near_miss_is_offered(self):
        self.assertEqual(
            [w for w, _ in self.game.save_candidates({"cloud": 0.80}, "claude")],
            ["cloud"])

    def test_an_unrelated_word_is_not_a_mishear(self):
        """0.18 is not a bad transcription of the wake word, it is a
        different word that happened to be said in the room."""
        self.assertEqual(self.game.save_candidates({"about": 0.18}, "claude"), [])

    def test_a_word_stt_already_got_right_is_not_offered(self):
        self.assertEqual(self.game.save_candidates({"claude": 1.0}, "claude"), [])
        self.assertEqual(self.game.save_candidates({"claud": 0.99}, "claude"), [])

    def test_best_match_first(self):
        seen = {"cloud": 0.80, "clyde": 0.55, "clawed": 0.66}
        self.assertEqual([w for w, _ in self.game.save_candidates(seen, "claude")],
                         ["cloud", "clawed", "clyde"])

    def test_the_list_is_bounded(self):
        seen = {"cl%02d" % i: 0.5 + i / 1000.0 for i in range(40)}
        self.assertEqual(len(self.game.save_candidates(seen, "claude")),
                         self.game.SAVE_LIMIT)


class WhatThePromptAccepts(CalibrationGameTestCase):
    def test_an_offered_word_saves_at_confirmed(self):
        out = self.answer({"cloud": 0.80}, "claude", "cloud")
        self.assertIn("Saved", out)
        entry = self.on_disk()["cloud"]
        self.assertEqual(entry["intent"], "claude")
        self.assertEqual(entry["confidence"], "confirmed")
        self.assertEqual(entry["type"], "calibration-game")

    def test_enter_skips_and_writes_nothing(self):
        out = self.answer({"cloud": 0.80}, "claude", "")
        self.assertIn("Skipped", out)
        self.assertEqual(self.on_disk(), {})

    def test_a_word_that_was_never_offered_is_refused(self):
        """The regression. "about" is in `seen` because someone said it in
        the room; it is not on the list; typing it must not reach the gate."""
        out = self.answer({"cloud": 0.80, "about": 0.18}, "claude", "about")
        self.assertNotIn("Saved", out)
        self.assertIn("not offered", out)
        self.assertEqual(self.on_disk(), {})

    def test_the_refusal_points_at_the_escape_hatch(self):
        out = self.answer({"cloud": 0.80, "about": 0.18}, "claude", "about")
        self.assertIn(self.game.FIXUPS_PATH, out)

    def test_case_and_whitespace_still_work(self):
        out = self.answer({"cloud": 0.80}, "claude", "  CLOUD  ")
        self.assertIn("Saved", out)
        self.assertIn("cloud", self.on_disk())

    def test_the_saved_similarity_is_the_one_that_was_shown(self):
        self.answer({"cloud": 0.80}, "claude", "cloud")
        self.assertIn("80%", self.on_disk()["cloud"]["note"])


class WhatReachesTheLiveGate(CalibrationGameTestCase):
    """The consequence, asked of crt_wake_gate.py itself rather than
    asserted about the JSON: this is what crt-stt-solo.py does with the file
    on the next utterance."""

    def test_an_unoffered_word_cannot_open_the_gate(self):
        self.answer({"cloud": 0.80, "about": 0.18}, "claude", "about")
        for utterance in ("what is this book about",
                          "tell me about the weather"):
            self.assertFalse(
                self.gate.addressed_to_console(utterance, "claude", self.on_disk()),
                "%r woke the console" % utterance)

    def test_a_confirmed_near_miss_still_does(self):
        """The feature the game exists for is untouched."""
        self.answer({"cloud": 0.80}, "claude", "cloud")
        self.assertTrue(self.gate.addressed_to_console(
            "cloud what is this book about", "claude", self.on_disk()))


class TheListDoesNotRaceTheTailer(CalibrationGameTestCase):
    """The Tailer thread adds to `seen` for the entire session on purpose --
    a round boundary is exactly when a slow whisper round-trip lands -- so
    the dict handed to offer_to_save() grows while a human reads and types."""

    def test_candidates_survive_a_dict_that_is_still_growing(self):
        seen = {"cloud": 0.80}
        stop = threading.Event()

        def churn():
            # Add and drop within a bounded key space: the size has to keep
            # CHANGING (that is what raises), but an unbounded dict would
            # just make the snapshot slow rather than test anything.
            i = 0
            while not stop.is_set():
                seen["word%d" % (i % 64)] = 0.5
                seen.pop("word%d" % ((i + 32) % 64), None)
                i += 1

        writer = threading.Thread(target=churn, daemon=True)
        writer.start()
        try:
            for _ in range(2000):
                # RuntimeError: dictionary changed size during iteration --
                # the crash would land on the one call that matters, right
                # as the round's findings are about to be offered.
                self.game.save_candidates(seen, "claude")
        finally:
            stop.set()
            writer.join(timeout=5)

    def test_a_word_arriving_after_the_list_is_not_acceptable(self):
        """Same seam in time rather than in content: what is accepted is the
        snapshot that was printed, not whatever the room has said since."""
        seen = {"cloud": 0.80}
        candidates = self.game.save_candidates(seen, "claude")
        seen["clawed"] = 0.66
        self.assertEqual([w for w, _ in candidates], ["cloud"])


if __name__ == "__main__":
    unittest.main()
