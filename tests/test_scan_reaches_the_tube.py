#!/usr/bin/env python3
# A scan has to end up ON THE TUBE (2026-07-25, fifteenth nightly cycle).
#
# THE BUG. crt-console.sh made `book` the boot-default window for one
# concrete reason, recorded in its own comment: the barcode scanner is a USB
# HID keyboard and types into whichever tmux window has FOCUS (SCANNER.md's
# "2026-07-21 late session" finding, proven live). The idle-lean layout
# (CRT_NO_IDLE_CLAUDE=1 -- what potato's ~/.bash_profile actually sets, per
# .claude/SESSION-STATE.md) selects the screensaver instead, and nothing
# ever handed focus back. So the `book` window drew its question onto a
# window nobody was looking at, and the tube kept showing a sleeping potato.
#
# The integration test at the bottom is the load-bearing one: it runs the
# real crt-book-console.py against a fake `tmux` on PATH (same shim idea as
# tests/test_console_book_game_layout.sh) and asserts the select-window
# actually happens on a scan -- not that a helper function exists.
import importlib.util
import os
import subprocess
import sys
import tempfile
import time
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")

_bg_spec = importlib.util.spec_from_file_location("crt_book_game", os.path.join(BIN_DIR, "crt-book-game.py"))
bg = importlib.util.module_from_spec(_bg_spec)
_bg_spec.loader.exec_module(bg)

_bc_spec = importlib.util.spec_from_file_location("crt_book_console", os.path.join(BIN_DIR, "crt-book-console.py"))
bc = importlib.util.module_from_spec(_bc_spec)
_bc_spec.loader.exec_module(bc)

ISBN = "9780141439518"

FAKE_TMUX = """#!/bin/sh
# Records every tmux call, and answers the one query the console makes.
printf '%s\\n' "$*" >> "$TMUX_CALL_LOG"
if [ "$1" = "display-message" ]; then
  cat "$TMUX_ACTIVE_WINDOW"
fi
exit 0
"""


class TestShouldReleaseTube(unittest.TestCase):
    """Handing the tube BACK when the question times out. Without this the
    idle-lean layout loses its idle face permanently on the first scan --
    which would make the fix for the bug above a second bug."""

    def test_releases_to_the_idle_face_when_it_still_holds_focus(self):
        self.assertTrue(bc.should_release_tube(
            active_window="book", holding=True, idle_face_window="0", book_window="book"))

    def test_nothing_to_release_when_this_window_is_the_idle_face(self):
        # The historical layout: `book` IS the boot default, CRT_IDLE_FACE_WINDOW
        # unset. Releasing would mean switching to a window that has no
        # claim on the tube.
        self.assertFalse(bc.should_release_tube(
            active_window="book", holding=True, idle_face_window="", book_window="book"))

    def test_does_not_release_a_tube_it_never_took(self):
        # take_tube() failed (no tmux, no such window): there is nothing to
        # give back, and switching anyway would move focus off whatever the
        # person is actually looking at.
        self.assertFalse(bc.should_release_tube(
            active_window="book", holding=False, idle_face_window="0", book_window="book"))

    def test_never_yanks_focus_from_a_window_chosen_by_hand(self):
        # Someone pressed prefix+1 to read window 1 while the question was
        # up. Same refusal crt-window-switcher.py's own decision function
        # makes -- and the same one cycle 10 had to add there.
        self.assertFalse(bc.should_release_tube(
            active_window="mono", holding=True, idle_face_window="0", book_window="book"))


class TestFocusFailureReport(unittest.TestCase):
    def test_says_the_scan_registered_and_names_the_window(self):
        line = bc.focus_failure_report("claude:book", "can't find window: book")
        self.assertIn("scanned", line)
        self.assertIn("claude:book", line)
        self.assertIn("can't find window", line)

    def test_fits_the_tube(self):
        # 40 columns, and window 1 wraps rather than truncates.
        self.assertLess(len(bc.focus_failure_report("claude:book", "no server")), 80)


class TestAnnounce(unittest.TestCase):
    def test_writes_to_the_window_1_channel(self):
        with tempfile.TemporaryDirectory() as d:
            log = os.path.join(d, "sub", "thoughts.log")
            bc.announce("[!] something honest", log_path=log)
            with open(log) as f:
                self.assertIn("something honest", f.read())

    def test_a_broken_log_never_raises(self):
        # The caller is a loop that is already dealing with a bigger problem.
        with tempfile.TemporaryDirectory() as d:
            blocker = os.path.join(d, "blocker")
            open(blocker, "w").close()
            bc.announce("x", log_path=os.path.join(blocker, "thoughts.log"))


class TestScanBringsTheBookWindowToTheTube(unittest.TestCase):
    """The real thing: run crt-book-console.py, scan into its stdin, and
    watch for the select-window that puts the question in front of the
    person who just scanned. Fails against the parent commit."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.calls = os.path.join(self.dir, "tmux-calls.log")
        self.active = os.path.join(self.dir, "active-window")
        with open(self.active, "w") as f:
            f.write("book\n")
        binstub = os.path.join(self.dir, "tmux")
        with open(binstub, "w") as f:
            f.write(FAKE_TMUX)
        os.chmod(binstub, 0o755)

        # A book already on the shelf: handle_scan() then takes its
        # re-scan branch (touch_scan), so this test never touches the
        # network.
        self.db = os.path.join(self.dir, "books.db")
        conn = bg.get_db(self.db)
        bg.register_book(conn, {"isbn": ISBN, "title": "Nineteen Eighty-Four",
                                "authors": ["George Orwell"], "year": 1949, "subjects": []},
                         questions=[{"text": "Fiction or nonfiction?",
                                     "options": ["fiction", "nonfiction"],
                                     "correct": "fiction"}],
                         question_source="template")
        conn.close()

        env = dict(os.environ)
        env.update({
            "PATH": self.dir + os.pathsep + env.get("PATH", ""),
            "TMUX_CALL_LOG": self.calls,
            "TMUX_ACTIVE_WINDOW": self.active,
            "CRT_TMUX_SESSION": "testsess",
            "CRT_IDLE_FACE_WINDOW": "0",
            "CRT_BOOKS_DB": self.db,
            "CRT_SCANNER_LOG": os.path.join(self.dir, "scanner.log"),
            "CRT_THOUGHT_LOG": os.path.join(self.dir, "thoughts.log"),
            "CRT_BOOK_GAME_TRAINING_LOG": os.path.join(self.dir, "training.jsonl"),
            "CRT_BOOK_CONSOLE_POLL_SECS": "0.1",
            "CRT_BOOK_CONSOLE_IDLE_SECS": "2",
            "CRT_COLS": "40", "CRT_ROWS": "15",
        })
        self.proc = subprocess.Popen(
            [sys.executable, os.path.join(BIN_DIR, "crt-book-console.py")],
            env=env, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, text=True)

    def tearDown(self):
        self.proc.kill()
        self.proc.wait(timeout=10)
        self.proc.stdin.close()
        self.proc.stderr.close()

    def _wait_for(self, needle, timeout=20.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                self.fail("book console exited early: %s" % self.proc.stderr.read())
            try:
                with open(self.calls) as f:
                    if needle in f.read():
                        return True
            except OSError:
                pass
            time.sleep(0.1)
        return False

    def test_a_scan_selects_the_book_window_and_then_gives_it_back(self):
        self.proc.stdin.write(ISBN + "\n")
        self.proc.stdin.flush()
        self.assertTrue(
            self._wait_for("select-window -t testsess:book"),
            "a scan drew its question but never brought the window to the front; "
            "on the idle-lean layout the tube stays on the screensaver")
        # ...and CRT_BOOK_CONSOLE_IDLE_SECS later, the idle face gets it
        # back -- otherwise this fix costs the screensaver permanently.
        self.assertTrue(
            self._wait_for("select-window -t testsess:0"),
            "the question timed out but the idle face never got the tube back")

    def test_the_scan_still_reaches_the_registry_and_the_audit_log(self):
        # Guards the obvious way to break the funnel while fixing focus:
        # taking the tube must not replace handling the scan.
        self.proc.stdin.write(ISBN + "\n")
        self.proc.stdin.flush()
        self.assertTrue(self._wait_for("select-window -t testsess:book"))
        with open(os.path.join(self.dir, "scanner.log")) as f:
            self.assertIn(ISBN, f.read())
        conn = bg.get_db(self.db)
        self.assertIsNotNone(bg.get_book(conn, ISBN)["last_scanned"])
        conn.close()


class TestScanLineContractIsOneModule(unittest.TestCase):
    """crt-screensaver.py writes scanner.log now too. Both ends ask the same
    module what a scan line looks like -- a second opinion would break the
    funnel silently, since a line written in a shape the reader rejects is
    indistinguishable from no scan at all."""

    def test_the_console_reads_exactly_what_the_shared_writer_writes(self):
        _sl_spec = importlib.util.spec_from_file_location(
            "crt_scan_line_under_test", os.path.join(BIN_DIR, "crt_scan_line.py"))
        sl = importlib.util.module_from_spec(_sl_spec)
        _sl_spec.loader.exec_module(sl)
        self.assertEqual(bc.parse_scanner_log_line(sl.format_scan_log_line(ISBN)), ISBN)

    def test_book_game_and_the_shared_module_agree_on_what_an_isbn_is(self):
        for candidate in (ISBN, "123456789X", "not an isbn", "", "12345"):
            self.assertEqual(bool(bg.is_isbn_like(candidate)),
                             bool(bc.parse_stdin_scan_line(candidate + "\n")),
                             candidate)


if __name__ == "__main__":
    unittest.main()
