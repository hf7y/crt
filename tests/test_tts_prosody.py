#!/usr/bin/env python3
# Offline tests for bin/crt-tts.py's per-call prosody layer
# (resolve_prosody/build_sox_effects are pure; apply_prosody actually
# shells out to sox, which IS available in this sandbox even though no
# TTS backend is -- so this exercises the real sox invocation, not a mock).
import importlib.util
import os
import subprocess
import sys
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")
spec = importlib.util.spec_from_file_location("crt_tts", os.path.join(BIN_DIR, "crt-tts.py"))
tts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tts)

HAVE_SOX = tts.have("sox")


class TestResolveProsody(unittest.TestCase):
    def test_no_args_is_a_true_noop(self):
        self.assertEqual(tts.resolve_prosody(), (None, None, None))

    def test_mood_preset_applies(self):
        p, r, v = tts.resolve_prosody(mood="wistful")
        self.assertEqual((p, r, v), tts.MOOD_PRESETS["wistful"])

    def test_unknown_mood_is_ignored_not_fatal(self):
        p, r, v = tts.resolve_prosody(mood="not-a-real-mood")
        self.assertEqual((p, r, v), (None, None, None))

    def test_explicit_kwargs_override_mood_preset(self):
        p, r, v = tts.resolve_prosody(mood="urgent", rate_mult=2.0)
        self.assertEqual(r, 2.0)  # explicit wins over urgent's 1.15
        self.assertEqual(p, tts.MOOD_PRESETS["urgent"][0])  # untouched fields keep the preset

    def test_curious_preset_is_the_identity(self):
        # "curious" = the default register -- must be a true no-op so
        # calling --mood curious never audibly differs from no flag at all.
        p, r, v = tts.resolve_prosody(mood="curious")
        effects = tts.build_sox_effects(p, r, v)
        self.assertEqual(effects, [])


class TestBuildSoxEffects(unittest.TestCase):
    def test_nothing_requested_yields_no_effects(self):
        self.assertEqual(tts.build_sox_effects(None, None, None), [])

    def test_pitch_only(self):
        effects = tts.build_sox_effects(pitch_semitones=2, rate_mult=None, volume_mult=None)
        self.assertEqual(effects, ["pitch", "200"])

    def test_rate_mult_of_exactly_one_is_a_noop(self):
        # 1.0x rate is "no change" -- must not emit a pointless tempo effect.
        effects = tts.build_sox_effects(None, 1.0, None)
        self.assertEqual(effects, [])

    def test_all_three_combine(self):
        effects = tts.build_sox_effects(-1, 0.85, 0.8)
        self.assertEqual(effects, ["pitch", "-100", "tempo", "0.85", "vol", "0.8"])


@unittest.skipUnless(HAVE_SOX, "sox not installed")
class TestApplyProsodyRealSox(unittest.TestCase):
    def setUp(self):
        # A tiny real wav to run sox against -- sox itself synthesizes it,
        # so this needs no TTS backend at all.
        import tempfile
        fd, self.wav = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        subprocess.run(["sox", "-n", "-r", "22050", self.wav,
                         "synth", "0.2", "sine", "440"], check=True)

    def tearDown(self):
        for p in (self.wav, self.wav[:-4] + "_prosody.wav"):
            try: os.unlink(p)
            except OSError: pass

    def test_no_effects_returns_same_path_unchanged(self):
        out = tts.apply_prosody(self.wav)
        self.assertEqual(out, self.wav)

    def test_effects_produce_a_new_file(self):
        out = tts.apply_prosody(self.wav, rate_mult=0.5)
        self.assertNotEqual(out, self.wav)
        self.assertTrue(os.path.exists(out))
        self.assertGreater(os.path.getsize(out), 0)

    def test_sox_failure_falls_back_to_original_path(self):
        # An absurd tempo value sox will reject -- must fail soft, not crash.
        out = tts.apply_prosody(self.wav, rate_mult=0.0001)
        self.assertEqual(out, self.wav)


class TestMain(unittest.TestCase):
    def test_flag_parsing_extracts_device_mood_and_text(self):
        old_argv = sys.argv
        captured = {}

        def fake_speak(text, device=None, mood=None, pitch_semitones=None,
                        rate_mult=None, volume_mult=None):
            captured.update(text=text, device=device, mood=mood,
                             pitch_semitones=pitch_semitones,
                             rate_mult=rate_mult, volume_mult=volume_mult)
            return True

        old_speak = tts.speak
        tts.speak = fake_speak
        sys.argv = ["crt-tts.py", "--device", "handset", "--mood", "urgent",
                    "hello", "world"]
        try:
            with self.assertRaises(SystemExit) as cm:
                tts.main()
            self.assertEqual(cm.exception.code, 0)
        finally:
            sys.argv = old_argv
            tts.speak = old_speak

        self.assertEqual(captured["text"], "hello world")
        self.assertEqual(captured["device"], "handset")
        self.assertEqual(captured["mood"], "urgent")


if __name__ == "__main__":
    unittest.main()
