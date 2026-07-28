#!/usr/bin/env python3
# Tests for crt-screensaver.py's dual-art alternation (2026-07-28,
# Zach-directed): "have the splash screen alternate between existing
# potato ascii and potato.txt ... remove 'say potato to wake' ... plan
# to sunset old potato in favor of new potato.txt, hardcode expiration."
import datetime
import importlib.util
import os
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")
spec = importlib.util.spec_from_file_location("crt_screensaver_art_rotation", os.path.join(BIN_DIR, "crt-screensaver.py"))
ss = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ss)


class TestActiveArtPaths(unittest.TestCase):
    def test_before_sunset_both_arts_active(self):
        before = ss.OLD_ART_SUNSET_DATE - datetime.timedelta(days=1)
        paths = ss.active_art_paths(today=before)
        self.assertEqual(paths, [ss.DEFAULT_ART, ss.NEW_ART])

    def test_on_sunset_date_only_new_art(self):
        paths = ss.active_art_paths(today=ss.OLD_ART_SUNSET_DATE)
        self.assertEqual(paths, [ss.NEW_ART])

    def test_after_sunset_only_new_art(self):
        after = ss.OLD_ART_SUNSET_DATE + datetime.timedelta(days=30)
        paths = ss.active_art_paths(today=after)
        self.assertEqual(paths, [ss.NEW_ART])

    def test_default_art_file_actually_retires_not_just_deprioritized(self):
        after = ss.OLD_ART_SUNSET_DATE + datetime.timedelta(days=1)
        self.assertNotIn(ss.DEFAULT_ART, ss.active_art_paths(today=after))


class TestBothArtFilesLoadReal(unittest.TestCase):
    def test_default_art_loads(self):
        art = ss.load_art(ss.DEFAULT_ART)
        self.assertNotEqual(art, ss.FALLBACK_ART, "potato-small.txt should exist and load for real")

    def test_new_art_loads(self):
        art = ss.load_art(ss.NEW_ART)
        self.assertNotEqual(art, ss.FALLBACK_ART, "potato.txt should exist and load for real")


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
