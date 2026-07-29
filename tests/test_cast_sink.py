#!/usr/bin/env python3
"""crt-cast-sink.py -- crt's half of the ecosim cast contract.

The load-bearing assertions here are the two failure modes the brief names:
a too-wide SEE line must be truncated AND counted (not wrapped into mush,
not silently clipped), and an unknown channel must be counted (not silently
eaten, which would make a broken sink indistinguishable from a working one).
"""
import io
import os
import sys
import unittest
import importlib.util

BIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")
_spec = importlib.util.spec_from_file_location(
    "crt_cast_sink", os.path.join(BIN, "crt-cast-sink.py"))
cast = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cast)


def sink(width=40):
    out, err = io.StringIO(), io.StringIO()
    return cast.Sink(width, dry_run=True, out=out, err=err), out, err


class TestSee(unittest.TestCase):
    def test_paints_the_line(self):
        s, out, _ = sink()
        s.feed("SEE\tdispatch_ref wtul EQUAL")
        self.assertEqual(out.getvalue(), "dispatch_ref wtul EQUAL\n")
        self.assertEqual(s.counts["SEE"], 1)

    def test_overwide_line_is_truncated_and_counted(self):
        s, out, _ = sink(width=40)
        s.feed("SEE\t" + "x" * 60)
        self.assertEqual(out.getvalue(), "x" * 40 + "\n")
        self.assertEqual(s.counts["TRUNCATED"], 1)

    def test_exact_width_is_not_truncated(self):
        s, out, _ = sink(width=40)
        s.feed("SEE\t" + "y" * 40)
        self.assertEqual(s.counts["TRUNCATED"], 0)
        self.assertEqual(out.getvalue(), "y" * 40 + "\n")

    def test_width_follows_calibrated_margins(self):
        """Not a hardcoded 40: the sink paints to the same width
        crt-monologue.sh/crt-pager.py do, margins included."""
        old = dict(os.environ)
        try:
            os.environ["CRT_PAGER_WIDTH"] = "40"
            os.environ["CRT_PAGER_HEIGHT"] = "15"
            os.environ["CRT_DISPLAY_CONF"] = "/nonexistent-display-conf"
            self.assertEqual(cast.display_width(), 40)
        finally:
            os.environ.clear()
            os.environ.update(old)


class TestNothingIsSilent(unittest.TestCase):
    def test_unknown_channel_counted_not_eaten(self):
        s, out, err = sink()
        s.feed("HEAR\tsomething")
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(s.counts["UNKNOWN"], 1)
        self.assertIn("HEAR", err.getvalue())

    def test_missing_tab_is_malformed_not_a_see_line(self):
        s, out, _ = sink()
        s.feed("SEE this has no tab")
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(s.counts["MALFORMED"], 1)

    def test_blank_lines_ignored_without_counting(self):
        s, _, _ = sink()
        s.feed("\n")
        s.feed("   \n")
        self.assertEqual(sum(s.counts.values()), 0)

    def test_report_says_so_when_nothing_arrived(self):
        s, _, _ = sink()
        self.assertIn("nothing received", s.report())

    def test_report_names_every_nonzero_counter(self):
        s, _, _ = sink()
        s.run(io.StringIO("SEE\tok\nNOPE\tx\nno tab here\n"))
        r = s.report()
        self.assertIn("SEE=1", r)
        self.assertIn("UNKNOWN=1", r)
        self.assertIn("MALFORMED=1", r)


class TestProtocol(unittest.TestCase):
    def test_text_may_contain_tabs(self):
        s, out, _ = sink()
        s.feed("SEE\ta\tb")
        self.assertEqual(out.getvalue(), "a\tb\n")

    def test_channel_is_case_and_space_tolerant(self):
        s, out, _ = sink()
        s.feed(" see \tfine")
        self.assertEqual(out.getvalue(), "fine\n")

    def test_say_and_mark_do_not_paint_the_tube(self):
        """The tube is a person's console first. SAY/MARK go elsewhere."""
        s, out, _ = sink()
        s.feed("SAY\tthe rotation stalled")
        s.feed("MARK\tstalled")
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(s.counts["SAY"], 1)
        self.assertEqual(s.counts["MARK"], 1)

    def test_stream_of_mixed_lines(self):
        s, out, _ = sink()
        s.run(io.StringIO("SEE\tone\nSAY\ttwo\nSEE\tthree\n"))
        self.assertEqual(out.getvalue(), "one\nthree\n")
        self.assertEqual(s.counts["SEE"], 2)


if __name__ == "__main__":
    unittest.main()
