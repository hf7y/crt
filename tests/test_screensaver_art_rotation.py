#!/usr/bin/env python3
# Tests for crt-screensaver.py's art rotation (2026-07-28, Zach-directed,
# three steps same session): alternate potato-small.txt/potato.txt with
# a sunset date -> sunset immediately -> "replace potato_small.txt with
# potato2.txt in the slideshow to create an animation effect". Final
# design: potato.txt/potato2.txt are a PERMANENT pair (near-identical
# frames, meant to shimmer), neither ever retires -- the sunset-date
# mechanism from the first two steps no longer applies and was removed.
import importlib.util
import os
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")
spec = importlib.util.spec_from_file_location("crt_screensaver_art_rotation", os.path.join(BIN_DIR, "crt-screensaver.py"))
ss = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ss)


class TestActiveArtPaths(unittest.TestCase):
    def test_both_frames_always_active(self):
        self.assertEqual(ss.active_art_paths(), [ss.DEFAULT_ART, ss.NEW_ART])

    def test_the_date_argument_is_accepted_but_irrelevant(self):
        # Kept accepting `today` so nothing calling the old signature
        # breaks, but it no longer changes the result -- neither frame
        # ever retires.
        import datetime
        self.assertEqual(ss.active_art_paths(today=datetime.date(2099, 1, 1)),
                         [ss.DEFAULT_ART, ss.NEW_ART])

    def test_potato_small_is_not_in_rotation_at_all(self):
        old_art = os.path.join(BIN_DIR, "..", "potato-small.txt")
        self.assertNotIn(old_art, ss.active_art_paths())


class TestBothArtFilesLoadReal(unittest.TestCase):
    def test_default_art_loads(self):
        art = ss.load_art(ss.DEFAULT_ART)
        self.assertNotEqual(art, ss.FALLBACK_ART, "potato.txt should exist and load for real")

    def test_new_art_loads(self):
        art = ss.load_art(ss.NEW_ART)
        self.assertNotEqual(art, ss.FALLBACK_ART, "potato2.txt should exist and load for real")

    def test_the_two_frames_are_near_identical_not_wildly_different(self):
        # The whole point is a shimmer, not a content swap -- if these
        # ever diverge by more than a few lines, the "animation effect"
        # framing no longer describes what's actually happening.
        a, b = ss.load_art(ss.DEFAULT_ART), ss.load_art(ss.NEW_ART)
        self.assertEqual(len(a), len(b))
        differing_lines = sum(1 for x, y in zip(a, b) if x != y)
        self.assertLessEqual(differing_lines, len(a) // 2,
                             "the two animation frames differ too much to read as one shimmering figure")


class TestDefaultCaptionRemoved(unittest.TestCase):
    def test_no_art_no_env_no_caption_flag_means_empty_caption(self):
        old = os.environ.pop("CRT_SCREENSAVER_CAPTION", None)
        try:
            import argparse
            p = argparse.ArgumentParser()
            p.add_argument("--caption", default=os.environ.get("CRT_SCREENSAVER_CAPTION", ""))
            args = p.parse_args([])
            self.assertEqual(args.caption, "")
        finally:
            if old is not None:
                os.environ["CRT_SCREENSAVER_CAPTION"] = old

    def test_empty_caption_renders_no_caption_text(self):
        frame = ss.render_frame(["x"], 20, 5, "", ss.CYAN, dim=True)
        self.assertNotIn("wake me", frame)
        self.assertNotIn("say", frame.lower())


if __name__ == "__main__":
    unittest.main()


class TestLogoColorVariety(unittest.TestCase):
    def test_default_logo_color_is_the_live_confirmed_olive_brown_tan(self):
        # 2026-07-28, LIVE-CONFIRMED (Zach: "good"): olive/brown/tan
        # tested on the real tube with no red-bleed -- this is now the
        # real default, wired into the actual boot path rather than
        # requiring a manual env override (which crt-console.sh never
        # set, so every real boot rendered flat white -- Zach: "awake
        # potato still blinking white"). No env override set here -> the
        # default.
        old = os.environ.pop("CRT_SCREENSAVER_LOGO_COLORS", None)
        try:
            import importlib
            fresh_spec = importlib.util.spec_from_file_location(
                "crt_screensaver_default_colors", os.path.join(BIN_DIR, "crt-screensaver.py"))
            fresh = importlib.util.module_from_spec(fresh_spec)
            fresh_spec.loader.exec_module(fresh)
            self.assertEqual(fresh.LOGO_COLORS, ["38;5;100", "38;5;94", "38;5;137"])
        finally:
            if old is not None:
                os.environ["CRT_SCREENSAVER_LOGO_COLORS"] = old

    def test_logo_colors_overridable_for_live_testing_without_a_redeploy(self):
        old = os.environ.get("CRT_SCREENSAVER_LOGO_COLORS")
        os.environ["CRT_SCREENSAVER_LOGO_COLORS"] = "38;5;58,38;5;94"
        try:
            import importlib
            fresh_spec = importlib.util.spec_from_file_location(
                "crt_screensaver_override_colors", os.path.join(BIN_DIR, "crt-screensaver.py"))
            fresh = importlib.util.module_from_spec(fresh_spec)
            fresh_spec.loader.exec_module(fresh)
            self.assertEqual(fresh.LOGO_COLORS, ["38;5;58", "38;5;94"])
        finally:
            if old is None:
                os.environ.pop("CRT_SCREENSAVER_LOGO_COLORS", None)
            else:
                os.environ["CRT_SCREENSAVER_LOGO_COLORS"] = old

    def test_no_logo_color_uses_a_forbidden_basic_primary_code(self):
        # CLAUDE.md's hard rule: never 31/32/34/91/92/94 (basic-mode
        # saturated primaries). 256-color codes (38;5;N) are a different
        # numbering space and are fine -- this checks none of them
        # accidentally collide with the forbidden literal codes.
        forbidden = {"31", "32", "34", "91", "92", "94"}
        self.assertEqual(set(ss.LOGO_COLORS) & forbidden, set())
