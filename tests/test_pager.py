#!/usr/bin/env python3
# Offline test suite for bin/crt-pager.py's pure rendering logic --
# runnable with zero VM/hardware access, exactly the "debug test suite for
# the graphics" gap this project had: nothing previously caught a
# wrap/width bug before it reached a real (unreachable-from-here) screen.
#
# Run: python3 tests/test_pager.py
import io
import os
import sys
import tempfile
import unittest
import importlib.util
import contextlib

BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")


def load_pager(env=None):
    """Fresh import each time (module-level WIDTH/HEIGHT are computed at
    import time from detect_size()), with a controlled environment."""
    old_env = dict(os.environ)
    try:
        if env is not None:
            os.environ.clear()
            os.environ.update(env)
        spec = importlib.util.spec_from_file_location(
            "crt_pager_under_test", os.path.join(BIN_DIR, "crt-pager.py"))
        mod = importlib.util.module_from_spec(spec)
        sys.argv = ["crt-pager.py"]
        spec.loader.exec_module(mod)
        return mod
    finally:
        os.environ.clear()
        os.environ.update(old_env)


@contextlib.contextmanager
def zero_margin_conf():
    """A display.conf that explicitly turns the overscan margin OFF.

    Needed since 2026-07-29: an ABSENT conf no longer means zero margin, it
    means crt-pager.DEFAULT_MARGINS (every real tube here overscans, so zero
    was the dangerous default rather than the neutral one). Tests whose
    subject is size DETECTION have to say "no margin" out loud now, instead
    of getting it for free by not writing a conf file."""
    with tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False) as f:
        f.write("top=0\nbottom=0\nleft=0\nright=0\n")
        path = f.name
    try:
        yield path
    finally:
        os.unlink(path)


class TestDetectSize(unittest.TestCase):
    def test_env_override_wins(self):
        with zero_margin_conf() as conf:
            m = load_pager({"CRT_PAGER_WIDTH": "40", "CRT_PAGER_HEIGHT": "14",
                            "CRT_DISPLAY_CONF": conf,
                            "PATH": os.environ.get("PATH", "")})
        self.assertEqual((m.WIDTH, m.HEIGHT), (40, 14))

    def test_columns_lines_env_detected(self):
        with zero_margin_conf() as conf:
            m = load_pager({"COLUMNS": "100", "LINES": "30",
                            "CRT_DISPLAY_CONF": conf,
                            "PATH": os.environ.get("PATH", "")})
        self.assertEqual(m.WIDTH, 100)
        self.assertEqual(m.HEIGHT, 29)  # one line reserved for footer

    def test_falls_back_when_nothing_available(self):
        with zero_margin_conf() as conf:
            m = load_pager({"CRT_DISPLAY_CONF": conf,
                            "PATH": os.environ.get("PATH", "")})
        # No COLUMNS/LINES, no real tty in this sandbox -> hardware fallback.
        self.assertEqual(m.WIDTH, m.FALLBACK_WIDTH)
        self.assertGreaterEqual(m.HEIGHT, 2)


class TestDisplayMargins(unittest.TestCase):
    def test_no_conf_file_falls_back_to_the_safe_default(self):
        # Changed 2026-07-29, deliberately. This used to assert (40, 14) --
        # "no conf is a no-op". An uncalibrated console then ran its text off
        # the physical edge of the tube, which is the failure mode, not the
        # safe state. The default is now the profile Zach confirmed by eye on
        # potato; an explicit conf still wins on every edge it names.
        m = load_pager({"CRT_PAGER_WIDTH": "40", "CRT_PAGER_HEIGHT": "14",
                         "CRT_DISPLAY_CONF": "/nonexistent/display.conf",
                         "PATH": os.environ.get("PATH", "")})
        self.assertEqual((m.WIDTH, m.HEIGHT), (36, 12))

    def test_the_default_profile_is_the_one_confirmed_on_the_tube(self):
        m = load_pager({"PATH": os.environ.get("PATH", "")})
        self.assertEqual(m.DEFAULT_MARGINS,
                         {"top": 1, "bottom": 1, "left": 2, "right": 2})

    def test_a_conf_that_names_only_one_edge_keeps_the_default_elsewhere(self):
        with tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False) as f:
            f.write("left=5\n")
            path = f.name
        try:
            m = load_pager({"CRT_DISPLAY_CONF": path,
                            "PATH": os.environ.get("PATH", "")})
            margins = m.load_display_margins(path)
        finally:
            os.unlink(path)
        self.assertEqual(margins["left"], 5)
        self.assertEqual(margins["right"], 2)
        self.assertEqual(margins["top"], 1)

    def test_conf_margins_shrink_effective_size(self):
        with tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False) as f:
            f.write("top=1\nbottom=1\nleft=2\nright=2\n")
            path = f.name
        try:
            m = load_pager({"CRT_PAGER_WIDTH": "40", "CRT_PAGER_HEIGHT": "14",
                             "CRT_DISPLAY_CONF": path,
                             "PATH": os.environ.get("PATH", "")})
            self.assertEqual((m.WIDTH, m.HEIGHT), (36, 12))
        finally:
            os.unlink(path)

    def test_margins_applied_even_with_explicit_env_override(self):
        # The margin represents a physical overscan crop, true regardless
        # of how WIDTH/HEIGHT were determined -- must still apply on top
        # of an explicit CRT_PAGER_WIDTH/HEIGHT override.
        with tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False) as f:
            f.write("left=5\nright=5\n")
            path = f.name
        try:
            m = load_pager({"CRT_PAGER_WIDTH": "40", "CRT_PAGER_HEIGHT": "14",
                             "CRT_DISPLAY_CONF": path,
                             "PATH": os.environ.get("PATH", "")})
            self.assertEqual(m.WIDTH, 30)
        finally:
            os.unlink(path)

    def test_margin_never_shrinks_below_one(self):
        with tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False) as f:
            f.write("left=100\nright=100\ntop=100\nbottom=100\n")
            path = f.name
        try:
            m = load_pager({"CRT_PAGER_WIDTH": "40", "CRT_PAGER_HEIGHT": "14",
                             "CRT_DISPLAY_CONF": path,
                             "PATH": os.environ.get("PATH", "")})
            self.assertGreaterEqual(m.WIDTH, 1)
            self.assertGreaterEqual(m.HEIGHT, 1)
        finally:
            os.unlink(path)


class TestWrapLines(unittest.TestCase):
    def setUp(self):
        self.m = load_pager({"CRT_PAGER_WIDTH": "10", "CRT_PAGER_HEIGHT": "5",
                              "PATH": os.environ.get("PATH", "")})

    def test_wraps_at_width(self):
        lines = self.m.wrap_lines("one two three four five")
        for ln in lines:
            self.assertLessEqual(len(ln), 10)

    def test_preserves_blank_paragraph_separators(self):
        lines = self.m.wrap_lines("first\n\nsecond")
        self.assertIn("", lines)

    def test_empty_text_yields_no_crash(self):
        lines = self.m.wrap_lines("")
        self.assertEqual(lines, [])


class TestRender(unittest.TestCase):
    def setUp(self):
        # Zero margin explicitly: this class is about the footer and the
        # wrap, and a 3-row box silently becoming a 1-row box under the
        # 2026-07-29 default margin would make these assertions test
        # something other than what they name.
        with zero_margin_conf() as conf:
            self.m = load_pager({"CRT_PAGER_WIDTH": "10", "CRT_PAGER_HEIGHT": "3",
                                 "CRT_DISPLAY_CONF": conf,
                                 "PATH": os.environ.get("PATH", "")})

    def _capture(self, lines, top):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.m.render(lines, top)
        return buf.getvalue()

    def test_shows_end_when_all_content_visible(self):
        out = self._capture(["a", "b"], 0)
        self.assertIn("END", out)

    def test_shows_more_when_content_remains(self):
        out = self._capture(["a", "b", "c", "d", "e"], 0)
        self.assertIn("MORE", out)

    def test_pads_short_content_to_full_height(self):
        out = self._capture(["only one line"], 0)
        # HEIGHT=3 -> exactly 3 content lines + 1 footer line, always,
        # regardless of how little text there is (fixed CRT geometry).
        content_lines = out.split("\n")[:-1]  # last line is the footer
        self.assertEqual(len(content_lines), self.m.HEIGHT)


if __name__ == "__main__":
    unittest.main()
