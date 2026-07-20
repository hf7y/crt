#!/usr/bin/env python3
# Offline tests for bin/crt-calibrate-display.py's pure logic (pattern
# rendering, margin hill-climb, feedback parsing) -- no real screen/STT
# needed, see DISPLAY-CALIBRATION.md.
import importlib.util
import os
import tempfile
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")
spec = importlib.util.spec_from_file_location(
    "crt_calibrate", os.path.join(BIN_DIR, "crt-calibrate-display.py"))
calib = importlib.util.module_from_spec(spec)
spec.loader.exec_module(calib)


class TestRenderPattern(unittest.TestCase):
    def test_output_shape_matches_canvas_size(self):
        lines = calib.render_pattern(40, 15, {"top": 1, "bottom": 1, "left": 2, "right": 2})
        self.assertEqual(len(lines), 15)
        self.assertTrue(all(len(ln) == 40 for ln in lines))

    def test_corners_are_at_inset_boundary_not_canvas_edge(self):
        margins = {"top": 2, "bottom": 2, "left": 3, "right": 3}
        lines = calib.render_pattern(40, 15, margins)
        # top-left corner letter "A" should be at (top, left), not (0,0)
        self.assertEqual(lines[2][3], "A")
        self.assertNotEqual(lines[0][0], "A")

    def test_zero_margin_uses_full_canvas(self):
        lines = calib.render_pattern(10, 5, {"top": 0, "bottom": 0, "left": 0, "right": 0})
        self.assertEqual(lines[0][0], "A")           # top-left corner
        self.assertEqual(lines[-1][-1], "D")          # bottom-right corner

    def test_larger_margin_shrinks_visible_content_area(self):
        small_margin = calib.render_pattern(20, 10, {"top": 0, "bottom": 0, "left": 0, "right": 0})
        big_margin = calib.render_pattern(20, 10, {"top": 3, "bottom": 3, "left": 4, "right": 4})
        # corner "D" moves further from the true bottom-right edge as
        # margin grows -- confirm it actually did move inward.
        small_d_col = small_margin[-1].rindex("D")
        big_d_col = big_margin[-4].rindex("D")
        self.assertLess(big_d_col, small_d_col)


class TestAdjustMargins(unittest.TestCase):
    def test_cutoff_edge_grows(self):
        new, converged = calib.adjust_margins({"top": 1}, {"top": True})
        self.assertEqual(new["top"], 2)
        self.assertFalse(converged)

    def test_fine_edge_shrinks_toward_min(self):
        new, converged = calib.adjust_margins({"top": 3}, {"top": False})
        self.assertEqual(new["top"], 2)
        self.assertFalse(converged)

    def test_fine_edge_at_minimum_does_not_go_negative(self):
        new, converged = calib.adjust_margins({"top": 0}, {"top": False}, min_margin=0)
        self.assertEqual(new["top"], 0)

    def test_all_fine_at_minimum_converges(self):
        margins = {e: 0 for e in calib.EDGES}
        feedback = {e: False for e in calib.EDGES}
        new, converged = calib.adjust_margins(margins, feedback, min_margin=0)
        self.assertTrue(converged)
        self.assertEqual(new, margins)

    def test_mixed_feedback_only_touches_reported_edges(self):
        margins = {"top": 1, "bottom": 1, "left": 1, "right": 1}
        new, converged = calib.adjust_margins(margins, {"top": True})
        self.assertEqual(new["top"], 2)
        self.assertEqual(new["bottom"], 1)
        self.assertEqual(new["left"], 1)
        self.assertEqual(new["right"], 1)

    def test_repeated_conflicting_feedback_does_not_oscillate_forever(self):
        # Alternating cut-off/fine reports for the same edge should still
        # settle (or at least not diverge) within a small bounded number
        # of rounds -- a real regression guard against an unstable loop.
        margins = {"top": 1}
        for i in range(20):
            feedback = {"top": (i % 2 == 0)}
            margins, _ = calib.adjust_margins(margins, feedback)
        self.assertLess(margins["top"], 15)   # didn't run away unbounded


class TestParseFeedback(unittest.TestCase):
    def test_all_good_phrase_clears_every_edge(self):
        fb = calib.parse_feedback("looks good")
        self.assertTrue(all(v is False for v in fb.values()))

    def test_named_edge_with_cut_word_flags_true(self):
        fb = calib.parse_feedback("the top is cut off")
        self.assertTrue(fb.get("top"))

    def test_unmentioned_edges_absent_not_false(self):
        fb = calib.parse_feedback("the top is cut off")
        self.assertNotIn("bottom", fb)


class TestConfigRoundtrip(unittest.TestCase):
    def test_save_and_load(self):
        with tempfile.NamedTemporaryFile(suffix=".conf", delete=False) as f:
            path = f.name
        try:
            margins = {"top": 3, "bottom": 2, "left": 5, "right": 1}
            calib.save_display_conf(margins, path)
            loaded = calib.load_display_conf(path)
            self.assertEqual(loaded, margins)
        finally:
            os.unlink(path)

    def test_missing_file_yields_defaults(self):
        loaded = calib.load_display_conf("/nonexistent/display.conf")
        self.assertEqual(loaded, calib.DEFAULT_MARGINS)


if __name__ == "__main__":
    unittest.main()
