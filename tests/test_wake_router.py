#!/usr/bin/env python3
# Offline tests for bin/crt-wake-router.py -- the pure decision core plus
# the env-driven CLI. No sockets are opened (we use --no-probe / forced
# env), so this runs anywhere.
import os
import subprocess
import sys
import unittest

BIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")
sys.path.insert(0, BIN)
import importlib.util

spec = importlib.util.spec_from_file_location("wake_router",
                                              os.path.join(BIN, "crt-wake-router.py"))
wr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wr)


class TestDecideCore(unittest.TestCase):
    def test_mandark_on_reachable_is_remote(self):
        self.assertEqual(wr.decide_brain(True, True, True), wr.REMOTE)
        self.assertEqual(wr.decide_brain(True, True, False), wr.REMOTE)

    def test_mandark_on_but_down_falls_back_local(self):
        self.assertEqual(wr.decide_brain(True, False, True), wr.LOCAL)

    def test_mandark_on_but_down_no_local_is_none(self):
        self.assertEqual(wr.decide_brain(True, False, False), wr.NONE)

    def test_mandark_off_uses_local_when_available(self):
        self.assertEqual(wr.decide_brain(False, False, True), wr.LOCAL)

    def test_mandark_off_no_local_is_none(self):
        self.assertEqual(wr.decide_brain(False, False, False), wr.NONE)

    def test_every_choice_has_an_explanation(self):
        for choice in (wr.REMOTE, wr.LOCAL, wr.NONE):
            self.assertTrue(wr.explain(choice))


class TestConfigured(unittest.TestCase):
    def _on(self, val):
        old = os.environ.get("CRT_CLAUDE_REMOTE_PORT")
        os.environ["CRT_CLAUDE_REMOTE_PORT"] = val
        try:
            return wr.mandark_configured_on()
        finally:
            if old is None:
                os.environ.pop("CRT_CLAUDE_REMOTE_PORT", None)
            else:
                os.environ["CRT_CLAUDE_REMOTE_PORT"] = old

    def test_real_port_is_on(self):
        on, port = self._on("8993")
        self.assertTrue(on)
        self.assertEqual(port, 8993)

    def test_zero_is_off(self):
        on, _ = self._on("0")
        self.assertFalse(on)

    def test_garbage_is_off(self):
        on, _ = self._on("nope")
        self.assertFalse(on)


class TestCli(unittest.TestCase):
    def _run(self, env):
        e = dict(os.environ)
        e.update(env)
        r = subprocess.run([sys.executable, os.path.join(BIN, "crt-wake-router.py"),
                            "--json", "--no-probe"],
                           capture_output=True, text=True, env=e)
        self.assertEqual(r.returncode, 0, r.stderr)
        import json
        return json.loads(r.stdout)

    def test_off_with_local_is_local(self):
        out = self._run({"CRT_CLAUDE_REMOTE_PORT": "0", "CRT_LOCAL_CLAUDE": "1"})
        self.assertEqual(out["choice"], "local")

    def test_on_but_noprobe_falls_back(self):
        # --no-probe forces unreachable; with no local -> none.
        out = self._run({"CRT_CLAUDE_REMOTE_PORT": "8993", "CRT_LOCAL_CLAUDE": "0"})
        self.assertEqual(out["choice"], "none")
        self.assertTrue(out["mandark_on"])
        self.assertFalse(out["mandark_reachable"])


if __name__ == "__main__":
    unittest.main()
