#!/usr/bin/env python3
# The idle face must not eat scans (2026-07-25, fifteenth nightly cycle).
#
# The barcode scanner is a USB HID keyboard -- it types into whichever tmux
# window has FOCUS (SCANNER.md, proven live), which is why crt-console.sh
# made `book` the boot-default window. The idle-lean layout
# (CRT_NO_IDLE_CLAUDE=1, what potato's ~/.bash_profile sets) selects the
# screensaver instead, and crt-screensaver.py never read its own stdin. So
# on potato every scan has been typing bare digits into an animation loop:
# no question, no answer window, no training row -- the Book Game funnel's
# first link, dead in the only layout that boots there.
#
# It forwards rather than handles: scanner.log in the exact shape
# crt-book-console.py already tails, so the idle face stays a face with no
# database and no book logic in it.
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import unittest

# Pin the live-console state defaults into tmp BEFORE any bin/ module is
# imported and reads them at module scope (2026-07-25). This file was one of
# five appending to the REAL ~/.crt -- the capture-duck control channel a
# running crt-stt-solo.py reads live, and the state crt-window-switcher.py
# reads to decide whether a brain is behind the screen. tests/run_tests.sh
# pins these for the whole suite; this covers running this file on its own.
_state = tempfile.mkdtemp(prefix="crt-test-state-")
os.environ.setdefault("CRT_CTL_FILE", os.path.join(_state, "ctl"))
os.environ.setdefault("CRT_CLAUDE_ACTIVE_STATE",
                      os.path.join(_state, "claude-window-active.state"))
os.environ.setdefault("CRT_THOUGHT_LOG", os.path.join(_state, "thoughts.log"))
os.environ.setdefault("CRT_STT_GATE_LOG", os.path.join(_state, "thoughts.log"))

BIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")

_spec = importlib.util.spec_from_file_location(
    "crt_screensaver", os.path.join(BIN_DIR, "crt-screensaver.py"))
ss = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ss)

_bc_spec = importlib.util.spec_from_file_location(
    "crt_book_console_for_screensaver_test", os.path.join(BIN_DIR, "crt-book-console.py"))
bc = importlib.util.module_from_spec(_bc_spec)
_bc_spec.loader.exec_module(bc)

ISBN = "9780141439518"


class TestScanForwarder(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.log = os.path.join(self.dir.name, "sub", "scanner.log")
        self.thoughts = os.path.join(self.dir.name, "thoughts.log")

    def tearDown(self):
        self.dir.cleanup()

    def test_a_scan_on_the_idle_face_reaches_the_book_window(self):
        ss.scan_forwarder(io.StringIO(ISBN + "\n"), log_path=self.log)
        with open(self.log) as f:
            written = f.read()
        # Not just "the ISBN is in there somewhere": the reader on the other
        # end has to accept the exact line.
        self.assertEqual(bc.parse_scanner_log_line(written), ISBN)

    def test_forwards_every_scan_in_a_run_not_just_the_first(self):
        other = "9780451524935"
        ss.scan_forwarder(io.StringIO("%s\n%s\n" % (ISBN, other)), log_path=self.log)
        with open(self.log) as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
        self.assertEqual([bc.parse_scanner_log_line(ln) for ln in lines], [ISBN, other])

    def test_stray_keystrokes_are_not_written_to_the_audit_log(self):
        # scanner.log is a record of scans. A library card, a mis-swipe, or
        # someone leaning on the keyboard is not one -- and the terminal's
        # own echo of it gets painted over by the next frame anyway.
        ss.scan_forwarder(io.StringIO("hello there\n\n   \nnot-an-isbn\n"), log_path=self.log)
        self.assertFalse(os.path.exists(self.log))

    def test_a_scan_it_cannot_pass_on_is_said_out_loud(self):
        # Invisible twice over otherwise: the person sees the potato before
        # the scan and after it, with nothing to distinguish "caught it and
        # dropped it" from "never saw it".
        blocker = os.path.join(self.dir.name, "blocker")
        open(blocker, "w").close()
        try:
            ss.THOUGHT_LOG, saved = self.thoughts, ss.THOUGHT_LOG
            ss.scan_forwarder(io.StringIO(ISBN + "\n"),
                              log_path=os.path.join(blocker, "scanner.log"))
        finally:
            ss.THOUGHT_LOG = saved
        with open(self.thoughts) as f:
            said = f.read()
        self.assertIn(ISBN, said)
        self.assertIn("[!]", said)

    def test_a_broken_scanner_log_never_takes_the_idle_face_down(self):
        # This runs on a daemon thread inside the screensaver. A raise here
        # would kill the forwarder silently and leave the potato breathing
        # away, which is the failure mode this whole cycle is about.
        blocker = os.path.join(self.dir.name, "blocker2")
        open(blocker, "w").close()
        seen = []
        ss.scan_forwarder(io.StringIO(ISBN + "\n"),
                          log_path=os.path.join(blocker, "scanner.log"),
                          on_line=lambda isbn, ok: seen.append((isbn, ok)))
        self.assertEqual(seen, [(ISBN, False)])


class TestScanFailureReport(unittest.TestCase):
    def test_names_the_isbn_so_it_can_be_scanned_again(self):
        line = ss.scan_failure_report(ISBN, "No space left on device")
        self.assertIn(ISBN, line)
        self.assertIn("No space left", line)

    def test_fits_the_tube(self):
        self.assertLess(len(ss.scan_failure_report(ISBN, "read-only file system")), 80)


class TestForwardScan(unittest.TestCase):
    def test_creates_the_log_directory_on_a_fresh_machine(self):
        with tempfile.TemporaryDirectory() as d:
            ok, detail = ss.forward_scan(ISBN, os.path.join(d, "a", "b", "scanner.log"))
            self.assertTrue(ok, detail)

    def test_reports_rather_than_raises_when_it_cannot_write(self):
        with tempfile.TemporaryDirectory() as d:
            blocker = os.path.join(d, "blocker")
            open(blocker, "w").close()
            ok, detail = ss.forward_scan(ISBN, os.path.join(blocker, "scanner.log"))
            self.assertFalse(ok)
            self.assertTrue(detail)


class TestTheIdleFaceStaysLight(unittest.TestCase):
    """POTATO.md's whole point: this window holds NO brain on a 1GB Pi.
    Reusing the scan-line contract must not drag the book stack in with
    it."""

    def test_no_database_or_network_module_pulled_into_the_screensaver(self):
        # Asked of a fresh interpreter that loads ONLY this file, not of its
        # source text: what matters is what actually gets imported at
        # runtime, and this test process has already loaded the book stack
        # for its own assertions above.
        probe = (
            "import importlib.util, sys\n"
            "s = importlib.util.spec_from_file_location('ss', %r)\n"
            "m = importlib.util.module_from_spec(s); s.loader.exec_module(m)\n"
            "print(','.join(n for n in ('sqlite3', 'urllib.request', 'sqlite3.dbapi2')\n"
            "               if n in sys.modules))\n" % os.path.join(BIN_DIR, "crt-screensaver.py")
        )
        out = subprocess.run([sys.executable, "-c", probe],
                             capture_output=True, text=True, check=True)
        self.assertEqual(out.stdout.strip(), "",
                         "the idle face pulled the book stack in with it")


if __name__ == "__main__":
    unittest.main()
