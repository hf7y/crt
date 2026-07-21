#!/usr/bin/env python3
# Offline tests for bin/crt-scanner-feed.py's log-only behavior
# (2026-07-21 input-routing cleanup -- see that file's own header). No
# HTTP server/tmux needed: log_scan() is a pure-ish local-file write, and
# this suite's real job is confirming the old tmux-delivery path (deliver())
# is actually gone, not just undocumented.
import importlib.util
import os
import tempfile
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")


def load_scanner_feed():
    spec = importlib.util.spec_from_file_location(
        "crt_scanner_feed", os.path.join(BIN_DIR, "crt-scanner-feed.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestScannerFeedLogOnly(unittest.TestCase):
    def setUp(self):
        self.mod = load_scanner_feed()
        self.tmpdir = tempfile.mkdtemp()
        self.mod.LOG_PATH = os.path.join(self.tmpdir, "scanner.log")

    def test_log_scan_writes_the_line(self):
        self.mod.log_scan("9780141439518")
        with open(self.mod.LOG_PATH) as f:
            contents = f.read()
        self.assertIn("9780141439518", contents)

    def test_no_tmux_delivery_path_exists(self):
        # The pre-pivot deliver() (tmux send-keys into whatever window had
        # focus) was a second, uncontrolled escalation path alongside
        # STT's gated one -- removed entirely, not just unused.
        self.assertFalse(hasattr(self.mod, "deliver"))


if __name__ == "__main__":
    unittest.main()
