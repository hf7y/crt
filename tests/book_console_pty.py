#!/usr/bin/env python3
"""A real running `crt-book-console.py` on a real pty, for tests that are
about the PROCESS rather than about a pure function.

Not named test_*.py on purpose: run_tests.sh's manifest check globs
test_*.{sh,py} and would demand an invocation for this, which has no tests
of its own to run.

WHY IT IS SHARED (2026-07-25, seventeenth nightly cycle). The sixteenth
cycle built this harness inside tests/test_book_console_size.py to prove
that a console born at 80x24 repaints when the tube turns out to be 40x15 --
a claim about a `main()` that read the size once, which no monkeypatched
seam can test. This cycle needed the same harness for a different claim
about the same loop (does the idle screen ever draw a second time?), and a
copy of ~90 lines of pty plumbing is exactly the drift the last three cycles
have been paying off elsewhere in this repo (crt_scan_line.py, crt_wake_gate.py,
crt_fixups_store.py). One home.

Subclass, set EXTRA_ENV, get a console running against a temp books.db with
one book already registered.
"""
import fcntl
import importlib.util
import os
import pty
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")

_spec = importlib.util.spec_from_file_location(
    "crt_book_game_for_pty_harness", os.path.join(BIN_DIR, "crt-book-game.py"))
bg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bg)

# Every env var that can decide the console's screen size. Cleared for the
# child so the pty is the only size source, and saved/restored around the
# in-process tests that set them.
SIZE_ENV = ("CRT_BOOK_GAME_WIDTH", "CRT_BOOK_GAME_HEIGHT", "CRT_COLS", "CRT_ROWS",
            "COLUMNS", "LINES")
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
ISBN = "9780451524935"
TITLE = "Nineteen Eighty-Four"


class BookConsolePty(unittest.TestCase):
    """A live console attached to a pty this test owns both ends of.

    Deliberately not a monkeypatched seam: these subclasses assert things
    about a long-running loop -- that it measures again, that it draws
    again -- and a helper function returning the right value proves nothing
    about a loop that calls it once.
    """

    START_SIZE = (80, 24)   # what tmux reports inside the detached session
    EXTRA_ENV = {}          # subclass hook: env for the console under test

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="crt-book-pty-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.master, self.slave = pty.openpty()
        self._resize(*self.START_SIZE)

        db = os.path.join(self.tmp, "books.db")
        conn = bg.get_db(db)
        bg.register_book(conn, {"isbn": ISBN, "title": TITLE,
                                "authors": ["George Orwell"], "year": 1949,
                                "subjects": []},
                         questions=[{"text": "Fiction or nonfiction?",
                                     "options": ["fiction", "nonfiction"],
                                     "correct": "fiction"}],
                         question_source="template")
        conn.close()

        env = dict(os.environ)
        for k in SIZE_ENV:
            env.pop(k, None)          # the pty is the only size source here
        env.update({
            "CRT_BOOKS_DB": db,
            "CRT_SCANNER_LOG": os.path.join(self.tmp, "scanner.log"),
            "CRT_THOUGHT_LOG": os.path.join(self.tmp, "thoughts.log"),
            "CRT_BOOK_GAME_TRAINING_LOG": os.path.join(self.tmp, "training.jsonl"),
            "CRT_BOOK_CONSOLE_POLL_SECS": "0.1",
            "CRT_BOOK_CONSOLE_IDLE_SECS": "600",   # never time out mid-test
            "CRT_IDLE_FACE_WINDOW": "",            # nothing to hand focus to
        })
        env.update(self.EXTRA_ENV)
        self.proc = subprocess.Popen(
            [sys.executable, os.path.join(BIN_DIR, "crt-book-console.py")],
            env=env, stdin=subprocess.PIPE, stdout=self.slave,
            stderr=subprocess.DEVNULL, close_fds=True)
        os.close(self.slave)          # so a dead child gives us EOF, not a hang

        # Drain continuously: an unread pty buffer fills and blocks the child
        # mid-frame, which would look exactly like "it never repainted".
        self.out = bytearray()
        self.lock = threading.Lock()
        self.reader = threading.Thread(target=self._drain, daemon=True)
        self.reader.start()

    def tearDown(self):
        self.proc.kill()
        self.proc.wait(timeout=10)
        self.proc.stdin.close()
        try:
            os.close(self.master)
        except OSError:
            pass

    def _drain(self):
        while True:
            try:
                chunk = os.read(self.master, 4096)
            except OSError:
                return
            if not chunk:
                return
            with self.lock:
                self.out += chunk

    def _resize(self, cols, rows):
        """TIOCSWINSZ on the master -- one pty, one window size, whichever end
        you set it from. This is what a tmux client attaching does to a pane."""
        fcntl.ioctl(self.master, termios.TIOCSWINSZ,
                    struct.pack("HHHH", rows, cols, 0, 0))

    def _scan(self, isbn=ISBN):
        """A scan, delivered the way the real barcode scanner delivers one:
        keystrokes into this window's stdin, terminated by Enter."""
        self.proc.stdin.write((isbn + "\n").encode())
        self.proc.stdin.flush()

    def _frames(self):
        """Every full-screen paint so far, as lists of ANSI-stripped lines.

        draw() starts each one with the home+clear sequence, so that is the
        frame separator. The pty's own ONLCR turns every '\\n' into '\\r\\n', so
        the '\\r' comes off before anything measures a line -- without that
        every line reads one column wider than it was drawn."""
        with self.lock:
            text = self.out.decode("utf-8", "replace")
        parts = text.split("\x1b[H\x1b[2J")[1:]
        return [[ANSI.sub("", ln).rstrip("\r") for ln in p.split("\n")]
                for p in parts]

    def _assert_alive(self):
        if self.proc.poll() is not None:
            self.fail("book console exited early (rc=%s)" % self.proc.poll())

    def _wait_for_frame_width(self, want, timeout=15.0):
        """Wait for a painted frame whose lines are `want` columns wide.

        render_idle_screen() pads every line to exactly the detected width,
        so the widest line in a frame IS the width it was laid out for."""
        deadline = time.time() + timeout
        seen = set()
        while time.time() < deadline:
            self._assert_alive()
            for frame in self._frames():
                widths = {len(ln) for ln in frame if ln}
                seen |= widths
                if widths and max(widths) == want:
                    return True
            time.sleep(0.2)
        self.fail("no frame at %d columns after %.0fs; line widths seen: %s"
                  % (want, timeout, sorted(seen)))

    def _wait_for_text(self, needle, timeout=15.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._assert_alive()
            for frame in self._frames():
                if needle in " ".join(frame):
                    return True
            time.sleep(0.2)
        self.fail("never saw %r on any frame after %.0fs" % (needle, timeout))

    def _wait_for_frame_count(self, want, timeout=15.0):
        """Wait until at least `want` full-screen paints have happened."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._assert_alive()
            if len(self._frames()) >= want:
                return len(self._frames())
            time.sleep(0.1)
        return len(self._frames())
