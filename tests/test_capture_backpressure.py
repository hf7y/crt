#!/usr/bin/env python3
# Offline tests for crt-stt-solo.py's capture backpressure (2026-07-25,
# seventh cycle): transcribe() runs inside the capture loop, so nobody reads
# arecord's stdout meanwhile. Each class docstring below states the specific
# property it witnesses.
#
# crt#345 candidate 3 (CRT_OVERLAP_TRANSCRIBE, off by default) answers that
# same problem a different way -- transcribe() moves to a background thread
# instead, so nobody has to stop reading arecord in the first place. Its
# tests live in this file rather than their own (folded in against the
# prose ratchet, crt#48/#251) because they test the same subject: the
# concurrency PRIMITIVES (spawn_transcription()/drain_pending()), not
# main()'s own wiring of them, which needs a live arecord and tmux session
# neither of which exist in a test process -- same posture as the classes
# above testing drain/backlog math without running main() itself.
import importlib.util
import os
import threading
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")
SOLO_PATH = os.path.join(BIN_DIR, "crt-stt-solo.py")
spec = importlib.util.spec_from_file_location("crt_stt_solo_backpressure", SOLO_PATH)
stt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stt)

BYTES_PER_SEC = 2 * stt.RATE   # S16_LE mono at the capture rate


def load_overlap_stt():
    """A fresh module instance per test, distinct from the shared `stt`
    above -- TestOverlapDefaultsOff reloads with a different env var each
    time, and TestTranscribePathOut mutates instance attributes, neither of
    which may leak into the backpressure tests sharing `stt`."""
    spec = importlib.util.spec_from_file_location("crt_stt_solo_overlap", SOLO_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def measure_capacity(read_fd, write_fd):
    """How many bytes actually fit before a writer would block -- the real
    answer to 'how much audio can queue while whisper runs'."""
    os.set_blocking(write_fd, False)
    written = 0
    block = b"\x00" * 4096
    try:
        while True:
            written += os.write(write_fd, block)
    except BlockingIOError:
        pass
    finally:
        os.set_blocking(write_fd, True)
    return written


class PipeCapacityTest(unittest.TestCase):
    """The measurement that motivates the whole change."""

    def setUp(self):
        self.r, self.w = os.pipe()
        self.addCleanup(self._close)

    def _close(self):
        for fd in (self.r, self.w):
            try:
                os.close(fd)
            except OSError:
                pass

    def test_default_pipe_holds_less_audio_than_a_transcription_takes(self):
        # This is the bug, stated as a measurement. A remote transcription
        # against mandark was measured at 1-3s (FOCUS.md 2026-07-23 07:45);
        # the default pipe holds ~2s. Anything past that is lost.
        secs = measure_capacity(self.r, self.w) / BYTES_PER_SEC
        self.assertLess(secs, 3.0,
                        "default pipe unexpectedly deep; the premise of this "
                        "change should be re-measured")

    def test_widening_actually_buys_room_for_a_slow_transcription(self):
        capacity = stt.widen_capture_pipe(self.r)
        self.assertIsNotNone(capacity)
        self.assertGreaterEqual(stt.audio_seconds(capacity), 4.0)
        # and the kernel really honours it, not just the return value
        measured = measure_capacity(self.r, self.w) / BYTES_PER_SEC
        self.assertGreaterEqual(measured, 4.0)

    def test_widening_is_idempotent_and_never_shrinks(self):
        first = stt.widen_capture_pipe(self.r)
        second = stt.widen_capture_pipe(self.r, want=1024)
        self.assertEqual(first, second)

    def test_request_above_the_kernel_cap_still_widens(self):
        # Unprivileged, asking for more than /proc/sys/fs/pipe-max-size is
        # EPERM. Clamping instead of failing is the difference between
        # taking what's available and getting nothing.
        capacity = stt.widen_capture_pipe(self.r, want=1 << 30)
        self.assertIsNotNone(capacity)
        self.assertGreater(capacity, 65536)

    def test_non_pipe_fd_reports_unknown_rather_than_lying(self):
        with open(os.devnull, "rb") as f:
            self.assertIsNone(stt.widen_capture_pipe(f.fileno()))


class PipeReportTest(unittest.TestCase):
    def test_reports_the_depth_in_seconds(self):
        line = stt.capture_pipe_report(256 * 1024)
        self.assertIn("8.2s", line)
        self.assertIn("262144 B", line)

    def test_a_shallow_buffer_says_what_it_will_cost(self):
        line = stt.capture_pipe_report(65536)
        self.assertIn("dropped follow-ups", line)
        self.assertIn("CRT_CAPTURE_PIPE_BYTES", line)

    def test_a_deep_enough_buffer_does_not_cry_wolf(self):
        self.assertNotIn("dropped", stt.capture_pipe_report(256 * 1024))

    def test_unknown_capacity_is_not_reported_as_fine(self):
        line = stt.capture_pipe_report(None)
        self.assertIn("unknown", line)


class BacklogPlanTest(unittest.TestCase):
    """Pure arithmetic -- testable without a pipe at all."""

    def test_nothing_to_drop_when_under_the_limit(self):
        self.assertEqual(stt.backlog_drop_bytes(1000, 96000, stt.NBYTES), 0)

    def test_drops_down_to_the_keep_window(self):
        keep = 3 * BYTES_PER_SEC
        pending = 10 * BYTES_PER_SEC
        drop = stt.backlog_drop_bytes(pending, keep, stt.NBYTES)
        self.assertAlmostEqual(stt.audio_seconds(pending - drop), 3.0, places=1)

    def test_drop_is_chunk_aligned(self):
        # A partial chunk left in the pipe would desynchronise every
        # subsequent read_exact() frame boundary.
        drop = stt.backlog_drop_bytes(97531, 1000, stt.NBYTES)
        self.assertEqual(drop % stt.NBYTES, 0)

    def test_keep_zero_disables_the_drain(self):
        self.assertEqual(stt.backlog_drop_bytes(10 ** 6, 0, stt.NBYTES), 0)

    def test_unknown_pending_drops_nothing(self):
        # pending_bytes() returns None when the kernel won't say; guessing
        # would mean discarding audio on no evidence.
        self.assertEqual(stt.backlog_drop_bytes(None, 96000, stt.NBYTES), 0)


class DrainTest(unittest.TestCase):
    """The real thing: a widened pipe, filled with real bytes, drained."""

    def setUp(self):
        self.r, self.w = os.pipe()
        # Explicitly 1 MiB (~32s) rather than the shipped default, so these
        # cases stay valid if CRT_CAPTURE_PIPE_BYTES is ever retuned -- and
        # so an over-long _fill() can never block this test on a full pipe.
        stt.widen_capture_pipe(self.r, want=1 << 20)
        self.rf = os.fdopen(self.r, "rb", 0)
        self.addCleanup(self._close)

    def _close(self):
        try:
            self.rf.close()
        except OSError:
            pass
        try:
            os.close(self.w)
        except OSError:
            pass

    def _fill(self, seconds):
        os.write(self.w, b"\x01" * int(seconds * BYTES_PER_SEC))

    def test_keeps_the_newest_audio_not_the_oldest(self):
        # Distinguishable halves: the follow-up someone just spoke is at the
        # END of the backlog, so that is the half that has to survive.
        old = b"\xaa" * (4 * BYTES_PER_SEC)
        new = b"\xbb" * (2 * BYTES_PER_SEC)
        os.write(self.w, old + new)
        dropped = stt.drain_capture_backlog(self.rf, 2 * BYTES_PER_SEC)
        self.assertGreater(dropped, 0)
        remaining = self.rf.read(stt.pending_bytes(self.r))
        self.assertNotIn(b"\xaa", remaining)
        self.assertEqual(set(remaining), {0xbb})

    def test_short_backlog_is_left_alone(self):
        self._fill(1.5)
        self.assertEqual(stt.drain_capture_backlog(self.rf, 3 * BYTES_PER_SEC), 0)
        self.assertEqual(stt.pending_bytes(self.r), int(1.5 * BYTES_PER_SEC))

    def test_long_backlog_is_bounded_to_the_keep_window(self):
        self._fill(7.0)
        stt.drain_capture_backlog(self.rf, 3 * BYTES_PER_SEC)
        left = stt.audio_seconds(stt.pending_bytes(self.r))
        self.assertLessEqual(left, 3.1)
        self.assertGreater(left, 2.8)

    def test_remaining_bytes_stay_frame_aligned(self):
        self._fill(9.0)
        stt.drain_capture_backlog(self.rf, 3 * BYTES_PER_SEC)
        self.assertEqual(stt.pending_bytes(self.r) % stt.NBYTES, 0)

    def test_disabled_drain_keeps_everything(self):
        self._fill(9.0)
        self.assertEqual(stt.drain_capture_backlog(self.rf, 0), 0)
        self.assertGreater(stt.audio_seconds(stt.pending_bytes(self.r)), 8.9)

    def test_a_drain_never_blocks_on_an_idle_pipe(self):
        # Nothing queued and no writer active: this runs on every utterance,
        # so blocking here would freeze the console rather than the reverse.
        self.assertEqual(stt.drain_capture_backlog(self.rf, 3 * BYTES_PER_SEC), 0)


class DrainReportTest(unittest.TestCase):
    def test_says_how_much_was_lost_and_why(self):
        line = stt.backlog_drop_report(5 * BYTES_PER_SEC)
        self.assertIn("5.0s", line)
        self.assertIn("too old", line)

    def test_never_silent_about_dropping_audio(self):
        self.assertTrue(stt.backlog_drop_report(stt.NBYTES).strip())


class ReadExactUnbufferedTest(unittest.TestCase):
    """The capture loop now reads an UNBUFFERED fd (bufsize=0), so read()
    returns short. read_exact() has always looped, but nothing pinned it."""

    def setUp(self):
        self.r, self.w = os.pipe()
        self.rf = os.fdopen(self.r, "rb", 0)
        self.addCleanup(self.rf.close)
        self.addCleanup(self._close_w)

    def _close_w(self):
        if self.w is not None:
            os.close(self.w)
            self.w = None

    def test_assembles_a_full_chunk_from_short_reads(self):
        import threading
        payload = (bytes(range(256)) * (stt.NBYTES // 256 + 1))[:stt.NBYTES]

        def dribble():
            for i in range(0, len(payload), 700):
                os.write(self.w, payload[i:i + 700])

        threading.Thread(target=dribble, daemon=True).start()
        self.assertEqual(stt.read_exact(self.rf, stt.NBYTES), payload)

    def test_eof_returns_short_so_the_loop_can_call_it_a_death(self):
        # main() detects a dead arecord by exactly this: a read shorter than
        # a chunk. It must stay true on an unbuffered fd.
        os.write(self.w, b"\x00" * 100)
        self._close_w()
        got = stt.read_exact(self.rf, stt.NBYTES)
        self.assertLess(len(got), stt.NBYTES)


class TestSpawnAndDrain(unittest.TestCase):
    def setUp(self):
        self.stt = load_overlap_stt()

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
        self.stt = load_overlap_stt()
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
        stt = load_overlap_stt()
        self.assertFalse(stt.OVERLAP_TRANSCRIBE)

    def test_overlap_transcribe_turns_on_with_the_env_var(self):
        old = os.environ.get("CRT_OVERLAP_TRANSCRIBE")
        os.environ["CRT_OVERLAP_TRANSCRIBE"] = "1"
        try:
            stt = load_overlap_stt()
            self.assertTrue(stt.OVERLAP_TRANSCRIBE)
        finally:
            if old is None:
                os.environ.pop("CRT_OVERLAP_TRANSCRIBE", None)
            else:
                os.environ["CRT_OVERLAP_TRANSCRIBE"] = old


if __name__ == "__main__":
    unittest.main(verbosity=2)
