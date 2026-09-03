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
import stat
import tempfile
import unittest
from unittest import mock

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
        self._saved = {k: getattr(stt_solo, k) for k in ("THRESH", "NR_AMT", "TRAIL", "MINUTT", "MUTED", "MUTE_COUNT", "MUTE_SINCE", "MUTE_MAX_SECS")}

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

    def test_mute_is_reference_counted_not_last_write_wins(self):
        # Two concurrent duckers (e.g. a TTS reply and an earcon both
        # playing over the handset) each push "mute 1"; the first to finish
        # writes "mute 0" and must NOT unmute capture while the other is
        # still holding its duck open (2026-07-24 fe46ac1's known
        # limitation -- this is the fix).
        stt_solo.apply_ctl_line("mute 1")  # ducker A starts
        stt_solo.apply_ctl_line("mute 1")  # ducker B starts
        stt_solo.apply_ctl_line("mute 0")  # ducker A finishes first
        self.assertTrue(stt_solo.MUTED)    # still muted -- B is still active
        stt_solo.apply_ctl_line("mute 0")  # ducker B finishes
        self.assertFalse(stt_solo.MUTED)   # now both released

    def test_mute_count_floors_at_zero(self):
        # An extra/unbalanced "mute 0" (e.g. from a duck whose matching
        # "mute 1" was lost) must not drive the count negative, which would
        # require multiple extra "mute 1"s to ever unmute again.
        stt_solo.apply_ctl_line("mute 0")
        stt_solo.apply_ctl_line("mute 0")
        self.assertEqual(stt_solo.MUTE_COUNT, 0)
        stt_solo.apply_ctl_line("mute 1")
        self.assertTrue(stt_solo.MUTED)


class MuteWatchdogTest(unittest.TestCase):
    """A leaked duck (producer killed before writing its 'mute 0') must not
    deafen capture forever -- ref-counting removed the old flag's accidental
    self-healing, so MUTE_MAX_SECS puts a hard ceiling on any held mute."""

    def setUp(self):
        self._saved = {k: getattr(stt_solo, k) for k in ("MUTED", "MUTE_COUNT", "MUTE_SINCE", "MUTE_MAX_SECS")}
        stt_solo.MUTED, stt_solo.MUTE_COUNT, stt_solo.MUTE_SINCE = False, 0, 0.0
        stt_solo.MUTE_MAX_SECS = 45.0

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(stt_solo, k, v)

    def test_unmuted_is_a_no_op(self):
        self.assertIsNone(stt_solo.check_mute_timeout(1000.0))

    def test_mute_within_window_is_held(self):
        stt_solo.apply_ctl_line("mute 1", now=1000.0)
        self.assertIsNone(stt_solo.check_mute_timeout(1040.0))
        self.assertTrue(stt_solo.MUTED)

    def test_stuck_mute_is_force_cleared_and_warns(self):
        stt_solo.apply_ctl_line("mute 1", now=1000.0)
        warn = stt_solo.check_mute_timeout(1046.0)
        self.assertIsNotNone(warn)
        self.assertIn("WARNING", warn)      # fails loud, not silently
        self.assertFalse(stt_solo.MUTED)
        self.assertEqual(stt_solo.MUTE_COUNT, 0)

    def test_force_clear_drops_every_leaked_ref_not_just_one(self):
        # Two leaked ducks: clearing one at a time would leave capture dead.
        stt_solo.apply_ctl_line("mute 1", now=1000.0)
        stt_solo.apply_ctl_line("mute 1", now=1001.0)
        stt_solo.check_mute_timeout(1050.0)
        self.assertEqual(stt_solo.MUTE_COUNT, 0)
        self.assertFalse(stt_solo.MUTED)

    def test_hold_clock_starts_at_first_duck_not_the_nested_one(self):
        # A long-held outer duck must not have its deadline pushed back by a
        # short inner duck starting and finishing inside it.
        stt_solo.apply_ctl_line("mute 1", now=1000.0)
        stt_solo.apply_ctl_line("mute 1", now=1040.0)
        stt_solo.apply_ctl_line("mute 0", now=1041.0)
        self.assertIsNotNone(stt_solo.check_mute_timeout(1046.0))

    def test_clean_release_resets_the_clock_for_the_next_duck(self):
        stt_solo.apply_ctl_line("mute 1", now=1000.0)
        stt_solo.apply_ctl_line("mute 0", now=1001.0)
        stt_solo.apply_ctl_line("mute 1", now=1002.0)   # new, unrelated duck
        self.assertIsNone(stt_solo.check_mute_timeout(1040.0))

    def test_zero_disables_the_watchdog(self):
        stt_solo.MUTE_MAX_SECS = 0.0
        stt_solo.apply_ctl_line("mute 1", now=1000.0)
        self.assertIsNone(stt_solo.check_mute_timeout(99999.0))
        self.assertTrue(stt_solo.MUTED)


class MomentaryCtlTest(unittest.TestCase):
    """main() replays the CTL file from byte 0 on startup so knob-tuned
    LEVELS survive a restart. One-shot COMMANDS must be skipped in that
    replay: a leaked 'mute 1' left in the append-only history would
    otherwise mute capture on every single start (and never age out, since
    the file isn't truncated), and a stale 'ring 4' would re-ring the
    phone at boot."""

    def test_mute_and_ring_are_momentary(self):
        self.assertTrue(stt_solo.is_momentary_ctl("mute 1"))
        self.assertTrue(stt_solo.is_momentary_ctl("mute 0"))
        self.assertTrue(stt_solo.is_momentary_ctl("ring 4"))

    def test_levels_are_not_momentary(self):
        for line in ("vad 4.0", "nr 0.2", "trail 0.8", "min 0.4"):
            self.assertFalse(stt_solo.is_momentary_ctl(line), line)

    def test_case_and_whitespace_tolerant(self):
        self.assertTrue(stt_solo.is_momentary_ctl("  MUTE 1  "))
        self.assertTrue(stt_solo.is_momentary_ctl("Ring"))

    def test_blank_line_is_not_momentary(self):
        self.assertFalse(stt_solo.is_momentary_ctl(""))
        self.assertFalse(stt_solo.is_momentary_ctl("   "))


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


class UttChunkTest(unittest.TestCase):
    """utt_chunk() -- what one capture chunk does to an ALREADY-OPEN utterance.

    The mute cases are the reason this function was extracted from main()'s
    loop (2026-07-25): before it, the VAD checked MUTED only when STARTING an
    utterance, so a duck arriving mid-utterance recorded our own handset
    playback into the middle of the speaker's sentence. The silence/cap cases
    are regression guards -- they describe behaviour that was already correct
    and must survive the extraction unchanged.
    """

    def setUp(self):
        self._saved = {k: getattr(stt_solo, k) for k in
                       ("THRESH", "TRAIL", "MAXUTT", "MUTE_UTT_MAX_SECS", "CHUNK_DUR")}
        stt_solo.THRESH = 0.10
        stt_solo.TRAIL = 0.8
        stt_solo.MAXUTT = 20.0
        stt_solo.MUTE_UTT_MAX_SECS = 2.0
        stt_solo.CHUNK_DUR = 0.1

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(stt_solo, k, v)

    # -- unmuted: unchanged pre-existing behaviour ------------------------

    def test_loud_chunk_is_kept_and_resets_the_silence_timer(self):
        keep, ended, sil, hold = stt_solo.utt_chunk(False, 0.5, 0.7, 0.0, 1.0)
        self.assertTrue(keep)
        self.assertFalse(ended)
        self.assertEqual(sil, 0.0)

    def test_quiet_chunks_accumulate_silence_and_end_at_trail(self):
        sil, hold, ended, chunks = 0.0, 0.0, False, 0
        while not ended and chunks < 20:
            keep, ended, sil, hold = stt_solo.utt_chunk(False, 0.01, sil, hold, 1.0)
            self.assertTrue(keep)             # trailing silence is still buffered
            chunks += 1
        self.assertTrue(ended)
        # 8 chunks is TRAIL exactly; float accumulation of 0.1s makes it 9.
        self.assertIn(chunks, (8, 9))

    def test_hard_cap_ends_the_utterance_even_while_speech_continues(self):
        stt_solo.MAXUTT = 2.0
        keep, ended, sil, hold = stt_solo.utt_chunk(False, 0.9, 0.0, 0.0, 1.9)
        self.assertTrue(keep)
        self.assertTrue(ended)                # 1.9 + 0.1 >= MAXUTT

    # -- muted: the fix ---------------------------------------------------

    def test_ducked_chunk_is_dropped_not_buffered(self):
        # THE regression: a loud chunk during a duck is our own playback.
        # Before the fix this returned "buffer it" and whisper transcribed
        # the console's earcon/reply as the speaker's words.
        keep, ended, sil, hold = stt_solo.utt_chunk(True, 0.9, 0.0, 0.0, 1.0)
        self.assertFalse(keep)

    def test_duck_does_not_advance_the_silence_timer(self):
        # A duck must not end the utterance by looking like trailing silence
        # either -- the whole point is that the frames are not evidence about
        # the speaker in either direction.
        sil = 0.7                             # one chunk short of TRAIL
        for _ in range(5):
            keep, ended, sil, hold = stt_solo.utt_chunk(True, 0.0, sil, 0.0, 1.0)
            self.assertFalse(ended)
        self.assertEqual(sil, 0.7)

    def test_a_duck_that_outlasts_the_bound_ends_the_utterance(self):
        hold, ended, chunks = 0.0, False, 0
        while not ended and chunks < 30:
            keep, ended, sil, hold = stt_solo.utt_chunk(True, 0.0, 0.0, hold, 1.0)
            chunks += 1
            if chunks == 10:                  # 1.0s in, still inside the bound
                self.assertFalse(ended)
        self.assertTrue(ended)
        self.assertIn(chunks, (20, 21))       # MUTE_UTT_MAX_SECS / CHUNK_DUR

    def test_bound_of_zero_freezes_indefinitely(self):
        stt_solo.MUTE_UTT_MAX_SECS = 0.0
        hold = 0.0
        for _ in range(200):                  # 20 seconds of duck
            keep, ended, sil, hold = stt_solo.utt_chunk(True, 0.0, 0.0, hold, 1.0)
            self.assertFalse(ended)

    def test_unducking_clears_the_hold(self):
        keep, ended, sil, hold = stt_solo.utt_chunk(True, 0.0, 0.0, 1.5, 1.0)
        self.assertAlmostEqual(hold, 1.6)
        keep, ended, sil, hold = stt_solo.utt_chunk(False, 0.9, 0.0, hold, 1.0)
        self.assertEqual(hold, 0.0)           # a later short duck starts over

    def test_short_earcon_is_excised_and_speech_either_side_survives(self):
        # The reachable case end-to-end: speaker talking, CRT_EARCON_ON_THRESHOLD
        # fires a ~0.3s "heard" beep, speaker keeps going. Expect: the three
        # ducked chunks dropped, the utterance still open, everything else kept.
        script = [(False, 0.9)] * 5 + [(True, 0.9)] * 3 + [(False, 0.9)] * 5
        sil, hold, kept, ended = 0.0, 0.0, 0, False
        for muted, peak in script:
            keep, ended, sil, hold = stt_solo.utt_chunk(muted, peak, sil, hold, 1.0)
            kept += 1 if keep else 0
        self.assertEqual(kept, 10)
        self.assertFalse(ended)


class LocalWhisperAvailableTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmp.cleanup()

    def _make(self, executable):
        bin_path = os.path.join(self._tmp.name, "whisper-cli")
        with open(bin_path, "w") as f:
            f.write("#!/bin/sh\n")
        if executable:
            os.chmod(bin_path, os.stat(bin_path).st_mode | stat.S_IEXEC)
        model_path = os.path.join(self._tmp.name, "model.bin")
        with open(model_path, "w") as f:
            f.write("x")
        return bin_path, model_path

    def test_true_when_both_exist_and_binary_is_executable(self):
        wbin, model = self._make(executable=True)
        with mock.patch.object(stt_solo, "WBIN", wbin), \
             mock.patch.object(stt_solo, "MODEL", model):
            self.assertTrue(stt_solo.local_whisper_available())

    def test_false_when_binary_is_not_executable(self):
        wbin, model = self._make(executable=False)
        with mock.patch.object(stt_solo, "WBIN", wbin), \
             mock.patch.object(stt_solo, "MODEL", model):
            self.assertFalse(stt_solo.local_whisper_available())

    def test_false_when_model_is_missing(self):
        wbin, model = self._make(executable=True)
        os.unlink(model)
        with mock.patch.object(stt_solo, "WBIN", wbin), \
             mock.patch.object(stt_solo, "MODEL", model):
            self.assertFalse(stt_solo.local_whisper_available())


class TranscribeFallbackTest(unittest.TestCase):
    # crt#132: a dead WHISPER_SERVER used to lose every utterance silently.
    # These exercise transcribe()'s branch logic directly -- NORM/NR_PROF
    # forced off so no sox subprocess runs, only the fallback decision.
    def setUp(self):
        self._patches = [
            mock.patch.object(stt_solo, "NORM", False),
            mock.patch.object(stt_solo, "NR_PROF", ""),
            mock.patch.object(stt_solo, "HP", "0"),
        ]
        for p in self._patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self._patches])
        self._frames = b"\x00\x00" * 1600

    def test_remote_success_never_touches_local(self):
        with mock.patch.object(stt_solo, "WHISPER_SERVER", "http://fake/transcribe"), \
             mock.patch.object(stt_solo, "transcribe_remote", return_value="hello"), \
             mock.patch.object(stt_solo, "transcribe_local") as local:
            self.assertEqual(stt_solo.transcribe(self._frames), "hello")
            local.assert_not_called()

    def test_remote_failure_falls_back_to_local_when_available(self):
        with mock.patch.object(stt_solo, "WHISPER_SERVER", "http://fake/transcribe"), \
             mock.patch.object(stt_solo, "WHISPER_LOCAL_FALLBACK", True), \
             mock.patch.object(stt_solo, "transcribe_remote", return_value=None), \
             mock.patch.object(stt_solo, "local_whisper_available", return_value=True), \
             mock.patch.object(stt_solo, "transcribe_local", return_value="fallback text"):
            self.assertEqual(stt_solo.transcribe(self._frames), "fallback text")

    def test_remote_failure_stays_none_when_no_local_build(self):
        with mock.patch.object(stt_solo, "WHISPER_SERVER", "http://fake/transcribe"), \
             mock.patch.object(stt_solo, "WHISPER_LOCAL_FALLBACK", True), \
             mock.patch.object(stt_solo, "transcribe_remote", return_value=None), \
             mock.patch.object(stt_solo, "local_whisper_available", return_value=False), \
             mock.patch.object(stt_solo, "transcribe_local") as local:
            self.assertIsNone(stt_solo.transcribe(self._frames))
            local.assert_not_called()

    def test_fallback_disabled_stays_none_even_with_a_local_build(self):
        with mock.patch.object(stt_solo, "WHISPER_SERVER", "http://fake/transcribe"), \
             mock.patch.object(stt_solo, "WHISPER_LOCAL_FALLBACK", False), \
             mock.patch.object(stt_solo, "transcribe_remote", return_value=None), \
             mock.patch.object(stt_solo, "local_whisper_available", return_value=True), \
             mock.patch.object(stt_solo, "transcribe_local") as local:
            self.assertIsNone(stt_solo.transcribe(self._frames))
            local.assert_not_called()

    def test_remote_heard_silence_is_not_treated_as_failure(self):
        # "" means the recogniser ran and heard nothing -- not a server outage.
        with mock.patch.object(stt_solo, "WHISPER_SERVER", "http://fake/transcribe"), \
             mock.patch.object(stt_solo, "transcribe_remote", return_value=""), \
             mock.patch.object(stt_solo, "transcribe_local") as local:
            self.assertEqual(stt_solo.transcribe(self._frames), "")
            local.assert_not_called()

    def test_no_server_configured_goes_straight_to_local(self):
        with mock.patch.object(stt_solo, "WHISPER_SERVER", ""), \
             mock.patch.object(stt_solo, "transcribe_local", return_value="local text") as local:
            self.assertEqual(stt_solo.transcribe(self._frames), "local text")
            local.assert_called_once()


if __name__ == "__main__":
    unittest.main()
