#!/usr/bin/env python3
# Regression tests for bin/crt-book-console.py's overscan safe-margin
# enforcement (2026-07-28, Zach-directed: "overscan is a major problem
# ... make a rule that forces text in center, including with an extra
# padding line above and below"). Live finding: this window never
# consumed ~/.crt/display.conf at all, unlike crt-pager.py/
# crt-monologue.py -- the first real calibration test on potato showed
# row 0 getting eaten by the physical bezel.
import importlib.util
import os
import tempfile
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")

_bc_spec = importlib.util.spec_from_file_location("crt_book_console_margins", os.path.join(BIN_DIR, "crt-book-console.py"))
bc = importlib.util.module_from_spec(_bc_spec)
_bc_spec.loader.exec_module(bc)


class TestLoadSafeMargins(unittest.TestCase):
    def test_missing_display_conf_still_floors_vertical_padding(self):
        margins = bc.load_safe_margins()
        # No file on disk in a clean test env -- must NOT degrade to
        # zero margin (that's the whole bug this fixes).
        self.assertGreaterEqual(margins["top"], bc.MIN_VERTICAL_PAD)
        self.assertGreaterEqual(margins["bottom"], bc.MIN_VERTICAL_PAD)

    def test_calibrated_margin_larger_than_floor_wins(self):
        with tempfile.TemporaryDirectory() as d:
            conf = os.path.join(d, "display.conf")
            with open(conf, "w") as f:
                f.write("top=3\nbottom=2\nleft=4\nright=5\n")
            old = os.environ.get("CRT_DISPLAY_CONF")
            os.environ["CRT_DISPLAY_CONF"] = conf
            try:
                margins = bc.load_safe_margins()
            finally:
                if old is None:
                    os.environ.pop("CRT_DISPLAY_CONF", None)
                else:
                    os.environ["CRT_DISPLAY_CONF"] = old
            self.assertEqual(margins["top"], 3)
            self.assertEqual(margins["bottom"], 2)
            self.assertEqual(margins["left"], 4)
            self.assertEqual(margins["right"], 5)

    def test_calibrated_margin_smaller_than_floor_is_raised_to_floor(self):
        with tempfile.TemporaryDirectory() as d:
            conf = os.path.join(d, "display.conf")
            with open(conf, "w") as f:
                f.write("top=0\nbottom=0\n")
            old = os.environ.get("CRT_DISPLAY_CONF")
            os.environ["CRT_DISPLAY_CONF"] = conf
            try:
                margins = bc.load_safe_margins()
            finally:
                if old is None:
                    os.environ.pop("CRT_DISPLAY_CONF", None)
                else:
                    os.environ["CRT_DISPLAY_CONF"] = old
            self.assertGreaterEqual(margins["top"], bc.MIN_VERTICAL_PAD)
            self.assertGreaterEqual(margins["bottom"], bc.MIN_VERTICAL_PAD)


class TestSafeScreenSize(unittest.TestCase):
    def test_shrinks_by_margins(self):
        w, h = bc.safe_screen_size({"top": 1, "bottom": 1, "left": 2, "right": 2})
        raw_w, raw_h = bc.bg.detect_screen_size()
        self.assertEqual(w, max(1, raw_w - 4))
        self.assertEqual(h, max(1, raw_h - 2))

    def test_never_goes_below_one(self):
        w, h = bc.safe_screen_size({"top": 999, "bottom": 999, "left": 999, "right": 999})
        self.assertEqual(w, 1)
        self.assertEqual(h, 1)


class TestPadForMargins(unittest.TestCase):
    def test_adds_blank_lines_above_and_below(self):
        out = bc.pad_for_margins(["hello"], {"top": 2, "bottom": 3, "left": 0, "right": 0}, width=5)
        self.assertEqual(len(out), 2 + 1 + 3)
        self.assertEqual(out[0], " " * 5)
        self.assertEqual(out[1], " " * 5)
        self.assertEqual(out[2], "hello")
        self.assertEqual(out[3], " " * 5)
        self.assertEqual(out[4], " " * 5)
        self.assertEqual(out[5], " " * 5)

    def test_adds_left_padding_to_every_line(self):
        out = bc.pad_for_margins(["ab", "cd"], {"top": 0, "bottom": 0, "left": 3, "right": 0}, width=2)
        self.assertEqual(out, ["   ab", "   cd"])

    def test_no_margins_is_a_no_op(self):
        out = bc.pad_for_margins(["x", "y"], {"top": 0, "bottom": 0, "left": 0, "right": 0}, width=1)
        self.assertEqual(out, ["x", "y"])

    def test_top_row_content_never_lands_on_row_zero_with_default_floor(self):
        # The exact live symptom (2026-07-28): row 0 of raw content got
        # eaten by the bezel. With any top margin applied, row 0 of the
        # OUTPUT must be blank padding, never real content.
        margins = {"top": bc.MIN_VERTICAL_PAD, "bottom": bc.MIN_VERTICAL_PAD, "left": 0, "right": 0}
        out = bc.pad_for_margins(["A    1    2    3    4    5    6    B"], margins, width=37)
        self.assertEqual(out[0].strip(), "")
        self.assertIn("A", out[bc.MIN_VERTICAL_PAD])


if __name__ == "__main__":
    unittest.main()
