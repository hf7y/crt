#!/usr/bin/env python3
"""The book window measures the tube it is actually drawing on.

WHY THIS EXISTS (2026-07-25, sixteenth nightly cycle). `crt-console.sh`
builds every window with `tmux new-window -d` and only runs
`exec tmux attach` at the very end, after all of them exist. A detached
tmux session is 80x24 regardless of the tube, so every one of those
processes is born believing it has 80 columns and 24 rows. Measured, not
assumed -- `tmux new-session -d; tmux new-window -d` then
`shutil.get_terminal_size()` inside that window reports exactly
`os.terminal_size(columns=80, lines=24)` on tmux 3.6.

`crt-screensaver.py` was fixed for this on 2026-07-23 (re-read the size
every frame) and `crt-monologue.py` in `6aecc39`. `crt-book-console.py` --
the third window that paints a full screen, and the one that draws the
trivia question the whole Book Game funnel exists to put in front of
someone -- sized itself once in `main()` and never again. On the real
40x15 tube that means every screen it draws is laid out 80 wide and 24
tall: each line wraps to two rows, 24 lines become 48 in a 15-row pane,
and the question scrolls itself off the top before anyone reads it. It
never recovers, because nothing measures a second time.

This is FOCUS.md's own 2026-07-23 13:40 line from Zach, in code:
"figure out what's wrong with the text column constraints, problem on
mono window and more."

Two halves, one per test class:
  - detect_screen_size() honors CRT_COLS/CRT_ROWS, the pins crt-console.sh
    already writes for the tube and that the other two renderers read.
  - the RUNNING console repaints at the new size when the terminal it is
    attached to is resized under it -- driven through a real pty, resized
    with a real TIOCSWINSZ, which is what `tmux attach` does to these panes.
"""
import fcntl
import importlib.util
import os
import pty
import re
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
    "crt_book_game_for_size_test", os.path.join(BIN_DIR, "crt-book-game.py"))
bg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bg)

SIZE_ENV = ("CRT_BOOK_GAME_WIDTH", "CRT_BOOK_GAME_HEIGHT", "CRT_COLS", "CRT_ROWS",
            "COLUMNS", "LINES")
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
ISBN = "9780451524935"


class DetectScreenSizeTest(unittest.TestCase):
    """The pin crt-console.sh writes has to reach this renderer too."""

    def setUp(self):
        self.saved = {k: os.environ.get(k) for k in SIZE_ENV}
        for k in SIZE_ENV:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_crt_cols_rows_pin_is_honored(self):
        # The whole point: crt-console.sh pins these for the screensaver with
        # a comment saying exactly why, and this window read neither.
        os.environ["CRT_COLS"], os.environ["CRT_ROWS"] = "40", "15"
        self.assertEqual(bg.detect_screen_size(), (40, 15))

    def test_the_games_own_override_still_wins(self):
        os.environ["CRT_COLS"], os.environ["CRT_ROWS"] = "40", "15"
        os.environ["CRT_BOOK_GAME_WIDTH"] = "72"
        os.environ["CRT_BOOK_GAME_HEIGHT"] = "20"
        self.assertEqual(bg.detect_screen_size(), (72, 20),
                         "BOOK-GAME-STYLE.md documents the game's own vars as "
                         "the top of the precedence chain")

    def test_each_dimension_resolves_independently(self):
        # A pin for one and auto-detect for the other is legitimate; it must
        # not throw both away, which is what `if env_w and env_h` did.
        # 52, not 40: 40 is also the fallback, so it would pass by accident
        # against a version that ignored the pin entirely.
        os.environ["CRT_COLS"] = "52"
        w, h = bg.detect_screen_size()
        self.assertEqual(w, 52)
        self.assertTrue(h > 0)

    def test_junk_falls_through_instead_of_raising(self):
        # These names are set by shell. A typo in crt-console.sh must degrade
        # to auto-detection, not kill the window that draws the question --
        # the old bare int() raised ValueError right out of main()'s first line.
        os.environ["CRT_COLS"], os.environ["CRT_ROWS"] = "", "forty"
        os.environ["CRT_BOOK_GAME_WIDTH"] = "-3"
        w, h = bg.detect_screen_size()
        self.assertTrue(w > 0 and h > 0)


class ResizeRepaintTest(unittest.TestCase):
    """A real pty, resized under a running console, exactly as an attaching
    tmux client resizes these panes.

    Deliberately not a monkeypatched seam: the claim being tested is that
    THIS PROCESS, started at one size, ends up drawing at another. A helper
    function returning the right number proves nothing about a `main()` that
    reads it once.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="crt-book-size-")
        self.master, self.slave = pty.openpty()
        self._resize(80, 24)   # what tmux reports inside a detached session

        db = os.path.join(self.tmp, "books.db")
        conn = bg.get_db(db)
        bg.register_book(conn, {"isbn": ISBN, "title": "Nineteen Eighty-Four",
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
        self.proc = subprocess.Popen(
            [sys.executable, os.path.join(BIN_DIR, "crt-book-console.py")],
            env=env, stdin=subprocess.DEVNULL, stdout=self.slave,
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

    def _frames(self):
        """Every full-screen paint so far, as lists of ANSI-stripped lines.

        draw() starts each one with the home+clear sequence, so that is the
        frame separator. The pty's own ONLCR turns every '\n' into '\r\n', so
        the '\r' comes off before anything measures a line -- without that
        every line reads one column wider than it was drawn."""
        with self.lock:
            text = self.out.decode("utf-8", "replace")
        parts = text.split("\x1b[H\x1b[2J")[1:]
        return [[ANSI.sub("", ln).rstrip("\r") for ln in p.split("\n")]
                for p in parts]

    def _wait_for_frame_width(self, want, timeout=15.0):
        """Wait for a painted frame whose lines are `want` columns wide.

        render_idle_screen() pads every line to exactly the detected width,
        so the widest line in a frame IS the width it was laid out for."""
        deadline = time.time() + timeout
        seen = set()
        while time.time() < deadline:
            if self.proc.poll() is not None:
                self.fail("book console exited early (rc=%s)" % self.proc.poll())
            for frame in self._frames():
                widths = {len(ln) for ln in frame if ln}
                seen |= widths
                if widths and max(widths) == want:
                    return True
            time.sleep(0.2)
        self.fail("no frame at %d columns after %.0fs; line widths seen: %s"
                  % (want, timeout, sorted(seen)))

    def test_it_repaints_when_the_tube_turns_out_to_be_smaller(self):
        # Born at 80x24 -- the size tmux reports inside the detached session
        # crt-console.sh builds.
        self._wait_for_frame_width(80)
        # ...then the client attaches and the pane becomes the real tube.
        self._resize(40, 15)
        # Before this cycle the console never asked again, and every frame for
        # the rest of its life was 80 columns wrapping into a 40-column pane.
        self._wait_for_frame_width(40)

    def test_the_repaint_is_a_full_screen_that_fits_the_pane(self):
        self._wait_for_frame_width(80)
        self._resize(40, 15)
        self._wait_for_frame_width(40)
        frame = self._frames()[-1]
        body = [ln for ln in frame if ln]
        self.assertTrue(body, "repainted an empty frame")
        self.assertTrue(all(len(ln) <= 40 for ln in body),
                        "a line longer than the pane wraps on the tube: %r"
                        % [ln for ln in body if len(ln) > 40][:2])
        # 15 rows of content, not 24 scrolling their own top away.
        self.assertLessEqual(len(frame), 16,
                             "frame is taller than the pane it is drawn into")


if __name__ == "__main__":
    unittest.main()
