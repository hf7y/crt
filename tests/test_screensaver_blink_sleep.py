#!/usr/bin/env python3
# Tests for crt-screensaver.py's blink model and sleep/wake state
# (2026-07-28, Zach-directed): "make the shimmer stay long on potato.txt
# with a quick potato2.txt, random delay, about 80-90% on potato one.
# this is a blink." then "have potato 2 for long stretches 'potato is
# asleep' ... on any sound, volume over threshold, go to the blink
# animation ... then have a >60s silence resulting in sleep again."
import importlib.util
import os
import random
import tempfile
import time
import unittest
import re

BIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")
spec = importlib.util.spec_from_file_location("crt_screensaver_blink_sleep", os.path.join(BIN_DIR, "crt-screensaver.py"))
ss = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ss)


class TestNextBlinkState(unittest.TestCase):
    def test_rest_is_the_common_case(self):
        # A fixed rng that never rolls below BLINK_PROBABILITY.
        rng = random.Random(1)
        results = [ss.next_blink_state(rng=rng)[0] for _ in range(200)]
        rest_fraction = 1 - (sum(results) / len(results))
        self.assertGreater(rest_fraction, 0.7,
                           "rest should be the large majority of decisions")

    def test_rest_hold_is_longer_than_blink_hold(self):
        rng = random.Random(2)
        rest_holds = []
        blink_holds = []
        for _ in range(500):
            is_blink, hold = ss.next_blink_state(rng=rng)
            (blink_holds if is_blink else rest_holds).append(hold)
        self.assertTrue(rest_holds and blink_holds, "need at least one of each in 500 rolls")
        self.assertGreater(min(rest_holds), max(blink_holds),
                           "every rest hold should outlast every blink hold")

    def test_holds_are_within_their_configured_ranges(self):
        rng = random.Random(3)
        for _ in range(300):
            is_blink, hold = ss.next_blink_state(rng=rng)
            lo, hi = ss.BLINK_HOLD_RANGE if is_blink else ss.REST_HOLD_RANGE
            self.assertTrue(lo <= hold <= hi)

    def test_not_deterministic(self):
        # "shouldn't be predictable" -- two independent rng STREAMS
        # (one Random instance reused across the whole sequence, not a
        # fresh one per call -- re-seeding every call would make every
        # draw identical regardless of how random the seed is) must not
        # produce the exact same sequence of (is_blink, hold) pairs.
        rng_a, rng_b = random.Random(10), random.Random(20)
        seq_a = [ss.next_blink_state(rng=rng_a) for _ in range(50)]
        seq_b = [ss.next_blink_state(rng=rng_b) for _ in range(50)]
        self.assertNotEqual(seq_a, seq_b)


class TestLastSoundAt(unittest.TestCase):
    def test_neither_log_exists_returns_none(self):
        self.assertIsNone(ss.last_sound_at("/no/such/stt.log", "/no/such/gate.log"))

    def test_returns_the_more_recent_mtime(self):
        with tempfile.TemporaryDirectory() as d:
            stt = os.path.join(d, "stt.log")
            gate = os.path.join(d, "gate.log")
            open(stt, "w").close()
            time.sleep(0.05)
            open(gate, "w").close()
            result = ss.last_sound_at(stt, gate)
            self.assertAlmostEqual(result, os.path.getmtime(gate), delta=0.01)

    def test_missing_one_log_still_uses_the_other(self):
        with tempfile.TemporaryDirectory() as d:
            stt = os.path.join(d, "stt.log")
            open(stt, "w").close()
            result = ss.last_sound_at(stt, "/no/such/gate.log")
            self.assertAlmostEqual(result, os.path.getmtime(stt), delta=0.01)


class TestIsAsleep(unittest.TestCase):
    def test_nothing_ever_heard_is_asleep(self):
        self.assertTrue(ss.is_asleep(time.time(), "/no/such/stt.log", "/no/such/gate.log"))

    def test_recent_sound_is_awake(self):
        with tempfile.TemporaryDirectory() as d:
            stt = os.path.join(d, "stt.log")
            open(stt, "w").close()
            self.assertFalse(ss.is_asleep(time.time(), stt, "/no/such/gate.log", silence_secs=60.0))

    def test_old_sound_past_silence_window_is_asleep(self):
        with tempfile.TemporaryDirectory() as d:
            stt = os.path.join(d, "stt.log")
            open(stt, "w").close()
            old_mtime = os.path.getmtime(stt) - 61.0
            os.utime(stt, (old_mtime, old_mtime))
            self.assertTrue(ss.is_asleep(time.time(), stt, "/no/such/gate.log", silence_secs=60.0))

    def test_exactly_at_the_boundary_is_asleep(self):
        # (now - last) >= silence_secs -- the boundary itself counts as
        # asleep, not one tick shy of it.
        with tempfile.TemporaryDirectory() as d:
            stt = os.path.join(d, "stt.log")
            open(stt, "w").close()
            now = os.path.getmtime(stt) + 60.0
            self.assertTrue(ss.is_asleep(now, stt, "/no/such/gate.log", silence_secs=60.0))

    def test_default_silence_secs_is_sixty(self):
        self.assertEqual(ss.SLEEP_SILENCE_SECS, 60.0)


if __name__ == "__main__":
    unittest.main()


class TestGradientColors(unittest.TestCase):
    def test_spans_the_full_palette_top_to_bottom(self):
        colors = ss.gradient_colors(5, palette=["a", "b", "c", "d", "e"])
        self.assertEqual(colors, ["a", "b", "c", "d", "e"])

    def test_fewer_rows_than_palette_still_spans_start_to_end(self):
        colors = ss.gradient_colors(2, palette=["a", "b", "c", "d", "e"])
        self.assertEqual(colors[0], "a")
        self.assertEqual(colors[-1], "e")

    def test_more_rows_than_palette_still_starts_and_ends_right(self):
        colors = ss.gradient_colors(13, palette=ss.LOGO_COLORS)
        self.assertEqual(len(colors), 13)
        self.assertEqual(colors[0], ss.LOGO_COLORS[0])
        self.assertEqual(colors[-1], ss.LOGO_COLORS[-1])

    def test_uses_more_than_one_color_for_real_art_height(self):
        # The actual live complaint: one flat shade for the whole frame.
        colors = ss.gradient_colors(13, palette=ss.LOGO_COLORS)
        self.assertGreater(len(set(colors)), 1)

    def test_zero_rows_returns_empty(self):
        self.assertEqual(ss.gradient_colors(0), [])

    def test_single_row_uses_first_color(self):
        self.assertEqual(ss.gradient_colors(1, palette=["a", "b", "c"]), ["a"])


class TestFrameRowsGradient(unittest.TestCase):
    def test_gradient_sentinel_produces_more_than_one_color_in_output(self):
        art = ["line%d" % i for i in range(5)]
        rows = ss._frame_rows(art, 40, 7, "", ss.GRADIENT, dim=True)
        colors_seen = set(re.findall(r"\x1b\[38;5;\d+m", "\n".join(rows)))
        self.assertGreater(len(colors_seen), 1,
                           "gradient mode should use more than one color across the art")

    def test_plain_color_string_still_uses_exactly_one_color(self):
        art = ["line%d" % i for i in range(5)]
        rows = ss._frame_rows(art, 40, 7, "", ss.CYAN, dim=True)
        colors_seen = set(re.findall(r"\x1b\[36m", "\n".join(rows)))
        other_colors = set(re.findall(r"\x1b\[38;5;\d+m", "\n".join(rows)))
        self.assertEqual(len(other_colors), 0)
