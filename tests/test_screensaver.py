#!/usr/bin/env python3
# Offline tests for bin/crt-screensaver.py: art loading + fallback,
# centering, --once single-frame render, and the CLAUDE.md CRT-safe color
# rule (no saturated primaries anywhere in output).
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import unittest

BIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")
spec = importlib.util.spec_from_file_location("screensaver",
                                              os.path.join(BIN, "crt-screensaver.py"))
ss = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ss)

FORBIDDEN = re.compile(r"\x1b\[[0-9;]*(31|32|34|91|92|94)[;m]")


class TestArt(unittest.TestCase):
    def test_missing_file_falls_back_not_crash(self):
        art = ss.load_art("/no/such/potato.txt")
        self.assertTrue(art)
        self.assertEqual(art, ss.FALLBACK_ART)

    def test_loads_real_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write("line one\nline two\n\n\n")
            path = f.name
        try:
            art = ss.load_art(path)
            self.assertEqual(art, ["line one", "line two"])  # trailing blanks trimmed
        finally:
            os.unlink(path)

    def test_bundled_potato_art_present(self):
        path = os.path.join(os.path.dirname(BIN), "potato-small.txt")
        self.assertTrue(os.path.exists(path), "potato-small.txt should ship with the repo")


class TestRender(unittest.TestCase):
    def test_frame_clears_and_centers(self):
        frame = ss.render_frame(["abc"], 40, 15, "cap", ss.CYAN, dim=True)
        self.assertIn("\x1b[2J", frame)   # cleared
        self.assertIn("abc", frame)
        self.assertIn("cap", frame)

    def test_no_forbidden_colors(self):
        frame = ss.render_frame(["potato"], 40, 15, "say potato", ss.CYAN, dim=True)
        self.assertIsNone(FORBIDDEN.search(frame),
                          "screensaver must not emit CRT-unsafe primary colors")


class TestCli(unittest.TestCase):
    def test_once_renders_and_exits(self):
        r = subprocess.run([sys.executable, os.path.join(BIN, "crt-screensaver.py"), "--once"],
                           capture_output=True, text=True,
                           env={**os.environ, "CRT_COLS": "40", "CRT_ROWS": "15"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("\x1b[2J", r.stdout)
        self.assertIsNone(FORBIDDEN.search(r.stdout))


if __name__ == "__main__":
    unittest.main()
