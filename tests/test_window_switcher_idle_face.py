#!/usr/bin/env python3
# Regression test (2026-07-28): crt-window-switcher.py always targeted
# `book` on Claude-idle, even under the idle-lean layout where the real
# resting state is the screensaver (CRT_IDLE_FACE_WINDOW, same var
# crt-book-console.py already reads) -- landing on `book` left the
#   [rest: vault:crt/header-archaeology-20260817.md]
import os
import subprocess
import sys
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")
MODULE_PATH = os.path.join(BIN_DIR, "crt-window-switcher.py")

PROBE = (
    "import importlib.util\n"
    "spec = importlib.util.spec_from_file_location('m', %r)\n"
    "m = importlib.util.module_from_spec(spec)\n"
    "spec.loader.exec_module(m)\n"
    "print(m.RETURN_WINDOW)\n"
) % MODULE_PATH


def run_with_env(extra_env):
    env = dict(os.environ)
    env.pop("CRT_IDLE_FACE_WINDOW", None)
    env.pop("CRT_BOOK_WINDOW_NAME", None)
    env.update(extra_env)
    r = subprocess.run([sys.executable, "-c", PROBE], capture_output=True,
                       text=True, env=env, timeout=30)
    return r.stdout.strip()


class TestReturnWindowTarget(unittest.TestCase):
    def test_defaults_to_book_when_no_idle_face_configured(self):
        self.assertEqual(run_with_env({}), "book")

    def test_targets_idle_face_when_configured(self):
        self.assertEqual(run_with_env({"CRT_IDLE_FACE_WINDOW": "0"}), "0")

    def test_idle_face_wins_over_a_custom_book_window_name(self):
        self.assertEqual(
            run_with_env({"CRT_IDLE_FACE_WINDOW": "0",
                          "CRT_BOOK_WINDOW_NAME": "custom-book"}),
            "0")

    def test_falls_back_to_custom_book_window_name_without_idle_face(self):
        self.assertEqual(
            run_with_env({"CRT_BOOK_WINDOW_NAME": "custom-book"}),
            "custom-book")


if __name__ == "__main__":
    unittest.main()
