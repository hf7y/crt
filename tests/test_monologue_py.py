#!/usr/bin/env python3
# Offline test suite for bin/crt-monologue.py's pure render() logic --
# the "mono" window's actually-live script (crt-monologue.sh is a dead
# wrapper, see vault:crt/REFACTOR-ASSESSMENT.md), never had a direct test before
# (coverage gap tracked in FOCUS.md's batch backlog item 5c).
#   [rest: vault:crt/header-archaeology-20260817.md]
import contextlib
import importlib.util
import io
import os
import shutil
import sys
import tempfile
import time
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")


def load_monologue():
    spec = importlib.util.spec_from_file_location(
        "crt_monologue_under_test", os.path.join(BIN_DIR, "crt-monologue.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class RenderTest(unittest.TestCase):
    # The env stays applied for the whole test, not just for the import
    # (2026-07-25): size is now resolved per frame rather than frozen at
    # import, which is the point -- this window is created inside a DETACHED
    # tmux session and only learns the tube's real geometry once a client
    # attaches. CRT_DISPLAY_CONF points at an explicit ZERO profile: since
    # 2026-07-29 an absent conf falls back to DEFAULT_MARGINS, which turned
    # these stale-line and wrap cases into a 6x2 box with nothing in it.
    ENV = {
        "CRT_PAGER_WIDTH": "10",
        "CRT_MONO_HEIGHT": "4",
        "CRT_MONO_STALE_SECS": "6",
        "CRT_MONO_DROP_SECS": "45",
    }

    @classmethod
    def setUpClass(cls):
        cls._conf_dir = tempfile.mkdtemp()
        conf = os.path.join(cls._conf_dir, "display.conf")
        with open(conf, "w") as f:
            f.write("top=0\nbottom=0\nleft=0\nright=0\n")
        cls.ENV = dict(cls.ENV, CRT_DISPLAY_CONF=conf)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._conf_dir, ignore_errors=True)

    def setUp(self):
        for k, v in self.ENV.items():
            old = os.environ.get(k)
            self.addCleanup(
                os.environ.__setitem__ if old is not None else
                (lambda key, _v: os.environ.pop(key, None)), k, old)
            os.environ[k] = v
        self.mod = load_monologue()

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
