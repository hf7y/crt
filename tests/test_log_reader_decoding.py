#!/usr/bin/env python3
# Every long-lived window on this console reads a log another process is
# appending to, and until 2026-07-25 every one of them decoded it strictly.
#
# A reader that catches up to a writer mid-character sees a partial UTF-8
# sequence -- book titles carry accents, idle-bait quotes carry em-dashes,
# and a barcode scanner is a keyboard-emulating device that can put
# arbitrary bytes into scanner.log. Strict decoding raises
# UnicodeDecodeError, which is a ValueError: NOT caught by the `except
# OSError` those loops wrap their reads in, and raised inside a tail
# generator it is outside main()'s LoopGuard too.
#
# The window that would die first is window 1 -- the one every honest-
# failure line the last eleven cycles added reports to.
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")

# A truncated two-byte character followed by junk: what a reader sees when
# it catches up to a writer mid-flush, or when a keyboard-emulating barcode
# scanner misreads.
GARBAGE = b"\xff\xfe\x00raw scanner bytes\n"


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(BIN_DIR, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestMonologueReadsTornBytes(unittest.TestCase):
    def test_the_real_process_keeps_rendering_after_a_torn_byte(self):
        # The read lives inside main()'s never-returning while-loop, so the
        # only honest way to test it is to run the real process. Against a
        # strict-decoding version this exits within one poll.
        with tempfile.TemporaryDirectory() as d:
            log = os.path.join(d, "thoughts.log")
            with open(log, "wb") as f:
                f.write(b"12:00:00  before\n")
            env = dict(os.environ, CRT_THOUGHT_LOG=log, CRT_COLS="40", CRT_ROWS="15")
            proc = subprocess.Popen([sys.executable, os.path.join(BIN_DIR, "crt-monologue.py")],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
            try:
                time.sleep(0.6)
                with open(log, "ab") as f:
                    f.write(b"12:00:01  caf\xc3")     # partial two-byte char
                    f.flush()
                time.sleep(1.2)
                self.assertIsNone(proc.poll(),
                                  "crt-monologue.py exited on a torn byte -- window 1 went dark")
            finally:
                proc.kill()
                proc.communicate(timeout=10)


class TestTailGeneratorsSurviveBadBytes(unittest.TestCase):
    """These matter most: a tail generator raising is outside the
    LoopGuard, so it ends the window outright."""

    def _first_lines(self, mod, path, count):
        got = []
        for line in mod.tail_new_lines(path):
            if line is None:
                break          # caught up; the generator would sleep next
            got.append(line)
            if len(got) >= count:
                break
        return got

    def test_book_answer_listen_tail_does_not_raise(self):
        mod = _load("crt_book_answer_listen_decode", "crt-book-answer-listen.py")
        with tempfile.TemporaryDirectory() as d:
            log = os.path.join(d, "stt.log")
            with open(log, "wb") as f:
                f.write(b"")
            gen = mod.tail_new_lines(log)
            self.assertIsNone(next(gen))            # positioned at EOF
            with open(log, "ab") as f:
                f.write(GARBAGE)
            line = next(gen)
        self.assertIsInstance(line, str)

    def test_book_console_tail_does_not_raise(self):
        mod = _load("crt_book_console_decode", "crt-book-console.py")
        with tempfile.TemporaryDirectory() as d:
            log = os.path.join(d, "scanner.log")
            with open(log, "wb") as f:
                f.write(b"")
            gen = mod.tail_new_lines(log)
            self.assertIsNone(next(gen))
            with open(log, "ab") as f:
                f.write(GARBAGE)
            line = next(gen)
        self.assertIsInstance(line, str)

    def test_book_console_training_tail_does_not_raise(self):
        mod = _load("crt_book_console_decode2", "crt-book-console.py")
        with tempfile.TemporaryDirectory() as d:
            log = os.path.join(d, "book-game-training.jsonl")
            with open(log, "wb") as f:
                f.write(b"")
            tail = mod.open_training_tail(log)
            with open(log, "ab") as f:
                f.write(GARBAGE)
            line = tail.readline()
        self.assertIsInstance(line, str)


class TestClaudeBridgeReadsTornBytes(unittest.TestCase):
    def test_the_real_process_keeps_mirroring_after_a_torn_byte(self):
        with tempfile.TemporaryDirectory() as d:
            proj, out = os.path.join(d, "proj"), os.path.join(d, "thoughts.log")
            os.makedirs(proj)
            transcript = os.path.join(proj, "session.jsonl")
            open(transcript, "wb").close()
            env = dict(os.environ, CRT_CLAUDE_PROJECT_DIR=proj,
                       CRT_THOUGHT_LOG=out, CRT_BRIDGE_POLL="0.1")
            proc = subprocess.Popen([sys.executable, os.path.join(BIN_DIR, "crt-claude-bridge.py")],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
            try:
                time.sleep(0.6)
                # Marked with the guillemet: crt-claude-bridge.py suppresses
                # unmarked replies until CRT_BRIDGE_FALLBACK_STALE_SECS
                # (see CLAUDE.md's window-1 section), which would outlast
                # this test and make it look like a decode failure.
                entry = {"type": "assistant",
                         "message": {"content": [{"type": "text", "text": "\u00bb hello from claude"}]}}
                with open(transcript, "ab") as f:
                    f.write((json.dumps(entry) + "\n").encode())
                    f.write(b'{"type": "assistant", "message": {"content": [{"type":'
                            b' "text", "text": "caf\xc3')      # torn mid-character
                    f.flush()
                time.sleep(1.2)
                self.assertIsNone(proc.poll(),
                                  "crt-claude-bridge.py exited on a torn byte -- "
                                  "claude's replies stop reaching window 1")
                with open(out) as f:
                    self.assertIn("hello from claude", f.read())
            finally:
                proc.kill()
                proc.communicate(timeout=10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
