#!/usr/bin/env python3
# Tests for bin/crt-remote-claude-bridge.py -- the mandark-side half of
# "run Claude Code off potato" (2026-07-23). Uses a REAL tmux session
# (short-lived, killed in tearDown) and a real socket connection to the
# server's CAPTURE/SEND protocol, same "test against the real mechanism,
# not a mock of it" posture as this project's other tmux-touching tests.
import importlib.util
import os
import socket
import subprocess
import threading
import time
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")

_spec = importlib.util.spec_from_file_location(
    "crt_remote_claude_bridge", os.path.join(BIN_DIR, "crt-remote-claude-bridge.py"))
bridge = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bridge)

TEST_SESSION = "crt-test-remote-bridge-session"
TEST_PORT = 18993  # unlikely to collide with a real run's 8993


def tmux_running():
    return subprocess.run(["tmux", "-V"], capture_output=True).returncode == 0


@unittest.skipUnless(tmux_running(), "tmux not available in this environment")
class TestRemoteClaudeBridge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run(["tmux", "kill-session", "-t", TEST_SESSION],
                        capture_output=True)
        subprocess.run(["tmux", "new-session", "-d", "-s", TEST_SESSION, "-x", "80", "-y", "24",
                        "bash", "--norc"], check=True)
        cls.server = bridge.Server(("127.0.0.1", TEST_PORT), bridge.Handler)
        cls.server.session = TEST_SESSION
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.2)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        subprocess.run(["tmux", "kill-session", "-t", TEST_SESSION], capture_output=True)

    def _request(self, command):
        with socket.create_connection(("127.0.0.1", TEST_PORT), timeout=5) as s:
            s.sendall((command + "\n").encode("utf-8"))
            s.shutdown(socket.SHUT_WR)
            chunks = []
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
            return b"".join(chunks).decode("utf-8", errors="replace")

    def test_capture_returns_pane_content(self):
        result = self._request("CAPTURE")
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_send_types_text_into_the_session(self):
        marker = "crt_test_marker_xyz123"
        self._request("SEND echo " + marker)
        time.sleep(0.5)
        result = self._request("CAPTURE")
        self.assertIn(marker, result)

    def test_send_returns_ok(self):
        result = self._request("SEND echo hi")
        self.assertEqual(result, "OK")

    def test_unknown_command_returns_empty(self):
        result = self._request("BOGUS")
        self.assertEqual(result, "")

    def test_send_to_a_dead_session_returns_err_not_ok(self):
        """The regression this whole ERR path exists for (2026-07-25): the
        handler used to write "OK" without looking at either send-keys
        return code, so a tmux session that had died or been renamed on
        mandark was indistinguishable, from potato, from one that took the
        message. Its own server on its own port so nothing here can
        disturb the shared session the other tests type into."""
        dead = bridge.Server(("127.0.0.1", TEST_PORT + 1), bridge.Handler)
        dead.session = "crt-test-session-that-does-not-exist"
        t = threading.Thread(target=dead.serve_forever, daemon=True)
        t.start()
        time.sleep(0.2)
        try:
            with socket.create_connection(("127.0.0.1", TEST_PORT + 1), timeout=5) as s:
                s.sendall(b"SEND echo nope\n")
                s.shutdown(socket.SHUT_WR)
                out = b""
                while True:
                    chunk = s.recv(65536)
                    if not chunk:
                        break
                    out += chunk
        finally:
            dead.shutdown()
            dead.server_close()
        result = out.decode("utf-8", errors="replace")
        self.assertTrue(result.startswith("ERR "), repr(result))
        self.assertNotEqual(result, "OK")

    def test_send_to_a_dead_session_reports_tmux_own_reason(self):
        """ERR is only useful if it carries why -- an ERR with an empty
        detail would just be a quieter silence in the log."""
        ok, detail = bridge.send_to_claude("crt-test-session-that-does-not-exist", "hi")
        self.assertFalse(ok)
        self.assertTrue(detail.strip(), "ERR detail must not be empty")

    def test_send_to_a_live_session_reports_ok_with_no_detail(self):
        ok, detail = bridge.send_to_claude(TEST_SESSION, "echo live")
        self.assertTrue(ok)
        self.assertEqual(detail, "")


if __name__ == "__main__":
    unittest.main()
