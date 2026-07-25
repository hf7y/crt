#!/usr/bin/env python3
"""The book window measures the tube it is actually drawing on.

WHY THIS EXISTS (2026-07-25, sixteenth nightly cycle). `crt-console.sh`
builds every window with `tmux new-window -d` and only runs
`exec tmux attach` at the very end, after all of them exist. A detached
tmux session is 80x24 regardless of the tube, so every one of those
processes is born believing it has 80 columns and 24 rows. Measured, not
assumed -- `tmux new-session -d; tmux new-window -d` then
`shutil.get_terminal_size()` inside that window reports exactly
`os.terminal_size(columns=80, lines=24)` on tmux 3.6.

`crt-screensaver.py` was fixed for this on 2026-07-23 (re-read the size
every frame) and `crt-monologue.py` in `6aecc39`. `crt-book-console.py` --
the third window that paints a full screen, and the one that draws the
trivia question the whole Book Game funnel exists to put in front of
someone -- sized itself once in `main()` and never again. On the real
40x15 tube that means every screen it draws is laid out 80 wide and 24
tall: each line wraps to two rows, 24 lines become 48 in a 15-row pane,
and the question scrolls itself off the top before anyone reads it. It
never recovers, because nothing measures a second time.

This is FOCUS.md's own 2026-07-23 13:40 line from Zach, in code:
"figure out what's wrong with the text column constraints, problem on
mono window and more."

Two halves, one per test class:
  - detect_screen_size() honors CRT_COLS/CRT_ROWS, the pins crt-console.sh
    already writes for the tube and that the other two renderers read.
  - the RUNNING console repaints at the new size when the terminal it is
    attached to is resized under it -- driven through a real pty, resized
    with a real TIOCSWINSZ, which is what `tmux attach` does to these panes.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from book_console_pty import BookConsolePty, ISBN, SIZE_ENV, bg   # noqa: E402


class DetectScreenSizeTest(unittest.TestCase):
    """The pin crt-console.sh writes has to reach this renderer too."""

    def setUp(self):
        self.saved = {k: os.environ.get(k) for k in SIZE_ENV}
        for k in SIZE_ENV:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_crt_cols_rows_pin_is_honored(self):
        # The whole point: crt-console.sh pins these for the screensaver with
        # a comment saying exactly why, and this window read neither.
        os.environ["CRT_COLS"], os.environ["CRT_ROWS"] = "40", "15"
        self.assertEqual(bg.detect_screen_size(), (40, 15))

    def test_the_games_own_override_still_wins(self):
        os.environ["CRT_COLS"], os.environ["CRT_ROWS"] = "40", "15"
        os.environ["CRT_BOOK_GAME_WIDTH"] = "72"
        os.environ["CRT_BOOK_GAME_HEIGHT"] = "20"
        self.assertEqual(bg.detect_screen_size(), (72, 20),
                         "BOOK-GAME-STYLE.md documents the game's own vars as "
                         "the top of the precedence chain")

    def test_each_dimension_resolves_independently(self):
        # A pin for one and auto-detect for the other is legitimate; it must
        # not throw both away, which is what `if env_w and env_h` did.
        # 52, not 40: 40 is also the fallback, so it would pass by accident
        # against a version that ignored the pin entirely.
        os.environ["CRT_COLS"] = "52"
        w, h = bg.detect_screen_size()
        self.assertEqual(w, 52)
        self.assertTrue(h > 0)

    def test_junk_falls_through_instead_of_raising(self):
        # These names are set by shell. A typo in crt-console.sh must degrade
        # to auto-detection, not kill the window that draws the question --
        # the old bare int() raised ValueError right out of main()'s first line.
        os.environ["CRT_COLS"], os.environ["CRT_ROWS"] = "", "forty"
        os.environ["CRT_BOOK_GAME_WIDTH"] = "-3"
        w, h = bg.detect_screen_size()
        self.assertTrue(w > 0 and h > 0)


class ResizeRepaintTest(BookConsolePty):
    """A real pty, resized under a running console, exactly as an attaching
    tmux client resizes these panes.

    Deliberately not a monkeypatched seam: the claim being tested is that
    THIS PROCESS, started at one size, ends up drawing at another. A helper
    function returning the right number proves nothing about a `main()` that
    reads it once.

    The pty plumbing itself lives in tests/book_console_pty.py (2026-07-25,
    seventeenth cycle) -- a second test needed the same running console.
    """

    def test_it_repaints_when_the_tube_turns_out_to_be_smaller(self):
        # Born at 80x24 -- the size tmux reports inside the detached session
        # crt-console.sh builds.
        self._wait_for_frame_width(80)
        # ...then the client attaches and the pane becomes the real tube.
        self._resize(40, 15)
        # Before this cycle the console never asked again, and every frame for
        # the rest of its life was 80 columns wrapping into a 40-column pane.
        self._wait_for_frame_width(40)

    def test_the_repaint_is_a_full_screen_that_fits_the_pane(self):
        self._wait_for_frame_width(80)
        self._resize(40, 15)
        self._wait_for_frame_width(40)
        frame = self._frames()[-1]
        body = [ln for ln in frame if ln]
        self.assertTrue(body, "repainted an empty frame")
        self.assertTrue(all(len(ln) <= 40 for ln in body),
                        "a line longer than the pane wraps on the tube: %r"
                        % [ln for ln in body if len(ln) > 40][:2])
        # 15 rows of content, not 24 scrolling their own top away.
        self.assertLessEqual(len(frame), 16,
                             "frame is taller than the pane it is drawn into")

    def test_a_question_already_on_the_tube_is_repainted_too(self):
        """The screen that actually matters. A resize while a question is up
        must correct the question, not just the shelf it fell back to -- and
        must not bring back a screen that has since been replaced."""
        self._wait_for_frame_width(80)
        self._scan(ISBN)
        # The question, drawn at the size this process was born believing.
        self._wait_for_text("Nineteen Eighty-Four")
        self._resize(40, 15)
        self._wait_for_frame_width(40)
        frame = self._frames()[-1]
        joined = " ".join(frame)
        self.assertIn("Nineteen Eighty-Four", joined,
                      "the resize repainted something other than the question "
                      "that was on the tube")
        self.assertIn("fiction", joined, "the options went missing on repaint")
        self.assertTrue(all(len(ln) <= 40 for ln in frame if ln))


if __name__ == "__main__":
    unittest.main()
