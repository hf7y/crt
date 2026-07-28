#!/usr/bin/env python3
"""The potato's caption moves, and never lands where it already is.

WHY THIS EXISTS (2026-07-25, eighteenth nightly cycle).

Last cycle fixed the book console's resting screen: its caption rotates and
moves, and nothing had ever called it twice. Zach's reply quoted both halves
of that docstring back with the point bolded -- "rather than just sitting
static -- the actual point of this feature", "so the idle screen doesn't
look frozen in the same layout every single time".

That is the OTHER resting screen. `crt-console.sh`'s idle-lean branch
(CRT_NO_IDLE_CLAUDE=1, the layout potato actually boots) selects window 0 --
`crt-screensaver.py` -- as the boot default, so on the live console this is
the screen the tube holds until somebody speaks or scans. Its caption was a
fixed string on the last row, centered, from boot to shutdown. The breathing
proves the PROCESS is alive; it says nothing about the screen, which was one
frozen layout in front of whoever was standing there.

Two more faults in the same few lines, both already fixed once next door:
  - `caption[:width]` and `len(cap)` counted characters, not columns, so a
    CRT_SCREENSAVER_CAPTION holding anything East Asian Wide is cut and
    centered wrong and wraps on the tube (bin/crt_caption.py).
  - a bare float() on CRT_SCREENSAVER_INTERVAL raised inside argparse's
    defaults, killing the idle face on a shell typo.

And one this file pins: the frame is exactly `height` lines. It used to emit
height+1, scrolling the tube by a row on every frame.
"""
import importlib.util
import os
import random
import re
import subprocess
import sys
import time
import unittest

BIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")
_spec = importlib.util.spec_from_file_location(
    "screensaver_caption", os.path.join(BIN, "crt-screensaver.py"))
ss = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ss)

ANSI = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
CAPTION = "say 'potato' to wake me"
ART = [("x" * 30) for _ in range(11)]     # the real potato's shape: 11 rows, 30 cols


def plain(frame):
    return ANSI.sub("", frame).split("\n")


def caption_row(frame, caption=CAPTION):
    for i, line in enumerate(plain(frame)):
        if caption.strip() in line:
            return i, len(line) - len(line.lstrip(" "))
    raise AssertionError("the caption is not on the screen at all")


class FrameShapeTest(unittest.TestCase):
    def test_frame_is_exactly_height_lines(self):
        """height+1 lines scrolled the tube one row every frame -- twice a
        breath, forever, on a screen that is meant to be still furniture."""
        for h in (15, 24, 8):
            frame = ss.render_frame(ART, 40, h, CAPTION, ss.CYAN, dim=True)
            self.assertEqual(len(plain(frame)), h,
                             "a %d-row screen got %d lines"
                             % (h, len(plain(frame))))

    def test_no_line_exceeds_the_width(self):
        for align in ss.caption_lib.ALIGNMENTS:
            frame = ss.render_frame(ART, 40, 15, CAPTION, ss.CYAN, dim=True,
                                    slot=(13, align))
            for line in plain(frame):
                self.assertLessEqual(len(line), 40)

    def test_default_slot_is_where_it_has_always_been(self):
        """No slot -> last row, centered. The historical layout is still the
        one you get by asking for nothing."""
        frame = ss.render_frame(ART, 40, 15, CAPTION, ss.CYAN, dim=True)
        row, left = caption_row(frame)
        self.assertEqual(row, 14)
        self.assertEqual(left, (40 - len(CAPTION)) // 2)


class CaptionIsMeasuredInColumnsTest(unittest.TestCase):
    """CRT_SCREENSAVER_CAPTION is free text and nothing stops it holding a
    kaomoji -- the sibling screen's own enticement lines are full of them."""

    WIDE = "(・∀・)  say potato -- anything at all, really, go on"

    def test_a_wide_caption_is_cut_to_columns_not_characters(self):
        frame = ss.render_frame(ART, 40, 15, self.WIDE, ss.CYAN, dim=True)
        for line in plain(frame):
            self.assertLessEqual(ss.caption_lib.display_width(line), 40,
                                 "a wide caption was drawn past the tube edge "
                                 "and wrapped: %r" % line)


class CaptionMovesTest(unittest.TestCase):
    def test_it_never_sits_where_it_already_is(self):
        rng = random.Random(3)
        slot = None
        for i in range(500):
            nxt = ss.pick_caption_slot(ART, 40, 15, rng=rng, avoid=slot)
            self.assertNotEqual(slot, nxt, "move %d did not move" % i)
            slot = nxt

    def test_it_uses_more_than_one_row_and_more_than_one_alignment(self):
        rng = random.Random(3)
        slots = {ss.pick_caption_slot(ART, 40, 15, rng=rng) for _ in range(200)}
        self.assertGreater(len({r for r, _ in slots}), 1, "it only ever used one row")
        self.assertGreater(len({a for _, a in slots}), 1, "it only ever used one alignment")

    def test_it_never_lands_on_the_art(self):
        lines, top = ss.art_layout(ART, 40, 15)
        art_rows = set(range(top, top + len(lines)))
        rng = random.Random(9)
        for _ in range(300):
            row, _align = ss.pick_caption_slot(ART, 40, 15, rng=rng)
            self.assertNotIn(row, art_rows, "the caption was placed on the potato")

    def test_it_stays_clear_of_the_overscan_edge_when_it_can(self):
        """The top row is the most clipped edge of a real tube, and this
        caption is the only thing on screen that says how to wake the
        console. Rows below the art exist here, so those are what it uses."""
        rng = random.Random(4)
        rows = {ss.pick_caption_slot(ART, 40, 15, rng=rng)[0] for _ in range(200)}
        self.assertNotIn(0, rows)

    def test_a_screen_with_no_room_below_the_art_still_places_it(self):
        """Degenerate geometry gets a caption, not an exception."""
        tall = [("y" * 10) for _ in range(30)]
        row, align = ss.pick_caption_slot(tall, 40, 6, rng=random.Random(1))
        frame = ss.render_frame(tall, 40, 6, CAPTION, ss.CYAN, dim=True,
                                slot=(row, align))
        self.assertEqual(len(plain(frame)), 6)
        self.assertIn(CAPTION, ANSI.sub("", frame))


class TheRunningScreensaverMovesItTest(unittest.TestCase):
    """The real process, not the pure function.

    Last cycle's whole finding next door was a renderer that varied perfectly
    and a loop that called it once. A placement function nothing calls on a
    timer is the same bug with the pieces swapped, so this drives the actual
    script and reads what it painted.
    """

    def _run(self, secs=2.5, min_frames=5, **env):
        proc = subprocess.Popen(
            [sys.executable, os.path.join(BIN, "crt-screensaver.py")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={**os.environ, "CRT_COLS": "40", "CRT_ROWS": "15",
                 "CRT_SCREENSAVER_INTERVAL": "0.1", **env})
        try:
            time.sleep(secs)
        finally:
            proc.terminate()
            out, err = proc.communicate(timeout=10)
        self.assertEqual(err.decode(), "", "the screensaver wrote to stderr")
        frames = [[ANSI.sub("", ln) for ln in f.split("\n")]
                  for f in out.decode("utf-8", "replace").split("\x1b[H\x1b[2J")[1:]]
        self.assertGreaterEqual(len(frames), min_frames,
                                "the screensaver painted %d frame(s)" % len(frames))
        return frames

    def _rows(self, frames, caption):
        out = []
        for f in frames:
            for i, line in enumerate(f):
                if caption in line:
                    out.append((i, len(line) - len(line.lstrip(" "))))
                    break
        return out

    def test_the_caption_ends_up_in_more_than_one_place(self):
        caption = "wake me up"
        slots = self._rows(self._run(CRT_SCREENSAVER_CAPTION=caption,
                                     CRT_SCREENSAVER_CAPTION_MOVE_SECS="0.3"),
                           caption)
        self.assertGreater(len(set(slots)), 1,
                           "the caption held one spot for the whole run: %s"
                           % sorted(set(slots)))

    def test_zero_pins_it(self):
        """The manual escape hatch, exercised rather than asserted about."""
        caption = "wake me up"
        slots = self._rows(self._run(CRT_SCREENSAVER_CAPTION=caption,
                                     CRT_SCREENSAVER_CAPTION_MOVE_SECS="0"),
                           caption)
        self.assertEqual(len(set(slots)), 1,
                         "CRT_SCREENSAVER_CAPTION_MOVE_SECS=0 still moved it")
        # Row 13, not 14 (2026-07-28): the overscan safe-margin fix means
        # row 14 (the tube's literal last row) is now always blank
        # padding -- see crt-screensaver.py's load_safe_margins()/
        # MIN_VERTICAL_PAD, same hard floor crt-book-console.py enforces.
        self.assertEqual(slots[0], (13, (40 - len(caption)) // 2))

    def test_a_junk_interval_does_not_kill_the_face(self):
        # 2.5s of run against the 2.5s default it must fall back to: one
        # frame is the whole point -- the process is alive and drawing.
        frames = self._run(min_frames=1, CRT_SCREENSAVER_INTERVAL="two-ish")
        self.assertTrue(frames, "nothing was drawn at all")


class JunkEnvTest(unittest.TestCase):
    """A typo in crt-console.sh must not kill the console's face."""

    def _with(self, name, value):
        old = os.environ.get(name)
        os.environ[name] = value
        try:
            return ss._env_secs(name, 2.5)
        finally:
            if old is None:
                del os.environ[name]
            else:
                os.environ[name] = old

    def test_junk_falls_back_to_the_default(self):
        self.assertEqual(self._with("CRT_SCREENSAVER_INTERVAL", "two"), 2.5)
        self.assertEqual(self._with("CRT_SCREENSAVER_INTERVAL", "-4"), 2.5)
        self.assertEqual(self._with("CRT_SCREENSAVER_INTERVAL", ""), 2.5)

    def test_a_real_value_is_honoured_including_zero(self):
        self.assertEqual(self._with("CRT_SCREENSAVER_INTERVAL", "0.4"), 0.4)
        self.assertEqual(self._with("CRT_SCREENSAVER_CAPTION_MOVE_SECS", "0"), 0.0)


if __name__ == "__main__":
    unittest.main()
