#!/usr/bin/env python3
# Offline test suite for bin/crt-monologue.py's pure render() logic --
# the "mono" window's actually-live script (crt-monologue.sh is a dead
# wrapper, see REFACTOR-ASSESSMENT.md), never had a direct test before
# (coverage gap tracked in FOCUS.md's batch backlog item 5c).
#
# main()'s tail-a-real-file loop isn't unit-testable without a live
# terminal/log, so this only exercises render(): fresh-vs-stale styling,
# width wrapping, and view height padding/truncation -- the parts that
# would silently misrender on the real tube with no test to catch it.
#
# Run: python3 tests/test_monologue_py.py
import contextlib
import importlib.util
import io
import os
import sys
import time
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")


def load_monologue(env=None):
    old_env = dict(os.environ)
    try:
        if env is not None:
            os.environ.clear()
            os.environ.update(env)
        spec = importlib.util.spec_from_file_location(
            "crt_monologue_under_test", os.path.join(BIN_DIR, "crt-monologue.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        os.environ.clear()
        os.environ.update(old_env)


class RenderTest(unittest.TestCase):
    def setUp(self):
        self.mod = load_monologue({
            "CRT_PAGER_WIDTH": "10",
            "CRT_MONO_HEIGHT": "4",
            "CRT_MONO_STALE_SECS": "6",
            "CRT_MONO_DROP_SECS": "45",
        })

    def render(self, buf):
        buf_out = io.StringIO()
        with contextlib.redirect_stdout(buf_out):
            self.mod.render(buf)
        out = buf_out.getvalue()
        clear = "\x1b[H\x1b[2J"
        self.assertTrue(out.startswith(clear))
        return out[len(clear):]

    def test_fresh_line_has_no_timestamp_or_dim_code(self):
        now = time.time()
        out = self.render([(now, "hello", "")])
        self.assertNotIn(self.mod.DIM_CODE, out)
        self.assertIn("hello", out)

    def test_stale_line_gets_hex_timestamp_and_dimmed(self):
        old = time.time() - 100  # well past STALE_SECS=6
        out = self.render([(old, "hello", "beefcafe")])
        self.assertIn(self.mod.DIM_CODE, out)
        self.assertIn("beefcafe", out)
        self.assertIn(self.mod.RESET, out)

    def test_stale_prefix_only_on_first_wrapped_line(self):
        # A long stale line wraps into multiple physical lines -- only the
        # first should carry the hex-timestamp prefix, the rest just dim.
        old = time.time() - 100
        out = self.render([(old, "a longer line that wraps twice over", "cafe")])
        self.assertEqual(out.count("cafe"), 1)

    def test_wraps_to_configured_width(self):
        now = time.time()
        out = self.render([(now, "a" * 25, "")])
        for line in out.split("\n"):
            plain = line.replace(self.mod.DIM_CODE, "").replace(self.mod.RESET, "")
            self.assertLessEqual(len(plain), 10)

    def test_view_padded_to_height_when_short(self):
        now = time.time()
        out = self.render([(now, "hi", "")])
        lines = out.split("\n")
        self.assertEqual(len(lines), 4)  # CRT_MONO_HEIGHT=4

    def test_view_truncated_to_last_n_lines_when_long(self):
        now = time.time()
        buf = [(now, "line%d" % i, "") for i in range(10)]
        out = self.render(buf)
        lines = out.split("\n")
        self.assertEqual(len(lines), 4)
        # Should show the LAST 4 lines (most recent), not the first.
        self.assertIn("line9", out)
        self.assertNotIn("line0", out)

    def test_empty_buffer_renders_blank_view(self):
        out = self.render([])
        lines = out.split("\n")
        self.assertEqual(len(lines), 4)
        self.assertTrue(all(l == "" for l in lines))

    def test_clears_screen_before_content(self):
        buf_out = io.StringIO()
        with contextlib.redirect_stdout(buf_out):
            self.mod.render([(time.time(), "x", "")])
        self.assertTrue(buf_out.getvalue().startswith("\x1b[H\x1b[2J"))


if __name__ == "__main__":
    unittest.main()
