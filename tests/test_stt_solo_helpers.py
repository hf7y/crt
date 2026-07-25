#!/usr/bin/env python3
# Offline tests for crt-stt-solo.py's small pure/file-scoped helpers that
# addressed_to_console()'s own test file (test_stt_gate.py) doesn't cover:
# load_fixups()'s malformed/missing-file tolerance, _contains_phrase()'s
# whole-word matching, classify_wake_match() (the arm-window's match-kind
# detail), and the control-file HUD helpers (hud_bar/apply_ctl_line) that
# translate MIDI-knob/control-file lines into clamped live params. No
# mic/VM/tmux needed -- pure string/logic, same posture as test_stt_gate.py.
import importlib.util
import json
import os
import tempfile
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")
spec = importlib.util.spec_from_file_location("crt_stt_solo_helpers", os.path.join(BIN_DIR, "crt-stt-solo.py"))
stt_solo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stt_solo)


class LoadFixupsTest(unittest.TestCase):
    def test_missing_file_degrades_to_empty_dict(self):
        self.assertEqual(stt_solo.load_fixups("/no/such/path/stt-fixups.json"), {})

    def test_malformed_json_degrades_to_empty_dict(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{not valid json")
            path = f.name
        try:
            self.assertEqual(stt_solo.load_fixups(path), {})
        finally:
            os.unlink(path)

    def test_underscore_keys_filtered_out(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"_comment": "docs", "slide": {"intent": "claude"}}, f)
            path = f.name
        try:
            fixups = stt_solo.load_fixups(path)
            self.assertNotIn("_comment", fixups)
            self.assertIn("slide", fixups)
        finally:
            os.unlink(path)


class ContainsPhraseTest(unittest.TestCase):
    def test_whole_word_match(self):
        self.assertTrue(stt_solo._contains_phrase(["hey", "slide", "over"], "slide"))

    def test_no_false_positive_on_substring(self):
        # "slide" must not match inside "landslide" -- these are already
        # separate tokens by the time _contains_phrase runs, but this
        # documents the whole-word contract explicitly.
        self.assertFalse(stt_solo._contains_phrase(["landslide", "warning"], "slide"))

    def test_multiword_phrase_contiguous(self):
        self.assertTrue(stt_solo._contains_phrase(["gray", "dude", "fetch"], "gray dude"))
        self.assertFalse(stt_solo._contains_phrase(["gray", "over", "dude"], "gray dude"))


class ClassifyWakeMatchTest(unittest.TestCase):
    def test_exact_wake_word_match(self):
        kind, _, matched = stt_solo.classify_wake_match("claude what time is it")
        self.assertEqual(kind, "exact")
        self.assertEqual(matched, stt_solo.WAKE_WORD)

    def test_no_match_returns_all_none(self):
        self.assertEqual(stt_solo.classify_wake_match("what a nice day"), (None, None, None))

    def test_fixup_fragment_match(self):
        fixups = {"greydog": {"intent": "claude"}}
        kind, _, matched = stt_solo.classify_wake_match(
            "greydog fetch", wake_word="claude", fixups=fixups)
        self.assertEqual(kind, "exact")
        self.assertEqual(matched, "greydog")

    def test_stays_in_sync_with_addressed_to_console(self):
        # Both functions share the same exact/fixup logic by design (kept in
        # sync by hand, per classify_wake_match's own header comment) --
        # assert they agree on a spread of cases so a future edit to one
        # without the other gets caught here instead of live.
        fixups = {"slide": {"intent": "claude"}}
        cases = ["claude run the tests", "slide over here", "nothing relevant", ""]
        for text in cases:
            gated = stt_solo.addressed_to_console(text, wake_word="claude", fixups=fixups)
            kind, _, _ = stt_solo.classify_wake_match(text, wake_word="claude", fixups=fixups)
            self.assertEqual(gated, kind == "exact", text)


class HudBarTest(unittest.TestCase):
    def test_midpoint_half_filled(self):
        s = stt_solo.hud_bar("vad", 5.0, 0.0, 10.0, "%")
        self.assertIn("#" * 7, s)  # round(0.5*14) == 7

    def test_at_low_bound_empty_bar(self):
        s = stt_solo.hud_bar("vad", 0.0, 0.0, 10.0, "%")
        self.assertIn("." * 14, s)

    def test_at_high_bound_full_bar(self):
        s = stt_solo.hud_bar("vad", 10.0, 0.0, 10.0, "%")
        self.assertIn("#" * 14, s)

    def test_equal_lo_hi_does_not_divide_by_zero(self):
        s = stt_solo.hud_bar("vad", 3.0, 5.0, 5.0, "%")
        self.assertIn("." * 14, s)


class ApplyCtlLineTest(unittest.TestCase):
    def setUp(self):
        # Snapshot + restore module globals apply_ctl_line mutates, so tests
        # can't leak state into each other or into a later test module that
        # imports the same file fresh (importlib caches by spec name, but
        # keep this test file self-contained regardless).
        self._saved = {k: getattr(stt_solo, k) for k in ("THRESH", "NR_AMT", "TRAIL", "MINUTT", "MUTED")}

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(stt_solo, k, v)

    def test_too_few_parts_returns_none(self):
        self.assertIsNone(stt_solo.apply_ctl_line("vad"))

    def test_unknown_param_returns_none(self):
        self.assertIsNone(stt_solo.apply_ctl_line("bogus 5"))

    def test_non_numeric_value_returns_none(self):
        self.assertIsNone(stt_solo.apply_ctl_line("vad notanumber"))

    def test_valid_vad_line_clamps_and_applies(self):
        out = stt_solo.apply_ctl_line("vad 4.0")
        self.assertIsNotNone(out)
        self.assertAlmostEqual(stt_solo.THRESH, 0.04)  # 4% / scale 100

    def test_value_above_hi_clamped(self):
        stt_solo.apply_ctl_line("vad 999")
        self.assertAlmostEqual(stt_solo.THRESH, 8.0 / 100.0)  # CTL_MAP hi=8.0

    def test_value_below_lo_clamped(self):
        stt_solo.apply_ctl_line("vad -5")
        self.assertAlmostEqual(stt_solo.THRESH, 0.3 / 100.0)  # CTL_MAP lo=0.3

    def test_mute_on(self):
        out = stt_solo.apply_ctl_line("mute 1")
        self.assertTrue(stt_solo.MUTED)
        self.assertIn("ON", out)

    def test_mute_off(self):
        stt_solo.apply_ctl_line("mute 1")
        out = stt_solo.apply_ctl_line("mute 0")
        self.assertFalse(stt_solo.MUTED)
        self.assertIn("off", out)


class LogUserThoughtTest(unittest.TestCase):
    def test_writes_you_prefixed_line(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "nested", "thoughts.log")
            stt_solo.log_user_thought("hello there", log_path=path, timestamp="12:00:00")
            with open(path) as f:
                self.assertEqual(f.read(), "12:00:00  [you] hello there\n")

    def test_unwritable_path_does_not_raise(self):
        # Best-effort logging must never block the real STT->secretary
        # routing that follows it -- an OSError (e.g. path under a file,
        # not a dir) must be swallowed, not propagated.
        with tempfile.NamedTemporaryFile() as f:
            bad_path = os.path.join(f.name, "thoughts.log")  # parent is a file
            stt_solo.log_user_thought("hello", log_path=bad_path)  # must not raise


if __name__ == "__main__":
    unittest.main()
