#!/usr/bin/env python3
# Offline test: window 1 has to fit the pane it is actually in (2026-07-25).
#
# bin/crt-monologue.py is the live script on the "mono" window -- the console's
# only text surface, and where every "the fault is here" line this project has
#   [rest: vault:crt/header-archaeology-20260817.md]
import importlib.util
import io
import os
import shutil
import tempfile
import time
import unittest
from contextlib import redirect_stdout

BIN_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))

SIZE_ENV = ("CRT_PAGER_WIDTH", "CRT_MONO_HEIGHT", "CRT_COLS", "CRT_ROWS",
            "CRT_DISPLAY_CONF")


class ViewportBase(unittest.TestCase):
    def setUp(self):
        for k in SIZE_ENV:
            old = os.environ.pop(k, None)
            if old is not None:
                self.addCleanup(os.environ.__setitem__, k, old)
            else:
                self.addCleanup(os.environ.pop, k, None)
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir, True)
        # A ZERO profile unless a test writes its own, so these assert
        # against a known margin rather than the host's own display.conf.
        # An absent conf means DEFAULT_MARGINS: "write no file" stopped
        # meaning "no margin".
        self.conf = os.path.join(self.tmpdir, "display.conf")
        os.environ["CRT_DISPLAY_CONF"] = self.conf
        with open(self.conf, "w") as f:
            f.write("top=0\nbottom=0\nleft=0\nright=0\n")
        spec = importlib.util.spec_from_file_location(
            "crt_monologue_viewport", os.path.join(BIN_DIR, "crt-monologue.py"))
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def set_terminal(self, cols, lines):
        self.mod.terminal_size = lambda: os.terminal_size((cols, lines))

    def write_conf(self, text):
        with open(self.conf, "w") as f:
            f.write(text)
        self.mod._pager = None      # margins are re-read; the module is cached

    def frame(self, buf):
        out = io.StringIO()
        with redirect_stdout(out):
            self.mod.render(buf)
        return out.getvalue()[len("\x1b[H\x1b[2J"):].split("\n")

    def plain(self, line):
        return line.replace(self.mod.DIM_CODE, "").replace(self.mod.RESET, "")


class TestSizeIsReadPerFrame(ViewportBase):
    def test_height_follows_the_pane_after_the_client_attaches(self):
        # The whole bug: this process starts detached at 80x24 and the tube
        # arrives later at 40x15. A size frozen at import never learns.
        self.set_terminal(80, 24)
        self.assertEqual(len(self.frame([])), 24)
        self.set_terminal(40, 15)
        self.assertEqual(len(self.frame([])), 15)

    def test_width_follows_the_pane_too(self):
        self.set_terminal(80, 24)
        wide = self.frame([(time.time(), "w" * 200, "")])
        self.assertTrue(any(len(self.plain(l)) > 40 for l in wide))
        self.set_terminal(40, 15)
        narrow = self.frame([(time.time(), "w" * 200, "")])
        self.assertTrue(all(len(self.plain(l)) <= 40 for l in narrow))

    def test_a_full_frame_never_exceeds_the_pane(self):
        # More text than fits, at the geometry CLAUDE.md states for the tube.
        self.set_terminal(40, 15)
        old = time.time() - 100        # stale: the ljust/dim branch
        buf = [(old, "a thought long enough to wrap %d" % i, "%05x" % i)
               for i in range(40)]
        lines = self.frame(buf)
        self.assertEqual(len(lines), 15)
        for line in lines:
            self.assertLessEqual(len(self.plain(line)), 40)


class TestPinsAndOverrides(ViewportBase):
    def test_console_sh_pins_win_over_a_detached_sessions_size(self):
        # CRT_COLS/CRT_ROWS are what crt-console.sh already exports for
        # crt-screensaver.py, for exactly this reason.
        self.set_terminal(80, 24)
        os.environ["CRT_COLS"], os.environ["CRT_ROWS"] = "40", "15"
        self.assertEqual(self.mod.viewport(), (40, 15))

    def test_explicit_env_size_wins_over_the_pins(self):
        self.set_terminal(80, 24)
        os.environ["CRT_COLS"], os.environ["CRT_ROWS"] = "40", "15"
        os.environ["CRT_PAGER_WIDTH"], os.environ["CRT_MONO_HEIGHT"] = "20", "8"
        self.assertEqual(self.mod.viewport(), (20, 8))

    def test_junk_in_the_environment_falls_through_to_the_terminal(self):
        # An empty or unparseable pin must not be read as a zero-width pane.
        self.set_terminal(40, 15)
        os.environ["CRT_COLS"], os.environ["CRT_ROWS"] = "", "not-a-number"
        self.assertEqual(self.mod.viewport(), (40, 15))

    def test_a_terminal_that_cannot_be_measured_falls_back_to_the_tube(self):
        def unmeasurable(*a, **k):
            raise OSError("not a tty")
        self.mod.shutil.get_terminal_size = unmeasurable
        self.assertEqual(self.mod.viewport(),
                         (self.mod.FALLBACK_WIDTH, self.mod.FALLBACK_HEIGHT))


class TestOverscanMargin(ViewportBase):
    def test_the_calibrated_safe_margin_shrinks_both_dimensions(self):
        self.set_terminal(40, 15)
        self.write_conf("top=1\nbottom=1\nleft=3\nright=3\n")
        self.assertEqual(self.mod.viewport(), (34, 13))

    def test_no_conf_file_falls_back_to_the_safe_default(self):
        # Inverted deliberately: text off the edge of an uncalibrated tube
        # is the failure mode, so an absent conf gets DEFAULT_MARGINS.
        self.set_terminal(40, 15)
        os.remove(self.conf)
        self.mod._pager = None
        self.assertEqual(self.mod.viewport(), (36, 13))

    def test_the_margin_applies_to_a_pinned_size_too(self):
        # The margin is a physical crop of the picture tube -- true no matter
        # where the number came from. Same rule as crt-pager.py's
        # apply_margins() and crt-monologue.sh's.
        self.set_terminal(80, 24)
        os.environ["CRT_COLS"], os.environ["CRT_ROWS"] = "40", "15"
        self.write_conf("left=2\nright=2\ntop=2\nbottom=2\n")
        self.assertEqual(self.mod.viewport(), (36, 11))

    def test_an_absurd_margin_never_produces_a_zero_width_pane(self):
        self.set_terminal(40, 15)
        self.write_conf("left=100\nright=100\ntop=100\nbottom=100\n")
        self.assertEqual(self.mod.viewport(), (1, 1))
        self.frame([(time.time(), "still renders", "")])   # must not raise


class TestTheMarginIsActuallyOnTheScreen(ViewportBase):
    """Shrinking the box is only half the job.

    display.conf said left=2 and the first characters of a line were still
    unreadable on the tube: render() homes to `\\x1b[H` and prints at physical
    column 1, so a smaller width pulled the RIGHT edge in and left the left
    edge where overscan was eating it. Every assertion above passed the whole
    time -- they test viewport() arithmetic, not where a character lands."""

    def test_the_left_margin_indents_the_text(self):
        self.set_terminal(40, 15)
        self.write_conf("top=0\nbottom=0\nleft=3\nright=3\n")
        lines = self.frame([(time.time(), "x" * 60, "")])
        body = [l for l in lines if l.strip()]
        self.assertTrue(body, "expected rendered text")
        for line in body:
            self.assertTrue(self.plain(line).startswith("   "),
                            "line is not indented: %r" % line)
            self.assertEqual(self.plain(line)[3], "x")

    def test_the_top_margin_leaves_blank_rows_above_the_text(self):
        self.set_terminal(40, 15)
        self.write_conf("top=2\nbottom=1\nleft=0\nright=0\n")
        lines = self.frame([(time.time(), "hello", "")])
        self.assertEqual(lines[0].strip(), "")
        self.assertEqual(lines[1].strip(), "")

    def test_the_padded_frame_still_exactly_fills_the_pane(self):
        # The margin comes out of the content, never on top of a full-height
        # frame: an extra row scrolls the top one away.
        self.set_terminal(40, 15)
        self.write_conf("top=1\nbottom=1\nleft=2\nright=2\n")
        buf = [(time.time(), "a thought long enough to wrap %d" % i, "")
               for i in range(40)]
        lines = self.frame(buf)
        self.assertEqual(len(lines), 15)
        for line in lines:
            self.assertLessEqual(len(self.plain(line)), 40)

    def test_no_margin_means_no_indent(self):
        self.set_terminal(40, 15)
        lines = self.frame([(time.time(), "hello", "")])
        self.assertEqual(self.plain(lines[0]), "hello")


class TestWindowOneNeverGoesDark(ViewportBase):
    def test_a_missing_crt_pager_degrades_to_no_margin(self):
        # A permanently dark window 1 is the worse failure mode (CLAUDE.md
        # says so about the bridge's marker fallback; it is just as true of the
        # thing doing the rendering). Losing the overscan inset is a bad frame;
        # raising here is no frame at all, forever.
        self.mod.BIN_DIR = os.path.join(self.tmpdir, "empty")
        os.makedirs(self.mod.BIN_DIR)
        self.mod._pager = None
        self.set_terminal(40, 15)
        self.assertEqual(self.mod.viewport(), (40, 15))
        self.assertEqual(len(self.frame([])), 15)

    def test_an_unreadable_conf_file_degrades_to_no_margin(self):
        os.remove(self.conf)            # setUp's zero profile
        os.makedirs(self.conf)          # a directory where a file belongs
        self.mod._pager = None
        self.set_terminal(40, 15)
        self.assertEqual(self.mod.viewport(), (40, 15))


if __name__ == "__main__":
    unittest.main(verbosity=2)
