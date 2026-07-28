#!/usr/bin/env python3
# Tests for crt-screensaver.py's overscan safe-margin enforcement
# (2026-07-28, Zach-directed: "splash screen doesn't look to be going
# through the same bezel margin enforcer, bottom line cut off by
# bezel"). Same pattern as tests/test_book_console_safe_margins.py.
import datetime
import importlib.util
import os
import tempfile
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")
spec = importlib.util.spec_from_file_location("crt_screensaver_margins", os.path.join(BIN_DIR, "crt-screensaver.py"))
ss = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ss)


class TestLoadSafeMargins(unittest.TestCase):
    def test_missing_display_conf_still_floors_vertical_padding(self):
        old = os.environ.pop("CRT_DISPLAY_CONF", None)
        try:
            margins = ss.load_safe_margins()
        finally:
            if old is not None:
                os.environ["CRT_DISPLAY_CONF"] = old
        self.assertGreaterEqual(margins["top"], ss.MIN_VERTICAL_PAD)
        self.assertGreaterEqual(margins["bottom"], ss.MIN_VERTICAL_PAD)

    def test_calibrated_margin_larger_than_floor_wins(self):
        with tempfile.TemporaryDirectory() as d:
            conf = os.path.join(d, "display.conf")
            with open(conf, "w") as f:
                f.write("top=3\nbottom=2\nleft=4\nright=5\n")
            old = os.environ.get("CRT_DISPLAY_CONF")
            os.environ["CRT_DISPLAY_CONF"] = conf
            try:
                margins = ss.load_safe_margins()
            finally:
                if old is None:
                    os.environ.pop("CRT_DISPLAY_CONF", None)
                else:
                    os.environ["CRT_DISPLAY_CONF"] = old
            self.assertEqual(margins["top"], 3)
            self.assertEqual(margins["left"], 4)


class TestSafeScreenSize(unittest.TestCase):
    def test_shrinks_by_margins(self):
        w, h = ss.safe_screen_size(40, 15, {"top": 1, "bottom": 1, "left": 2, "right": 2})
        self.assertEqual((w, h), (36, 13))

    def test_never_goes_below_one(self):
        w, h = ss.safe_screen_size(40, 15, {"top": 999, "bottom": 999, "left": 999, "right": 999})
        self.assertEqual((w, h), (1, 1))


class TestPadFrameRows(unittest.TestCase):
    def test_top_row_of_output_is_always_blank_with_default_floor(self):
        # The exact live symptom (2026-07-28): the splash's bottom line
        # was eaten by the bezel. With the floor applied, row 0 AND the
        # last row of the OUTPUT must be blank padding, never content.
        margins = {"top": ss.MIN_VERTICAL_PAD, "bottom": ss.MIN_VERTICAL_PAD, "left": 0, "right": 0}
        content = ["potato art line 1", "potato art line 2"]
        out = ss.pad_frame_rows(content, margins, width=20)
        self.assertEqual(out[0].strip(), "")
        self.assertEqual(out[-1].strip(), "")
        self.assertIn("potato art line 1", out[ss.MIN_VERTICAL_PAD])

    def test_no_margins_is_a_no_op(self):
        out = ss.pad_frame_rows(["x", "y"], {"top": 0, "bottom": 0, "left": 0, "right": 0}, width=1)
        self.assertEqual(out, ["x", "y"])

    def test_adds_left_padding_to_every_row(self):
        out = ss.pad_frame_rows(["ab", "cd"], {"top": 0, "bottom": 0, "left": 3, "right": 0}, width=2)
        self.assertEqual(out, ["   ab", "   cd"])


if __name__ == "__main__":
    unittest.main()


class TestArtLayoutCaptionReservation(unittest.TestCase):
    def test_reserves_two_rows_by_default(self):
        art = ["line%d" % i for i in range(13)]
        lines, _top = ss.art_layout(art, 40, 13)
        self.assertEqual(len(lines), 11)

    def test_no_reservation_when_no_caption(self):
        # The exact live bug (2026-07-28): potato.txt's real 13-line art
        # lost its bottom 2 lines to a caption reservation for a caption
        # that (post caption-removal) was never going to be drawn.
        art = ["line%d" % i for i in range(13)]
        lines, _top = ss.art_layout(art, 40, 13, reserve_caption=False)
        self.assertEqual(len(lines), 13)

    def test_frame_rows_reserves_nothing_for_empty_caption(self):
        art = ["line%d" % i for i in range(13)]
        rows = ss._frame_rows(art, 40, 13, "", ss.CYAN, dim=True)
        self.assertTrue(any("line12" in r for r in rows),
                        "the last art line was dropped even with no caption")

    def test_frame_rows_still_reserves_for_a_real_caption(self):
        art = ["line%d" % i for i in range(13)]
        rows = ss._frame_rows(art, 40, 13, "wake me up", ss.CYAN, dim=True)
        self.assertFalse(any("line12" in r for r in rows),
                         "a real caption's reserved row should still cost the last art line")
