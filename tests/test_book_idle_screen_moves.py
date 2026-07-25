#!/usr/bin/env python3
"""The idle screen actually moves. It has never moved.

WHY THIS EXISTS (2026-07-25, seventeenth nightly cycle).
`crt-book-console.py`'s `render_idle_screen()` picks a fresh caption and a
fresh position on every call, and its docstring says why, twice, quoting
Zach directly:

    "Caption rotates between the plain count and a random enticement line
     (bg.pick_entice_line) so the resting screen actively invites a new scan
     rather than just sitting static -- the actual point of this feature."

    "Caption POSITION also moves around the screen (2026-07-21, Zach's direct
     ask) ... so the idle screen doesn't look frozen in the same layout every
     single time."

It is called once. `main()` calls `draw_idle()` at startup, on a scan's idle
timeout, and on a stray non-ISBN line -- and nothing else. So the resting
screen picks one caption at one position at boot and holds it, unchanged,
until somebody scans something. Which is the thing it is supposed to be
talking them into doing. The randomisation is real, tested, and never runs
twice: idle-bait is the FIRST link of the funnel (.claude/FOCUS.md's
2026-07-21 end-goal statement) and it has been a still frame.

It also holds one unchanging frame on a phosphor tube indefinitely, which is
the hazard the sibling window (`crt-screensaver.py`, breathing every 2.5s)
exists to avoid.

Two classes:
  - the pure renderer really does vary (so the fix is "call it again", not
    "make it random");
  - the RUNNING console draws the idle screen more than once, with nobody
    touching it. Driven through the shared pty harness, because the claim is
    about a loop, not about a function.
"""
import os
import random
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from book_console_pty import BookConsolePty, ISBN, TITLE, ANSI, bg   # noqa: E402

import importlib.util   # noqa: E402

BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")
_spec = importlib.util.spec_from_file_location(
    "crt_book_console_for_idle_test", os.path.join(BIN_DIR, "crt-book-console.py"))
console = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(console)


def _plain(lines):
    return tuple(ANSI.sub("", ln) for ln in lines)


class IdleScreenVariesTest(unittest.TestCase):
    """The renderer's own variety, so the loop fix is the only thing missing."""

    def test_repeated_draws_are_not_the_same_screen(self):
        rng = random.Random(7)
        seen = {_plain(console.render_idle_screen(3, 40, 15, rng=rng))
                for _ in range(40)}
        self.assertGreater(len(seen), 5,
                           "render_idle_screen() is supposed to move the caption "
                           "and swap its text; 40 draws produced %d layouts"
                           % len(seen))

    def test_both_captions_come_up_over_time(self):
        rng = random.Random(11)
        text = " ".join(" ".join(_plain(console.render_idle_screen(3, 40, 15, rng=rng)))
                        for _ in range(60))
        self.assertIn("book(s) registered", text,
                      "the plain count never appeared")
        self.assertTrue(any(line[:12] in text for line in bg.ENTICE_LINES),
                        "no enticement line ever appeared -- the half of the "
                        "caption that invites a NEW scan")


class IdleScreenRedrawsTest(BookConsolePty):
    """The running console, left completely alone.

    Nothing is written to its stdin and no scan lands: this is exactly the
    console sitting on the boot-default `book` window with nobody at it, which
    is the state the idle screen exists for.
    """

    EXTRA_ENV = {"CRT_BOOK_IDLE_ROTATE_SECS": "0.4"}

    def test_the_resting_screen_draws_again_on_its_own(self):
        # Four paints in six seconds at a 0.4s cadence is a very slack bar --
        # it would take ~2.5s. Against the parent commit this never gets past
        # one, however long it waits, because nothing calls draw_idle() again.
        count = self._wait_for_frame_count(4, timeout=6.0)
        self.assertGreaterEqual(
            count, 4,
            "the idle screen painted %d time(s) in 6s with a 0.4s rotation "
            "cadence -- it is a still frame" % count)

    def test_the_screen_it_draws_again_is_a_different_one(self):
        """Redrawing the identical frame forever would satisfy a frame count
        and none of the point. The caption has to actually move or change."""
        self._wait_for_frame_count(12, timeout=8.0)
        layouts = {tuple(f) for f in self._frames()}
        self.assertGreater(len(layouts), 1,
                           "every repaint drew the identical screen")


class IdleRotationLeavesAQuestionAloneTest(BookConsolePty):
    """A question on the tube is not an idle screen, and must not be painted
    over by the rotation timer.

    CRT_BOOK_CONSOLE_IDLE_SECS is 600 here (harness default), so the question
    is still current for the whole test -- if the rotation fired regardless of
    state, the person reading the question would watch it vanish.
    """

    EXTRA_ENV = {"CRT_BOOK_IDLE_ROTATE_SECS": "0.2"}

    def test_the_question_stays_up_while_the_rotation_ticks(self):
        self._wait_for_text("BOOK GAME")
        self._scan(ISBN)
        self._wait_for_text(TITLE)
        before = len(self._frames())
        time.sleep(2.0)     # ten rotation intervals
        after = self._frames()
        self.assertIn(TITLE, " ".join(after[-1]),
                      "the idle rotation painted over the question")
        # And it is not silently repainting the question ten times either --
        # the only frames since the scan should be the ones the console's own
        # question logic draws (at most the waiting hint, which needs 8s).
        self.assertLessEqual(len(after) - before, 1,
                             "the rotation kept drawing while a question was up")


class IdleRotationCanBeTurnedOffTest(BookConsolePty):
    """Zero disables it.

    This repo's standing rule (.claude/FOCUS.md, 2026-07-23 07:20, about
    resolving the capture device by name) is that an automatic behaviour keeps
    its manual escape hatch. A tube that must hold one frame -- a photograph,
    a long-exposure, someone's own reason -- gets to.
    """

    EXTRA_ENV = {"CRT_BOOK_IDLE_ROTATE_SECS": "0"}

    def test_nothing_repaints(self):
        self._wait_for_text("BOOK GAME")
        time.sleep(2.0)
        self.assertEqual(len(self._frames()), 1,
                         "CRT_BOOK_IDLE_ROTATE_SECS=0 still repainted")


class IdleRotationSurvivesJunkTest(BookConsolePty):
    """A typo in the shell must not kill the window that IS the console's face.

    Same class as the bare int() that `bg.detect_screen_size()` was carrying
    until last cycle: these names are set by crt-console.sh, and a module-level
    float() on a misspelled value raises before main() draws anything at all,
    leaving a bash prompt where the console's face goes.
    """

    EXTRA_ENV = {"CRT_BOOK_IDLE_ROTATE_SECS": "eight"}

    def test_it_falls_back_to_the_default_instead_of_dying(self):
        self._wait_for_text("BOOK GAME")
        self._assert_alive()


if __name__ == "__main__":
    unittest.main()
