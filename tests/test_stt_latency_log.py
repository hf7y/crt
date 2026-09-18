#!/usr/bin/env python3
# "It feels too laggy" (Zach, 2026-09-18) had no number behind it on either
# side. emit() has measured reader_lag -- end of speech to text in hand --
# since the arm-window work, but spent it on the clock domain and dropped it,
# so the delay the speaker actually experiences was never written down.
#
# These tests pin the writing-down, not the size: what the right latency IS
# is a by-ear call, and this file only guarantees a night of real speech
# leaves evidence to make that call from.
import importlib.util
import os
import shutil
import tempfile
import time
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")
SOLO_PATH = os.path.join(BIN_DIR, "crt-stt-solo.py")

WHISPER_SECS = 1.25      # a plausible round-trip; the fixture's only clock lie


class LatencyLogTest(unittest.TestCase):
    def setUp(self):
        self.env_backup = {k: os.environ.get(k) for k in
                           ("CRT_STT_GATE", "CRT_STT_SINK", "CRT_VAD_TRAIL",
                            "CRT_EARCON_ON_ADDRESSED", "CRT_WAKE_ARM_ENABLED")}
        os.environ.update({
            "CRT_STT_GATE": "0",          # route everything; the gate is not under test
            "CRT_STT_SINK": "secretary",
            "CRT_VAD_TRAIL": "0.80",
            "CRT_EARCON_ON_ADDRESSED": "0",
            "CRT_WAKE_ARM_ENABLED": "0",
        })
        spec = importlib.util.spec_from_file_location("crt_stt_solo_lat", SOLO_PATH)
        self.stt = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.stt)

        self.tmpdir = tempfile.mkdtemp()
        self.stt.STT_LOG = os.path.join(self.tmpdir, "stt.log")
        self.stt.GATE_LOG = os.path.join(self.tmpdir, "gate.log")
        self.stt.LATENCY_LOG = os.path.join(self.tmpdir, "latency.log")
        self.stt.log_user_thought = lambda text, **kw: None
        self.stt.play_earcon = lambda *a, **kw: None
        self.stt.send_to_secretary = lambda text: None
        self.stt.send_to_claude = lambda text, key: None

    def tearDown(self):
        for k, v in self.env_backup.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def lines(self):
        with open(self.stt.LATENCY_LOG) as f:
            return [l for l in f.read().splitlines() if l.strip()]

    def fields(self, line):
        return dict(tok.split("=", 1) for tok in line.split() if "=" in tok)

    def test_an_utterance_leaves_a_timed_line(self):
        # Spoken for 3s, transcribed WHISPER_SECS after the audio ended.
        end = time.time() - WHISPER_SECS
        self.stt.emit("potato what time is it", 1.0,
                      utt_start=end - 3.0, utt_end=end)
        got = self.fields(self.lines()[0])
        self.assertAlmostEqual(float(got["whisper"]), WHISPER_SECS, delta=0.2)

    def test_blind_is_the_trail_the_speaker_also_waits_through(self):
        # The point of carrying trail: the speaker's silence starts when they
        # stop talking, not when the VAD concedes they did. A whisper time
        # alone would under-report the wait by a whole TRAIL.
        end = time.time() - WHISPER_SECS
        self.stt.emit("potato hello", 1.0, utt_start=end - 1.0, utt_end=end)
        got = self.fields(self.lines()[0])
        self.assertAlmostEqual(
            float(got["blind"]),
            float(got["trail"]) + float(got["whisper"]), delta=0.01)
        self.assertGreater(float(got["trail"]), 0.0)

    def test_a_dropped_hallucination_is_not_a_round_trip(self):
        # emit() returns before any of this for whisper's canned silence
        # tags. Logging those would put a floor of noise lines under every
        # quiet hour and make the median meaningless.
        self.stt.emit("Thank you.", 1.0,
                      utt_start=time.time() - 2.0, utt_end=time.time() - 1.0)
        self.assertFalse(os.path.exists(self.stt.LATENCY_LOG))

    def test_a_broken_log_never_blocks_the_dispatch(self):
        # Same contract as predictive_flash()/set_sideband_state(): the
        # measurement is best-effort and the utterance is not.
        self.stt.LATENCY_LOG = os.path.join(self.tmpdir, "nope", "x")
        os.makedirs(os.path.join(self.tmpdir, "nope"))
        os.chmod(os.path.join(self.tmpdir, "nope"), 0o500)
        sent = []
        self.stt.send_to_secretary = sent.append
        try:
            self.stt.emit("potato are you there", 1.0,
                          utt_start=time.time() - 2.0, utt_end=time.time() - 1.0)
        finally:
            os.chmod(os.path.join(self.tmpdir, "nope"), 0o700)
        self.assertEqual(sent, ["potato are you there"])


if __name__ == "__main__":
    unittest.main()
