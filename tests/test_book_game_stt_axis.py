#!/usr/bin/env python3
# correct_stt and correct_content were the same flag (2026-07-25,
# fourteenth nightly cycle).
#
# BOOK-GAME.md is explicit about why the Book Game logs two axes: "a wrong
# content-answer with correct STT is a fine game round and useless training
# noise; a right content-answer with wrong STT is the valuable case." The
# code could not tell those apart. grade_answer() computed
#
#   correct_stt     = normalize(expected)      == normalize(heard)
#   correct_content = normalize(correct_option) == normalize(heard)
#
# and BOTH live callers pass the same string twice --
# crt-book-answer-listen.py:233 and crt-book-game.py's own --answer CLI both
# say expected=q["correct"], correct_option=q["correct"]. So the two flags
# were identical in every row this console has ever been able to write.
#
# What it cost, in the most ordinary event a two-option game has:
#
#   "Is Dune fiction or nonfiction?"  ->  someone says "nonfiction"
#     -> heard perfectly by whisper, and simply wrong
#     -> correct_stt: false
#     -> counted against "STT accuracy" on the tube and in the printed report
#     -> listed under "STT mismatches ... the actual training data"
#     -> generate_candidate_fixups() at 2 occurrences emits
#        {"nonfiction": {"intent": "fiction"}}
#     -> crt-stt-training-merge.py auto-merges it into the live
#        bin/stt-fixups.json, confidence "auto"
#
# The console teaching itself that a word it heard correctly is a mishear.
# And the same corrupted number drives pick_response_tier(), so honest wrong
# answers held the game in short-response mode.
#
# The always-available fallback question was worse: "Have you read this
# before?" has correct=None, so normalize(expected) was "" and EVERY answer
# anyone could give it -- "yes", "no", anything -- logged correct_stt false.
#
# The fix asks the question this side can actually answer: did the
# transcription land on one of the options the person was offered?
#
# All 12 tests fail against the parent commit, but nine of them fail as
# TypeErrors on grade_answer's new `options=` argument, which is a weak
# witness -- an API change, not a behaviour change. The two that pin the
# actual defect go through the live path with no new argument anywhere, and
# fail there as plain assertion failures:
# TestTheLiveCallerPassesTheOptions's two tests, where a person speaks a
# wrong answer, whisper hears it perfectly, and the parent files it as a
# mishear and then hands it to the fixups merger.
import importlib.util
import json
import os
import tempfile
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(BIN_DIR, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bg = _load("crt_book_game_stt_axis", "crt-book-game.py")
st = _load("crt_book_game_stats_stt_axis", "crt-book-game-stats.py")
al = _load("crt_book_answer_listen_stt_axis", "crt-book-answer-listen.py")

OPTIONS = ["fiction", "nonfiction"]
QUESTION = {"text": "Fiction or nonfiction?", "options": OPTIONS, "correct": "fiction"}


class TestTheTwoAxesCanDisagree(unittest.TestCase):
    def test_a_wrong_answer_heard_correctly_is_not_a_mishear(self):
        """The headline. Against the parent this reads correct_stt False."""
        g = bg.grade_answer(expected="fiction", heard="nonfiction",
                            correct_option="fiction", options=OPTIONS)
        self.assertFalse(g["correct_content"], "they got the fact wrong")
        self.assertTrue(g["correct_stt"], "whisper heard them perfectly")

    def test_a_right_answer_misheard_is_still_the_valuable_case(self):
        """The row BOOK-GAME.md calls the valuable one must keep reading as a
        mishear -- the fix must not blunt the signal it exists to sharpen."""
        g = bg.grade_answer(expected="fiction", heard="friction",
                            correct_option="fiction", options=OPTIONS)
        self.assertFalse(g["correct_content"])
        self.assertFalse(g["correct_stt"], "'friction' is not on the list")

    def test_a_right_answer_heard_correctly_is_right_on_both_axes(self):
        g = bg.grade_answer(expected="fiction", heard="fiction",
                            correct_option="fiction", options=OPTIONS)
        self.assertTrue(g["correct_content"])
        self.assertTrue(g["correct_stt"])

    def test_the_ungradeable_fallback_question_no_longer_fails_every_answer(self):
        """generate_template_question's always-available fallback has
        correct=None but perfectly good options. Against the parent,
        normalize(None) is '' and so "yes" was a transcription failure."""
        g = bg.grade_answer(expected=None, heard="yes", correct_option=None,
                            options=["yes", "no"])
        self.assertIsNone(g["correct_content"], "nothing to grade content-wise")
        self.assertTrue(g["correct_stt"], "'yes' is exactly what was offered")

    def test_normalization_still_applies_to_the_option_list(self):
        """Case and punctuation must not decide whether a word is on the
        list -- same normalize() the content axis has always used."""
        g = bg.grade_answer(expected="Fiction!", heard="fiction",
                            correct_option="Fiction!", options=["Fiction!", "Nonfiction!"])
        self.assertTrue(g["correct_stt"])
        self.assertTrue(g["correct_content"])

    def test_no_option_list_means_unknown_not_failed(self):
        """A caller with nothing to check against must produce None. False
        would be the old bug wearing a new name."""
        g = bg.grade_answer(expected="fiction", heard="anything at all",
                            correct_option="fiction")
        self.assertIsNone(g["correct_stt"])


class TestTheTrainingLogStopsPoisoningTheFixups(unittest.TestCase):
    """The end of the pipe, which is where the damage actually landed."""

    def _rows(self, *grades):
        return [dict(g, isbn="1") for g in grades]

    def test_wrong_answers_do_not_become_candidate_fixups(self):
        """Two honest wrong guesses used to reach min_repeats and emit
        {"nonfiction": {"intent": "fiction"}} for crt-stt-training-merge.py
        to auto-merge into the live wake-gate fixups file."""
        rows = self._rows(*[bg.grade_answer(expected="fiction", heard="nonfiction",
                                            correct_option="fiction", options=OPTIONS)
                            for _ in range(2)])
        mismatches = st.summarize_training(rows)["mismatches"]
        self.assertEqual(mismatches, [], "a wrong guess is not training data")
        self.assertEqual(st.generate_candidate_fixups(mismatches), {})

    def test_real_mishears_still_become_candidate_fixups(self):
        """The don't-break half: the mechanism must still fire on a genuine
        repeated mishear, which is the whole reason it exists."""
        rows = self._rows(*[bg.grade_answer(expected="fiction", heard="friction",
                                            correct_option="fiction", options=OPTIONS)
                            for _ in range(2)])
        mismatches = st.summarize_training(rows)["mismatches"]
        self.assertEqual(len(mismatches), 2)
        candidates = st.generate_candidate_fixups(mismatches)
        self.assertIn("friction", candidates)
        self.assertEqual(candidates["friction"]["intent"], "fiction")

    def test_stt_accuracy_counts_only_rounds_it_can_judge(self):
        """One judgeable hit, one judgeable miss, one unjudgeable round ->
        50%, not 33%. Dividing by every row would let 'no options recorded'
        read as a transcription failure."""
        rows = self._rows(
            bg.grade_answer(expected="fiction", heard="fiction",
                            correct_option="fiction", options=OPTIONS),
            bg.grade_answer(expected="fiction", heard="friction",
                            correct_option="fiction", options=OPTIONS),
            bg.grade_answer(expected="fiction", heard="who knows",
                            correct_option="fiction"),
        )
        stats = st.summarize_training(rows)
        self.assertEqual(stats["total_rounds"], 3)
        self.assertEqual(stats["stt_known"], 2)
        self.assertAlmostEqual(stats["stt_accuracy"], 0.5)

    def test_the_screen_summary_says_n_a_rather_than_zero_percent(self):
        rows = self._rows(bg.grade_answer(expected="fiction", heard="who knows",
                                          correct_option="fiction"))
        lines = st.render_screen_summary({"total": 1}, st.summarize_training(rows), width=40)
        self.assertTrue(any("n/a" in l for l in lines), lines)
        self.assertFalse(any("0%" in l for l in lines), lines)

    def test_the_tier_reader_uses_the_same_denominator_as_the_stats_reader(self):
        """pick_response_tier's docstring says its accuracy comes from
        summarize_training()['stt_accuracy'], but _recent_training_stats()
        is a separate hand-rolled reader of the same file (deliberately, to
        avoid an import cycle). Two readers that disagree about what counts
        is the drift this project keeps finding."""
        rows = self._rows(
            bg.grade_answer(expected="fiction", heard="fiction",
                            correct_option="fiction", options=OPTIONS),
            bg.grade_answer(expected="fiction", heard="friction",
                            correct_option="fiction", options=OPTIONS),
            bg.grade_answer(expected="fiction", heard="who knows",
                            correct_option="fiction"),
        )
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "training.jsonl")
            with open(path, "w") as f:
                for r in rows:
                    f.write(json.dumps(r) + "\n")
            total, acc = bg._recent_training_stats(path)
        self.assertEqual(total, 3, "rounds played is still every row")
        self.assertAlmostEqual(acc, st.summarize_training(rows)["stt_accuracy"])
        self.assertAlmostEqual(acc, 0.5)

    def test_the_full_report_no_longer_calls_it_matched_what_was_expected(self):
        """The old label described a trivia score wearing an STT name."""
        rows = self._rows(bg.grade_answer(expected="fiction", heard="nonfiction",
                                          correct_option="fiction", options=OPTIONS))
        report = st.render_full_report(
            {"total": 1, "template_questions": 1, "claude_questions": 0},
            st.summarize_training(rows))
        self.assertNotIn("matched what was expected", report)
        self.assertIn("one of the offered options", report)


class TestTheLiveCallerPassesTheOptions(unittest.TestCase):
    """A grade_answer() that CAN tell the axes apart is worth nothing if the
    one caller that writes real rows still doesn't hand it the option list.
    This goes through crt-book-answer-listen.py end to end."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        d = self._tmp.name
        self.conn = bg.get_db(os.path.join(d, "books.db"))
        self.log_path = os.path.join(d, "training.jsonl")
        for mod in (bg, al.bg):
            self.addCleanup(setattr, mod, "TRAINING_LOG", mod.TRAINING_LOG)
            mod.TRAINING_LOG = self.log_path
        bg.register_book(self.conn,
                         {"isbn": "1", "title": "Dune", "authors": ["H"],
                          "year": 1965, "subjects": [], "raw": {}},
                         questions=[QUESTION], question_source="template",
                         timestamp="2026-07-21T12:00:00")

    def rows(self):
        if not os.path.exists(self.log_path):
            return []
        with open(self.log_path) as f:
            return [json.loads(l) for l in f if l.strip()]

    def test_a_spoken_wrong_answer_is_logged_as_heard_correctly(self):
        grade = al.grade_pending_answer(self.conn, "nonfiction", window_secs=20,
                                        now=al._parse_iso_utc("2026-07-21T12:00:05"))
        self.assertIsNotNone(grade)
        self.assertFalse(grade["correct_content"])
        self.assertTrue(grade["correct_stt"],
                        "the listener must pass options= through to grade_answer")
        row = self.rows()[0]
        self.assertIs(row["correct_stt"], True)
        self.assertIs(row["correct_content"], False)

    def test_two_spoken_wrong_answers_do_not_reach_the_live_fixups_file(self):
        """The whole chain, as it actually runs: two wrong guesses on two
        scans of the same book, straight into what crt-stt-training-merge.py
        would merge into bin/stt-fixups.json. Against the parent this emits
        {'nonfiction': {'intent': 'fiction'}} at confidence "auto"."""
        al.grade_pending_answer(self.conn, "nonfiction", window_secs=20,
                                now=al._parse_iso_utc("2026-07-21T12:00:05"))
        bg.touch_scan(self.conn, "1", timestamp="2026-07-21T12:01:00")
        al.grade_pending_answer(self.conn, "nonfiction", window_secs=20,
                                now=al._parse_iso_utc("2026-07-21T12:01:05"))
        self.assertEqual(len(self.rows()), 2, "both rounds must have been graded")
        mismatches = st.summarize_training(self.rows())["mismatches"]
        self.assertEqual(st.generate_candidate_fixups(mismatches), {},
                         "a repeated wrong guess must never become a wake-gate fixup")


if __name__ == "__main__":
    unittest.main()
