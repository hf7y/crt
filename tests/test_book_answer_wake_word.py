#!/usr/bin/env python3
# A question for Claude is not a trivia answer (2026-07-25, fourteenth
# nightly cycle).
#
# crt-stt-solo.py writes EVERY recognized utterance to ~/.crt/stt.log before
# its wake gate runs, and two programs read that file with opposite rules:
# the engine routes anything carrying the wake word to Claude, and
# crt-book-answer-listen.py grades anything inside a book's answer window as
# a trivia answer. Nothing arbitrated between them.
#
#   scan -> tube shows "Fiction or nonfiction?"
#        -> "claude, what is this book about?"
#        -> tube: "nope, it was fiction"
#        -> {"expected": "fiction", "heard": "claude what is this book
#           about"} in book-game-training.jsonl
#        -> "fiction"  (the real answer) -- NOT graded, because 2776f99
#           closes the round on the first graded utterance
#
# So the defect costs twice: one mislabelled row in the file this whole
# console exists to fill, and the loss of the good row that was about to
# follow it. Asking Claude about the book you just scanned is not an exotic
# utterance -- it is the most natural thing in the room.
#
# The 2026-07-21 fix already covers this exact shape for voice COMMANDS by
# reusing crt-secretary.py's find_playbook(). A wake-word utterance is not a
# command: nothing in PLAYBOOKS matches "claude, what is this book about?",
# which is precisely why it falls through to Claude. The fix is the same
# move for the other half -- ask bin/crt_wake_gate.py, which is the gate's
# own rule, aliases included.
#
# Every test in TestAQuestionForClaudeIsNotAnAnswer fails against the parent
# commit. The load-bearing one is
# test_the_real_answer_after_it_still_grades: against the parent it finds
# one training row reading heard='claude what is this book about', instead
# of one reading heard='fiction'.
import importlib.util
import json
import os
import tempfile
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")

_bg_spec = importlib.util.spec_from_file_location(
    "crt_book_game_wakeword", os.path.join(BIN_DIR, "crt-book-game.py"))
bg = importlib.util.module_from_spec(_bg_spec)
_bg_spec.loader.exec_module(bg)

_al_spec = importlib.util.spec_from_file_location(
    "crt_book_answer_listen_wakeword", os.path.join(BIN_DIR, "crt-book-answer-listen.py"))
al = importlib.util.module_from_spec(_al_spec)
_al_spec.loader.exec_module(al)

_wg_spec = importlib.util.spec_from_file_location(
    "crt_wake_gate_under_test", os.path.join(BIN_DIR, "crt_wake_gate.py"))
wg = importlib.util.module_from_spec(_wg_spec)
_wg_spec.loader.exec_module(wg)

QUESTION = {"text": "Fiction or nonfiction?",
            "options": ["fiction", "nonfiction"], "correct": "fiction"}

# The real bin/stt-fixups.json entry, verbatim in shape -- this is what a
# calibration session's "confirmed" evidence actually looks like on disk.
SLIDE_FIXUPS = {
    "_comment": "the file's own doc key, which is not a fixup",
    "slide": {"intent": "claude", "confidence": "confirmed",
              "type": "a-substitution", "note": "calibration-confirmed"},
    "before.": {"intent": "after", "confidence": "auto",
                "type": "book-game-observed", "note": "not a wake word"},
}


def _book(isbn, title):
    return {"isbn": isbn, "title": title, "authors": ["H"], "year": 1965,
            "subjects": [], "raw": {}}


class WakeWordAnswerTestCase(unittest.TestCase):
    """One registered book, a temp training log, a controlled clock, and --
    critically -- a fixups file of this test's own. Left pointed at the real
    bin/stt-fixups.json these tests would pass or fail depending on which
    aliases the room happens to have confirmed by ear this week."""

    FIXUPS = SLIDE_FIXUPS

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.d = self._tmp.name
        self.conn = bg.get_db(os.path.join(self.d, "books.db"))
        self.log_path = os.path.join(self.d, "training.jsonl")
        # al loads its own crt-book-game module object, so patch both (same
        # reason tests/test_book_answer_round_closes.py does).
        for mod in (bg, al.bg):
            self.addCleanup(setattr, mod, "TRAINING_LOG", mod.TRAINING_LOG)
            mod.TRAINING_LOG = self.log_path
        self.fixups_path = os.path.join(self.d, "stt-fixups.json")
        with open(self.fixups_path, "w") as f:
            json.dump(self.FIXUPS, f)
        self._setenv("CRT_STT_FIXUPS", self.fixups_path)
        self._setenv("CRT_STT_FIXUPS_PATH", None)
        self._setenv("CRT_WAKE_WORD", None)

    def _setenv(self, name, value):
        """Set (or unset) an env var for one test, restoring exactly what was
        there -- including 'it was not set at all'."""
        old = os.environ.get(name)
        def restore():
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old
        self.addCleanup(restore)
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value

    def register(self, isbn="1", title="Dune", timestamp="2026-07-21T12:00:00"):
        return bg.register_book(self.conn, _book(isbn, title), questions=[QUESTION],
                                question_source="template", timestamp=timestamp)

    def at(self, iso):
        return al._parse_iso_utc(iso)

    def grade(self, text, iso):
        return al.grade_pending_answer(self.conn, text, window_secs=20,
                                       now=self.at(iso))

    def rows(self):
        if not os.path.exists(self.log_path):
            return []
        with open(self.log_path) as f:
            return [json.loads(l) for l in f if l.strip()]

    def heard(self):
        return [r.get("heard") for r in self.rows()]


class TestAQuestionForClaudeIsNotAnAnswer(WakeWordAnswerTestCase):
    def test_a_question_for_claude_is_not_graded(self):
        """The headline. Not a command -- no playbook matches it -- so the
        2026-07-21 guard does not catch it."""
        self.register()
        self.assertIsNone(
            self.grade("claude what is this book about", "2026-07-21T12:00:05"),
            "an utterance addressed to the console is not a trivia answer")
        self.assertEqual(self.heard(), [],
                         "nothing addressed to Claude belongs in the training log")

    def test_the_real_answer_after_it_still_grades(self):
        """The load-bearing one, and the reason this is worth more than a
        stray row: skipping must leave the round OPEN. Against the parent
        the Claude question consumed the round (2776f99) and this finds one
        row reading 'claude what is this book about'."""
        self.register()
        self.grade("claude what is this book about", "2026-07-21T12:00:05")
        grade = self.grade("fiction", "2026-07-21T12:00:11")
        self.assertIsNotNone(grade, "the round must still be open for the real answer")
        self.assertTrue(grade["correct_content"])
        self.assertEqual(self.heard(), ["fiction"])

    def test_a_stray_comma_does_not_defeat_the_match(self):
        """Whisper punctuates unreliably; the gate tokenizes on word
        characters for exactly this reason and so must the grader."""
        self.register()
        self.assertIsNone(self.grade("hey claude, is this any good?",
                                     "2026-07-21T12:00:05"))
        self.assertEqual(self.heard(), [])

    def test_a_confirmed_mishear_of_the_wake_word_is_also_skipped(self):
        """The reason this asks the gate rather than checking for the literal
        word. 'slide' is a calibration-confirmed mishear of 'claude' in the
        real bin/stt-fixups.json: it WAKES the console, so it cannot also be
        graded as an answer."""
        self.register()
        self.assertIsNone(self.grade("slide what is this book about",
                                     "2026-07-21T12:00:05"))
        self.assertEqual(self.heard(), [])

    def test_a_learned_alias_takes_effect_without_a_restart(self):
        """stt-fixups.json is rewritten while the console runs (the stttrain
        merge loop, a calibration session, a person with an editor). 0ccdf13
        made the engine's gate re-read it live; a grader holding a boot-time
        snapshot would go on grading the very word that now wakes the tube."""
        self.register()
        fresh = dict(self.FIXUPS)
        fresh["cloud"] = {"intent": "claude", "confidence": "confirmed",
                          "type": "a-substitution", "note": "added mid-run"}
        with open(self.fixups_path, "w") as f:
            json.dump(fresh, f)
        self.assertIsNone(self.grade("cloud what is this book about",
                                     "2026-07-21T12:00:05"))
        self.assertEqual(self.heard(), [])


class TestItStillGradesWhatItShould(WakeWordAnswerTestCase):
    """The don't-break-what-works half. A guard that swallows real answers
    would be a worse bug than the one it fixes."""

    def test_an_ordinary_answer_is_still_graded(self):
        self.register()
        grade = self.grade("fiction", "2026-07-21T12:00:05")
        self.assertIsNotNone(grade)
        self.assertEqual(self.heard(), ["fiction"])

    def test_a_wrong_ordinary_answer_is_still_graded(self):
        self.register()
        grade = self.grade("nonfiction", "2026-07-21T12:00:05")
        self.assertIsNotNone(grade)
        self.assertFalse(grade["correct_content"])
        self.assertEqual(self.heard(), ["nonfiction"])

    def test_an_alias_fragment_inside_a_longer_word_is_still_an_answer(self):
        """'slide' is a whole-word fixup. 'landslide' is a perfectly good
        answer to a trivia question and must not be mistaken for the wake
        word -- the substring trap _contains_phrase() exists to avoid."""
        self.register()
        grade = self.grade("landslide", "2026-07-21T12:00:05")
        self.assertIsNotNone(grade, "'landslide' does not contain the wake word")
        self.assertEqual(self.heard(), ["landslide"])

    def test_a_non_wake_fixup_entry_does_not_skip(self):
        """Only entries whose intent IS the wake word gate anything. A
        book-game-observed row like 'before.' -> 'after' is plumbing for a
        consumer that does not exist yet (crt-stt-training-merge.py's own
        honest-scope note) and must not silently start eating answers."""
        self.register()
        grade = self.grade("after", "2026-07-21T12:00:05")
        self.assertIsNotNone(grade)
        self.assertEqual(self.heard(), ["after"])

    def test_a_missing_fixups_file_does_not_break_grading(self):
        """A grader that raised on an unreadable fixups file would take the
        last link of the funnel down over a config problem. The gate degrades
        to exact-word matching; so does this."""
        os.unlink(self.fixups_path)
        self.register()
        self.assertIsNotNone(self.grade("fiction", "2026-07-21T12:00:05"))
        self.assertIsNone(self.grade("claude what is this", "2026-07-21T12:00:06"),
                          "the literal wake word still gates with no fixups file")


class TestTheGateIsOneRuleNotTwo(unittest.TestCase):
    """crt-stt-solo.py's addressed_to_console() and the grader must be the
    same rule, not two that agree today. These pin the delegation itself."""

    def test_stt_solo_delegates_to_the_shared_gate(self):
        spec = importlib.util.spec_from_file_location(
            "crt_stt_solo_for_wake_gate", os.path.join(BIN_DIR, "crt-stt-solo.py"))
        solo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(solo)
        fixups = {"slide": {"intent": "claude"}}
        for text in ("claude run the tests", "hey claude, hello", "slide hello",
                     "landslide hello", "nothing to see here", ""):
            self.assertEqual(
                solo.addressed_to_console(text, fixups=fixups),
                wg.addressed_to_console(text, word="claude", fixups=fixups),
                "the engine and the shared gate disagree about %r" % text)

    def test_the_wake_word_is_read_from_the_same_env_var(self):
        self.assertEqual(wg.wake_word({}), "claude")
        self.assertEqual(wg.wake_word({"CRT_WAKE_WORD": "Potato"}), "potato")

    def test_live_fixups_drops_the_files_own_comment_key(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "f.json")
            with open(path, "w") as f:
                json.dump(SLIDE_FIXUPS, f)
            self.assertNotIn("_comment", wg.live_fixups(path))
            self.assertIn("slide", wg.live_fixups(path))

    def test_live_fixups_tolerates_a_malformed_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "f.json")
            with open(path, "w") as f:
                f.write("{not json")
            self.assertEqual(wg.live_fixups(path), {})


if __name__ == "__main__":
    unittest.main()
