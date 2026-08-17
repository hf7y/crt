#!/usr/bin/env python3
# The calibration game's confirm prompt (2026-07-25, twenty-first cycle).
#
# bin/crt-calibration-game.py is the one place a HUMAN can teach the wake
# gate a new alias by ear -- FOCUS.md's second top-priority item, running
#   [rest: vault:crt/header-archaeology-20260817.md]
import importlib.util
import io
import json
import os
import sys
import tempfile
import time
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
        # Every path this module resolves at import is pinned inside tmp,
        # INCLUDING the defaults. Writing a real ~/.crt/earcon-routing.jsonl
        # from the suite is the thing cycle 20 caught the hard way -- and it
        # happened again while this file was being written, which is why the
        # pin is here in the base class rather than in the cases that write.
        os.environ["CRT_EARCON_ROUTING_LOG"] = os.path.join(self.tmp, "default-routing.jsonl")
        os.environ["CRT_THOUGHT_LOG"] = os.path.join(self.tmp, "thoughts.log")
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


class TheEarconRound(CalibrationGameTestCase):
    """The round exists so device routing can be re-checked without a
    hands-on session. Two things stopped it being one: it could not tell a
    tone that failed to play from a tone nobody heard -- and it asked a
    HUMAN to render that verdict -- and the answer it called "logged" was
    never written anywhere.

    crt-earcon.sh is driven for real here (it is a real script, and on a box
    with no sox it really does exit 1), rather than stubbed."""

    def setUp(self):
        super().setUp()
        self.routing = os.path.join(self.tmp, "earcon-routing.jsonl")

    def run_round(self, answers):
        old_stdin = sys.stdin
        sys.stdin = io.StringIO("\n".join(answers) + "\n")
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                self.game.earcon_round(self.routing)
        finally:
            sys.stdin = old_stdin
        return buf.getvalue()

    def rows(self):
        if not os.path.exists(self.routing):
            return []
        with open(self.routing) as f:
            return [json.loads(ln) for ln in f if ln.strip()]

    def test_a_failed_play_is_reported_not_asked_about(self):
        """No sox on this box, so the real crt-earcon.sh exits 1. The round
        must say so and must NOT ask whether it was heard."""
        played, detail = self.game.play_earcon("addressed", "tv")
        if played:
            self.skipTest("this box can actually play audio; see the loopback test")
        out = self.run_round(["", ""])          # two Enters, no verdicts typed
        self.assertIn("nothing played", out)
        self.assertNotIn("Did you hear it", out)
        self.assertEqual([r["played"] for r in self.rows()], [False, False])
        self.assertEqual([r["intended"] for r in self.rows()], ["tv", "handset"])
        for row in self.rows():
            self.assertIsNone(row["reported"])
            self.assertTrue(row["detail"], "a failure with no reason is the old behaviour")

    def test_play_earcon_reports_the_reason(self):
        """Whatever crt-earcon.sh said on its way out, not just a code. Which
        reason depends on the box (no sox here, "unknown name" where there
        is one) -- both carry the script's own prefix, and both used to go
        to /dev/null."""
        played, detail = self.game.play_earcon("no-such-earcon", "tv")
        self.assertFalse(played)
        self.assertIn("crt-earcon", detail)

    def test_play_earcon_survives_a_missing_script(self):
        self.game.EARCON_BIN = os.path.join(self.tmp, "not-here.sh")
        played, detail = self.game.play_earcon("addressed", "tv")
        self.assertFalse(played)
        self.assertTrue(detail)

    def test_a_verdict_is_written_down(self):
        self.assertTrue(self.game.record_routing("tv", True, "handset", "",
                                                 self.routing))
        row, = self.rows()
        self.assertEqual(row["intended"], "tv")
        self.assertEqual(row["reported"], "handset")
        self.assertTrue(row["played"])
        self.assertTrue(row["at"])

    def test_verdicts_accumulate_rather_than_replace(self):
        self.game.record_routing("tv", True, "tv", "", self.routing)
        self.game.record_routing("handset", True, "nowhere", "", self.routing)
        self.assertEqual([r["intended"] for r in self.rows()], ["tv", "handset"])

    def test_a_bare_filename_is_a_path_too(self):
        """os.makedirs("") raises, so a relative CRT_EARCON_ROUTING_LOG
        would have reported "could not write" for no reason."""
        cwd = os.getcwd()
        os.chdir(self.tmp)
        try:
            self.assertTrue(self.game.record_routing("tv", True, "tv", "",
                                                     "bare.jsonl"))
        finally:
            os.chdir(cwd)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "bare.jsonl")))

    def test_a_log_it_cannot_write_is_not_called_logged(self):
        unwritable = os.path.join(self.tmp, "a-file", "routing.jsonl")
        open(os.path.join(self.tmp, "a-file"), "w").close()
        buf = io.StringIO()
        with redirect_stdout(buf):
            ok = self.game.record_routing("tv", True, "tv", "", unwritable)
        self.assertFalse(ok)
        self.assertIn("could not write", buf.getvalue())


class TheTailerKeepsListening(CalibrationGameTestCase):
    """What it reads is TRANSCRIBED SPEECH -- accented names and whisper's
    smart quotes are ordinary content, not an edge case -- and it reads it
    while crt-stt-solo.py appends. Landing inside a multi-byte character
    raised UnicodeDecodeError, a ValueError, which the `except OSError`
    around the read does not catch. In a thread that kills the thread and
    nothing else: the game goes on prompting, the round still ends, and
    "Nothing worth saving" is what a person gets for standing at the mic.

    ae54ef4 swept four readers of this class. This one reads the same
    ~/.crt/stt.log the same way and was not among them."""

    def setUp(self):
        super().setUp()
        self.log = os.environ["CRT_STT_LOG"]
        with open(self.log, "wb") as f:
            f.write(b"12:00:00  potato\n")

    def append(self, raw):
        with open(self.log, "ab") as f:
            f.write(raw)

    def start(self, target="potato"):
        tailer = self.game.Tailer(target)
        tailer.pos = 0
        buf = io.StringIO()
        self._redirect = redirect_stdout(buf)
        self._redirect.__enter__()
        self.addCleanup(tailer.stop)
        self.addCleanup(self._redirect.__exit__, None, None, None)
        tailer.run()
        self.buf = buf
        return tailer

    def settle(self, tailer, want, tries=40):
        for _ in range(tries):
            if want in tailer.seen:
                return True
            time.sleep(0.1)
        return want in tailer.seen

    def test_a_torn_character_does_not_end_the_thread(self):
        tailer = self.start()
        self.assertTrue(self.settle(tailer, "potato"))
        self.append(b"12:00:01  caf\xc3")           # partial two-byte char
        time.sleep(0.8)
        self.append(b"\xa9\n12:00:02  potater\n")   # writer's next flush
        self.assertTrue(self.settle(tailer, "potater"),
                        "the tailer stopped hearing after one torn byte")
        self.assertTrue(tailer._thread.is_alive())

    def test_tail_new_lines_does_not_raise_on_bad_bytes(self):
        self.append(b"12:00:01  \xff\xfe raw scanner bytes\n")
        lines, pos = self.game.tail_new_lines(self.log, 0)
        self.assertTrue(lines)
        self.assertGreater(pos, 0)

    def test_a_truncated_log_is_read_from_the_start(self):
        """A reader sitting past the end of a replaced file is deaf for the
        rest of the session -- the same one line crt-monologue.py has."""
        self.append(b"12:00:01  a good deal more log than what replaces it\n")
        _, pos = self.game.tail_new_lines(self.log, 0)
        with open(self.log, "wb") as f:                 # truncate + one line
            f.write(b"12:00:09  tomato\n")
        self.assertGreater(pos, os.path.getsize(self.log))
        lines, _ = self.game.tail_new_lines(self.log, pos)
        self.assertEqual(lines, ["tomato"])

    def test_an_iteration_that_raises_is_reported_and_the_loop_goes_on(self):
        """Decoding is fixed, but a dead tailer is invisible whatever killed
        it. crt_loop_guard.py is this project's answer to that, and it is
        what the thread now runs inside."""
        real = self.game.tail_new_lines
        calls = []

        def once_bad(path, pos):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError("a bad poll")
            return real(path, pos)

        self.game.tail_new_lines = once_bad
        tailer = self.start()
        self.assertTrue(self.settle(tailer, "potato"))
        self.append(b"12:00:02  potater\n")
        self.assertTrue(self.settle(tailer, "potater"),
                        "one raised iteration ended the tailer")
        self.assertIn("a bad poll", self.buf.getvalue())
        with open(os.environ["CRT_THOUGHT_LOG"]) as f:
            self.assertIn("calibration-game", f.read())


class RecordRoutingDefaultPath(CalibrationGameTestCase):
    def test_the_default_is_env_overridable(self):
        """So the suite -- and anything else -- can never append to the live
        console's own ~/.crt. Cycle 20 caught the same class the hard way."""
        os.environ["CRT_EARCON_ROUTING_LOG"] = os.path.join(self.tmp, "elsewhere.jsonl")
        game = _load("crt_calibration_game_env", "crt-calibration-game.py")
        self.assertEqual(game.ROUTING_LOG, os.path.join(self.tmp, "elsewhere.jsonl"))


if __name__ == "__main__":
    unittest.main()
