#!/usr/bin/env python3
# A sticky-conversation follow-up is not a trivia answer (2026-07-25,
# twentieth nightly cycle).
#
# This is the fourteenth cycle's defect (tests/test_book_answer_wake_word.py)
# through the one door that file could not close. Two programs read
# ~/.crt/stt.log with opposite rules -- crt-stt-solo.py routes anything
# addressed to the console to Claude, crt-book-answer-listen.py grades
# anything inside a scanned book's answer window as a trivia answer -- and
# "addressed to the console" stopped meaning "carries the wake word" the day
# bin/crt-wake-arm.py landed. Inside an open arm window, follow-ups reach
# Claude with NO wake word at all, deliberately: the live 2026-07-23 bug this
# whole mechanism exists for was four follow-ups in one breath, every one of
# them gate-dropped for not repeating it.
#
#   scan -> tube shows "Fiction or nonfiction?"
#        -> "claude, are you there?"     wake: not graded (14th cycle), ARMS
#        -> "what is this book about?"   follow-up: routed to Claude...
#        -> tube: "nope, it was fiction"          ...and graded anyway
#        -> {"expected": "fiction", "heard": "what is this book about"}
#        -> "fiction"  (the real answer) -- NOT graded: 2776f99 closed the
#           round on the row above
#
# Both bar items in .claude/FOCUS.md's stability milestone are involved: the
# arm window is item 1 and the Book Game funnel is item 4, and turning the
# first one on live is what makes the fourth one start writing corrupt rows
# into the file this console exists to fill. CRT_WAKE_ARM_ENABLED is still
# default-OFF, so nothing here changes today's live behaviour -- these tests
# are the reason it can be turned on without taking the funnel with it.
#
# The arm state machine is in-process (one ArmState in the engine), so the
# reader is told about it through a published DEADLINE, not a flag: the wake
# utterance opens the window, which puts the file on disk before the
# follow-up it describes is ever spoken. See crt-wake-arm.py's
# ARM_STATE_FILE block.
#
# Against the parent commit every test here errors, since the mechanism they
# describe does not exist there (no ARM_STATE_FILE to point anywhere). The
# BEHAVIOUR they pin was reproduced separately against the parent's own
# crt-book-answer-listen.py, with the published window in place: the
# follow-up graded as wrong, one row reading heard='what is this book about'
# went into the training log, and the real answer two seconds later returned
# None -- ungraded, the round already closed.
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


bg = _load("crt_book_game_armwindow", "crt-book-game.py")
al = _load("crt_book_answer_listen_armwindow", "crt-book-answer-listen.py")
wake_arm = _load("crt_wake_arm_armwindow", "crt-wake-arm.py")

QUESTION = {"text": "Fiction or nonfiction?",
            "options": ["fiction", "nonfiction"], "correct": "fiction"}


def _book(isbn, title):
    return {"isbn": isbn, "title": title, "authors": ["H"], "year": 1965,
            "subjects": [], "raw": {}}


class ArmWindowTestCase(unittest.TestCase):
    """One registered book, a temp training log, a controlled clock, and an
    arm-state file of this test's own -- pointed away from ~/.crt/ so a suite
    run can neither read whatever the live console happens to be doing nor
    write into it. The same hermeticity rule the fixups path gets in
    tests/test_book_answer_wake_word.py."""

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
        self.state_path = os.path.join(self.d, "wake-arm.state")
        for mod in (wake_arm, al.wake_arm):
            self.addCleanup(setattr, mod, "ARM_STATE_FILE", mod.ARM_STATE_FILE)
            mod.ARM_STATE_FILE = self.state_path

    def register(self, isbn="1", title="Dune", timestamp="2026-07-21T12:00:00"):
        return bg.register_book(self.conn, _book(isbn, title), questions=[QUESTION],
                                question_source="template", timestamp=timestamp)

    def at(self, iso):
        return al._parse_iso_utc(iso)

    def arm_until(self, iso):
        """Publish an open window ending at `iso`, the way the engine does
        after a wake -- through the real ArmState and the real publisher, not
        by writing a number this test made up."""
        state = wake_arm.ArmState()
        end = self.at(iso)
        state.arm("claude are you there", "exact", now=end - 12.0, arm_secs=12.0)
        wake_arm.publish_arm_window(state)
        return state

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


class TestAFollowUpIsNotAnAnswer(ArmWindowTestCase):
    def test_follow_up_inside_the_window_is_not_graded(self):
        self.register()
        self.arm_until("2026-07-21T12:00:12")
        self.assertIsNone(self.grade("what is this book about",
                                     "2026-07-21T12:00:05"))

    def test_it_writes_no_training_row(self):
        self.register()
        self.arm_until("2026-07-21T12:00:12")
        self.grade("what is this book about", "2026-07-21T12:00:05")
        self.assertEqual(self.rows(), [])

    def test_the_round_stays_open(self):
        """The load-bearing one. 2776f99 closes a round on the first graded
        utterance, so a follow-up graded by mistake does not just add a bad
        row -- it eats the good one that was about to follow."""
        self.register()
        self.arm_until("2026-07-21T12:00:12")
        self.grade("what is this book about", "2026-07-21T12:00:05")
        self.assertIsNotNone(al.get_pending_question(self.conn, 20,
                                                     now=self.at("2026-07-21T12:00:06")))

    def test_the_real_answer_after_the_window_still_grades(self):
        self.register()
        self.arm_until("2026-07-21T12:00:12")
        self.grade("what is this book about", "2026-07-21T12:00:05")
        grade = self.grade("fiction", "2026-07-21T12:00:14")
        self.assertIsNotNone(grade)
        self.assertTrue(grade["correct_content"])
        self.assertEqual(self.heard(), ["fiction"])


class TestNothingChangesWithTheWindowShut(ArmWindowTestCase):
    """CRT_WAKE_ARM_ENABLED is default-OFF and this must stay a no-op there,
    and stay a no-op for every failure mode of the file itself. Each of these
    grades, exactly as it did before this cycle."""

    def test_never_published_still_grades(self):
        self.register()
        self.assertFalse(os.path.exists(self.state_path))
        self.assertIsNotNone(self.grade("fiction", "2026-07-21T12:00:05"))

    def test_a_closed_window_still_grades(self):
        self.register()
        state = self.arm_until("2026-07-21T12:00:12")
        state.disarm()
        wake_arm.publish_arm_window(state)
        self.assertIsNotNone(self.grade("fiction", "2026-07-21T12:00:05"))

    def test_a_stale_deadline_still_grades(self):
        """A crash, a reboot, or arming turned back off leaves the last file
        behind, from a conversation that ended long before this scan. It
        describes a moment in the past, so it reads as shut and nothing has to
        clean it up."""
        self.register()
        self.arm_until("2026-07-21T11:50:00")
        self.assertIsNotNone(self.grade("fiction", "2026-07-21T12:00:05"))

    def test_a_junk_state_file_still_grades(self):
        self.register()
        with open(self.state_path, "w") as f:
            f.write("not a number\n")
        self.assertIsNotNone(self.grade("fiction", "2026-07-21T12:00:05"))

    def test_an_unreadable_state_path_still_grades(self):
        self.register()
        al.wake_arm.ARM_STATE_FILE = os.path.join(self.d, "nope", "nope", "x")
        self.assertIsNotNone(self.grade("fiction", "2026-07-21T12:00:05"))


class TestPublishedArmWindow(unittest.TestCase):
    """The channel itself, away from the game."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "sub", "wake-arm.state")

    def armed(self, now=1000.0, arm_secs=12.0):
        state = wake_arm.ArmState()
        state.arm("claude", "exact", now=now, arm_secs=arm_secs)
        return state

    def test_publish_then_read_round_trips_the_deadline(self):
        wake_arm.publish_arm_window(self.armed(), self.path)
        self.assertAlmostEqual(wake_arm.read_arm_deadline(self.path), 1012.0, places=2)

    def test_open_before_the_deadline_shut_after(self):
        wake_arm.publish_arm_window(self.armed(), self.path)
        self.assertTrue(wake_arm.arm_window_open(now=1011.9, path=self.path))
        self.assertFalse(wake_arm.arm_window_open(now=1012.0, path=self.path))

    def test_a_slide_moves_the_deadline(self):
        state = self.armed()
        state.slide("and another thing", now=1005.0, arm_secs=12.0)
        wake_arm.publish_arm_window(state, self.path)
        self.assertTrue(wake_arm.arm_window_open(now=1015.0, path=self.path))

    def test_disarm_publishes_a_shut_window(self):
        state = self.armed()
        wake_arm.publish_arm_window(state, self.path)
        state.disarm()
        wake_arm.publish_arm_window(state, self.path)
        self.assertFalse(wake_arm.arm_window_open(now=1001.0, path=self.path))

    def test_never_published_reads_as_shut(self):
        self.assertIsNone(wake_arm.read_arm_deadline(self.path))
        self.assertFalse(wake_arm.arm_window_open(now=1001.0, path=self.path))

    def test_no_temp_file_is_left_behind(self):
        """os.replace, not a plain truncating write: a reader catching a
        half-written number would read it as shut, which is the exact failure
        this file exists to stop."""
        wake_arm.publish_arm_window(self.armed(), self.path)
        self.assertEqual(os.listdir(os.path.dirname(self.path)), ["wake-arm.state"])

    def test_an_unwritable_path_does_not_raise(self):
        """This is called from the sole mic reader's own loop. An unwritable
        ~/.crt must cost the console a published window, not its ears."""
        wake_arm.publish_arm_window(self.armed(), os.path.join(__file__, "x", "y"))

    def test_an_empty_path_is_a_no_op(self):
        wake_arm.publish_arm_window(self.armed(), "")
        self.assertIsNone(wake_arm.read_arm_deadline(""))
        self.assertFalse(wake_arm.arm_window_open(path=""))


class TestTheEnginePublishes(unittest.TestCase):
    """crt-stt-solo.py's own publish_arm_window() -- the half that makes the
    file appear at all. Imported here with CRT_WAKE_ARM_ENABLED=1, since the
    engine reads that at import and the whole mechanism is dead code without
    it (tests/test_stt_solo_helpers.py imports the same file with the flag
    off, in its own process, and must keep seeing today's behaviour)."""

    @classmethod
    def setUpClass(cls):
        cls._old = os.environ.get("CRT_WAKE_ARM_ENABLED")
        os.environ["CRT_WAKE_ARM_ENABLED"] = "1"
        try:
            cls.engine = _load("crt_stt_solo_armed", "crt-stt-solo.py")
        finally:
            if cls._old is None:
                os.environ.pop("CRT_WAKE_ARM_ENABLED", None)
            else:
                os.environ["CRT_WAKE_ARM_ENABLED"] = cls._old

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "wake-arm.state")
        mod = self.engine.wake_arm
        self.addCleanup(setattr, mod, "ARM_STATE_FILE", mod.ARM_STATE_FILE)
        mod.ARM_STATE_FILE = self.path
        self.addCleanup(self.engine.ARM_STATE.disarm)

    def test_arming_publishes_the_window(self):
        self.engine.ARM_STATE.arm("claude", "exact", now=1000.0, arm_secs=12.0)
        self.engine.publish_arm_window()
        self.assertTrue(self.engine.wake_arm.arm_window_open(now=1005.0, path=self.path))

    def test_disarming_publishes_a_shut_window(self):
        self.engine.ARM_STATE.arm("claude", "exact", now=1000.0, arm_secs=12.0)
        self.engine.publish_arm_window()
        self.engine.ARM_STATE.disarm()
        self.engine.publish_arm_window()
        self.assertFalse(self.engine.wake_arm.arm_window_open(now=1005.0, path=self.path))

    def test_every_transition_site_publishes(self):
        """Structural, on purpose. The three places the engine changes arm
        state are an arm on a fresh wake, a consume (which slides, re-arms or
        closes), and a timeout -- and a publish forgotten at any one of them
        leaves the reader believing a window that is no longer there, or
        missing one that is. Reading the source is the only way to assert
        that from here without a mic; the alternative is finding out live."""
        with open(os.path.join(BIN_DIR, "crt-stt-solo.py")) as f:
            lines = f.readlines()
        sites = [i for i, ln in enumerate(lines)
                 if ("ARM_STATE.arm(" in ln
                     or "consume_arm_with_followup(" in ln
                     or "check_arm_timeout(" in ln)
                 and "def " not in ln]
        self.assertTrue(sites, "no arm-state transition sites found at all")
        for i in sites:
            window = "".join(lines[i:i + 12])
            self.assertIn("publish_arm_window()", window,
                          "no publish within 12 lines of %s:%d -- %r"
                          % ("bin/crt-stt-solo.py", i + 1, lines[i].strip()))


if __name__ == "__main__":
    unittest.main()
