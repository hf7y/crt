#!/usr/bin/env python3
# Tests for bin/crt_config.py's fixups_path(), and for the three scripts
# that used to resolve bin/stt-fixups.json for themselves.
#
# The defect: crt-stt-solo.py (the wake gate, the only READER) and
# crt-calibration-game.py read CRT_STT_FIXUPS; crt-stt-training-merge.py
# read CRT_STT_FIXUPS_PATH. Same default, so nothing looks wrong -- until
# someone sets one, at which point a writer and the reader are pointed at
# different files and every surface still says it worked.
import importlib.util
import os
import unittest
from unittest import mock

BIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")


def _load(name, filename, env=None):
    spec = importlib.util.spec_from_file_location(name, os.path.join(BIN_DIR, filename))
    mod = importlib.util.module_from_spec(spec)
    if env is None:
        spec.loader.exec_module(mod)
        return mod
    with mock.patch.dict(os.environ, env, clear=False):
        spec.loader.exec_module(mod)
    return mod


cfg = _load("crt_config", "crt_config.py")


class TestFixupsPath(unittest.TestCase):
    def test_default_is_next_to_the_scripts(self):
        self.assertEqual(cfg.fixups_path(env={}),
                         os.path.join(BIN_DIR, "stt-fixups.json"))

    def test_canonical_name_wins_when_only_it_is_set(self):
        self.assertEqual(cfg.fixups_path(env={"CRT_STT_FIXUPS": "/tmp/a.json"}), "/tmp/a.json")

    def test_legacy_name_is_still_honoured(self):
        # Retiring it would break any live env on potato that already sets
        # it, which this tier cannot see to check.
        self.assertEqual(cfg.fixups_path(env={"CRT_STT_FIXUPS_PATH": "/tmp/b.json"}), "/tmp/b.json")

    def test_canonical_wins_over_legacy(self):
        got = cfg.fixups_path(env={"CRT_STT_FIXUPS": "/tmp/a.json",
                                   "CRT_STT_FIXUPS_PATH": "/tmp/b.json"},
                              warn=lambda _line: None)
        self.assertEqual(got, "/tmp/a.json")

    def test_a_real_disagreement_is_reported(self):
        seen = []
        cfg.fixups_path(env={"CRT_STT_FIXUPS": "/tmp/a.json",
                             "CRT_STT_FIXUPS_PATH": "/tmp/b.json"},
                        warn=seen.append)
        self.assertEqual(len(seen), 1)
        self.assertIn("/tmp/a.json", seen[0])
        self.assertIn("/tmp/b.json", seen[0])

    def test_both_set_to_the_same_path_is_not_a_disagreement(self):
        seen = []
        got = cfg.fixups_path(env={"CRT_STT_FIXUPS": "/tmp/a.json",
                                   "CRT_STT_FIXUPS_PATH": "/tmp/a.json"},
                              warn=seen.append)
        self.assertEqual((got, seen), ("/tmp/a.json", []))

    def test_empty_string_is_not_a_setting(self):
        self.assertEqual(cfg.fixups_path(env={"CRT_STT_FIXUPS": ""}),
                         os.path.join(BIN_DIR, "stt-fixups.json"))

    def test_never_raises_on_conflict(self):
        # Called at import by crt-stt-solo.py: a config complaint must
        # never be why the STT engine fails to start.
        cfg.fixups_path(env={"CRT_STT_FIXUPS": "/a", "CRT_STT_FIXUPS_PATH": "/b"},
                        warn=lambda _line: None)


class TestAllThreeScriptsAgree(unittest.TestCase):
    """The point of the change: one env var, one file, for the reader and
    both writers. Each assertion below fails against the parent for one of
    the two spellings."""

    SCRIPTS = [
        ("crt_stt_solo_cfg", "crt-stt-solo.py"),                # reader: the wake gate
        ("crt_calibration_game_cfg", "crt-calibration-game.py"),  # writer: a human's ear
        ("crt_stt_training_merge_cfg", "crt-stt-training-merge.py"),  # writer: unattended
    ]

    def _paths_under(self, env):
        return [_load(name, filename, env).FIXUPS_PATH for name, filename in self.SCRIPTS]

    def test_canonical_spelling_moves_all_three(self):
        paths = self._paths_under({"CRT_STT_FIXUPS": "/tmp/canonical.json",
                                   "CRT_STT_FIXUPS_PATH": ""})
        self.assertEqual(paths, ["/tmp/canonical.json"] * 3)

    def test_legacy_spelling_moves_all_three(self):
        paths = self._paths_under({"CRT_STT_FIXUPS": "",
                                   "CRT_STT_FIXUPS_PATH": "/tmp/legacy.json"})
        self.assertEqual(paths, ["/tmp/legacy.json"] * 3)

    def test_they_agree_with_nothing_set(self):
        paths = self._paths_under({"CRT_STT_FIXUPS": "", "CRT_STT_FIXUPS_PATH": ""})
        self.assertEqual(paths, [os.path.join(BIN_DIR, "stt-fixups.json")] * 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
