#!/usr/bin/env python3
# crt#345 candidate 3 (CRT_OVERLAP_TRANSCRIBE, off by default): transcribe()
# moves to a background thread so the capture loop's sole reader never
# actually stops reading arecord for the 1-10s a transcription takes.
#
# What is tested here is the concurrency PRIMITIVES -- spawn_transcription()
# and drain_pending() -- not main()'s own wiring of them, same posture as
# test_capture_backpressure.py testing drain/backlog math without running
# main() itself: main() needs a live arecord and a tmux session neither of
# which exist in a test process.
import importlib.util
import os
import threading
import time
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")
SOLO_PATH = os.path.join(BIN_DIR, "crt-stt-solo.py")


def load_stt():
    spec = importlib.util.spec_from_file_location("crt_stt_solo_overlap", SOLO_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestSpawnAndDrain(unittest.TestCase):
    def setUp(self):
        self.stt = load_stt()

    def test_spawn_runs_transcribe_and_reports_text_and_path(self):
        self.stt.transcribe = lambda frames, path_out=None: (
            path_out.append("remote") or "hello potato")
        pending = []
        holder = self.stt.spawn_transcription(b"\0" * 10, 0.5, (0, 1), pending)
        self.assertEqual(pending, [holder])
        holder["done"].wait(2.0)
        self.assertEqual(holder["text"], "hello potato")
        self.assertEqual(holder["path"], "remote")
        self.assertEqual(holder["peak"], 0.5)
        self.assertEqual(holder["span"], (0, 1))

    def test_spawn_defaults_path_to_failed_when_transcribe_never_marks_one(self):
        # transcribe() raising before mark_path() runs (see its own
        # try/except) returns None and leaves path_out empty -- spawn's
        # holder must not crash reading path_out[0] in that case.
        self.stt.transcribe = lambda frames, path_out=None: None
        pending = []
        holder = self.stt.spawn_transcription(b"\0" * 10, 0.5, (0, 1), pending)
        holder["done"].wait(2.0)
        self.assertIsNone(holder["text"])
        self.assertEqual(holder["path"], "failed")

    def test_drain_holds_a_finished_entry_behind_an_unfinished_one(self):
        # FIFO: the second utterance's transcription finishing first must
        # not let it jump ahead of the first -- a reply must answer the
        # utterance that was actually spoken first.
        pending = [
            {"done": threading.Event(), "text": "first", "path": "remote",
             "peak": 1.0, "span": (0, 1)},
            {"done": threading.Event(), "text": "second", "path": "remote",
             "peak": 1.0, "span": (2, 3)},
        ]
        pending[1]["done"].set()   # second finished; first has not
        seen = []
        self.stt.drain_pending(pending, lambda *a: seen.append(a))
        self.assertEqual(seen, [])
        self.assertEqual(len(pending), 2)

        pending[0]["done"].set()   # now the first finishes too
        self.stt.drain_pending(pending, lambda *a: seen.append(a))
        self.assertEqual([s[0] for s in seen], ["first", "second"])
        self.assertEqual(pending, [])

    def test_drain_reports_each_holders_own_path_not_a_later_global_write(self):
        # The bug this design avoids: two workers both call transcribe(),
        # which sets the shared TRANSCRIBE_PATH global as a side effect
        # (existing, synchronous callers rely on reading it right after
        # their own call). A second worker finishing -- or anything else --
        # can overwrite that global before drain_pending() gets around to
        # the first holder. drain_pending() must use the PER-HOLDER path
        # (captured via transcribe()'s path_out at the time IT ran), never
        # the global, or this utterance's latency-log line would blame the
        # wrong recogniser.
        holder = {"done": threading.Event(), "text": "hello", "path": "remote",
                  "peak": 1.0, "span": (0, 1)}
        holder["done"].set()
        pending = [holder]
        self.stt.TRANSCRIBE_PATH = "fallback"   # simulate a second worker's write
        seen = []
        self.stt.drain_pending(pending, lambda *a: seen.append(a))
        self.assertEqual(seen[0][1], "remote")   # the holder's own path, not "fallback"


class TestTranscribePathOut(unittest.TestCase):
    """transcribe()'s new path_out param, alongside the global it has always
    set -- existing synchronous callers (test_wake_arm_clock_domain.py) read
    the global right after calling transcribe() and must see no change."""

    def setUp(self):
        self.stt = load_stt()
        self.stt.NORM = False
        self.stt.HP = "0"
        self.stt.NR_PROF = None

    def test_remote_success_marks_path_out_and_the_global(self):
        self.stt.WHISPER_SERVER = "http://example.invalid/inference"
        self.stt.transcribe_remote = lambda wav: "hi"
        path_out = []
        text = self.stt.transcribe(b"\0" * 32000, path_out=path_out)
        self.assertEqual(text, "hi")
        self.assertEqual(path_out, ["remote"])
        self.assertEqual(self.stt.TRANSCRIBE_PATH, "remote")

    def test_fallback_marks_path_out_and_the_global(self):
        self.stt.WHISPER_SERVER = "http://example.invalid/inference"
        self.stt.WHISPER_LOCAL_FALLBACK = True
        self.stt.transcribe_remote = lambda wav: None
        self.stt.local_whisper_available = lambda: True
        self.stt.transcribe_local = lambda wav: "rescued"
        path_out = []
        text = self.stt.transcribe(b"\0" * 32000, path_out=path_out)
        self.assertEqual(text, "rescued")
        self.assertEqual(path_out, ["fallback"])
        self.assertEqual(self.stt.TRANSCRIBE_PATH, "fallback")

    def test_path_out_defaults_to_none_and_nothing_breaks(self):
        self.stt.WHISPER_SERVER = "http://example.invalid/inference"
        self.stt.transcribe_remote = lambda wav: "hi"
        text = self.stt.transcribe(b"\0" * 32000)
        self.assertEqual(text, "hi")
        self.assertEqual(self.stt.TRANSCRIBE_PATH, "remote")


class TestOverlapDefaultsOff(unittest.TestCase):
    def test_overlap_transcribe_is_off_unless_the_env_var_says_1(self):
        os.environ.pop("CRT_OVERLAP_TRANSCRIBE", None)
        stt = load_stt()
        self.assertFalse(stt.OVERLAP_TRANSCRIBE)

    def test_overlap_transcribe_turns_on_with_the_env_var(self):
        old = os.environ.get("CRT_OVERLAP_TRANSCRIBE")
        os.environ["CRT_OVERLAP_TRANSCRIBE"] = "1"
        try:
            stt = load_stt()
            self.assertTrue(stt.OVERLAP_TRANSCRIBE)
        finally:
            if old is None:
                os.environ.pop("CRT_OVERLAP_TRANSCRIBE", None)
            else:
                os.environ["CRT_OVERLAP_TRANSCRIBE"] = old


if __name__ == "__main__":
    unittest.main()
