#!/usr/bin/env python3
# Tests for bin/crt_config.py's fixups_path(), and for the three scripts
# that used to resolve bin/stt-fixups.json for themselves.
#
# The defect: crt-stt-solo.py (the wake gate, the only READER) and
#   [rest: vault:crt/header-archaeology-20260817.md]
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


class TestEnvNumber(unittest.TestCase):
    """env_number, the second thing crt_config.py holds (2026-07-25). Every
    tunable in bin/ arrives from crt-console.sh as shell text, and a bare
    float() of a typo raises at import -- before the window draws anything."""

    def n(self, raw, default=8.0, **kw):
        return cfg.env_number("X", default, env={} if raw is None else {"X": raw}, **kw)

    def test_unset_is_the_default(self):
        self.assertEqual(self.n(None), 8.0)

    def test_a_real_number_is_used(self):
        self.assertEqual(self.n("2.5"), 2.5)

    def test_a_typo_falls_back_instead_of_raising(self):
        for raw in ("eight", "3min", "8s", "", "  "):
            with self.subTest(raw=raw):
                self.assertEqual(self.n(raw), 8.0)

    def test_zero_is_honoured_as_the_disable_hatch(self):
        self.assertEqual(self.n("0"), 0.0)

    def test_negative_is_junk(self):
        self.assertEqual(self.n("-1"), 8.0)

    def test_a_positive_floor_rejects_zero(self):
        """For a poll interval, 0 is not an escape hatch -- it is a hot
        while-True on the box that also runs the sole mic reader."""
        self.assertEqual(self.n("0", minimum=0.1), 8.0)
        self.assertEqual(self.n("0.5", minimum=0.1), 0.5)


class TestEnvFlag(unittest.TestCase):
    def f(self, raw, default=False):
        return cfg.env_flag("X", default, env={} if raw is None else {"X": raw})

    def test_unset_is_the_default(self):
        self.assertFalse(self.f(None))
        self.assertTrue(self.f(None, default=True))

    def test_the_words_a_person_actually_types(self):
        for raw in ("1", "true", "TRUE", "yes", "on", " True "):
            with self.subTest(raw=raw):
                self.assertTrue(self.f(raw))
        for raw in ("0", "false", "no", "off", "Off"):
            with self.subTest(raw=raw):
                self.assertFalse(self.f(raw, default=True))

    def test_anything_else_is_the_default_not_an_exception(self):
        for raw in ("maybe", "", "2"):
            with self.subTest(raw=raw):
                self.assertFalse(self.f(raw))
                self.assertTrue(self.f(raw, default=True))


class TestATypoDoesNotTakeAWindowDown(unittest.TestCase):
    """The failure this helper exists for, asserted where it actually
    happens: crt-console.sh wraps each window in `; exec bash`, so a module
    that raises at import does not close its window -- it leaves a bash prompt
    where the console's face used to be, with nothing anywhere saying why.

    Each of these imports the real module with a value a person could
    plausibly type, and asserts both that the import survives and that the
    tunable came out at its documented default. Against the parent commit the
    idle-bait and loop-guard cases raise ValueError out of exec_module."""

    JUNK = {
        "CRT_BOOK_IDLE_BAIT_SECS": "3min",
        "CRT_BOOK_IDLE_BAIT_POLL": "ten",
        "CRT_BOOK_ENTICE_RATE": "40%",
        "CRT_BOOK_IDLE_ROTATE_SECS": "eight",
        "CRT_BOOK_CONSOLE_IDLE_SECS": "20s",
        "CRT_SCREENSAVER_CAPTION_MOVE_SECS": "8sec",
        "CRT_SCREENSAVER_INTERVAL": "two and a half",
        "CRT_LOOP_GUARD_TRACEBACK": "true",
    }

    def test_the_idle_bait_window_still_loads_at_its_defaults(self):
        mod = _load("crt_book_idle_bait_junk", "crt-book-idle-bait.py", self.JUNK)
        self.assertEqual((mod.IDLE_SECS, mod.POLL_SECS, mod.ENTICE_RATE),
                         (180.0, 10.0, 0.4))

    def test_the_book_window_still_loads_at_its_defaults(self):
        mod = _load("crt_book_console_junk", "crt-book-console.py", self.JUNK)
        # 20.0 -> 35.0, 2026-07-28 (see crt-book-console.py's own comment
        # on IDLE_SECS: "need more of a delay between question and
        # answer" for the now-real, thought-requiring AI-enriched
        # questions).
        self.assertEqual((mod.IDLE_SECS, mod.IDLE_ROTATE_SECS), (35.0, 8.0))

    def test_the_idle_face_still_loads_at_its_defaults(self):
        mod = _load("crt_screensaver_junk", "crt-screensaver.py", self.JUNK)
        self.assertEqual(mod._env_secs("CRT_SCREENSAVER_INTERVAL", 2.5), 2.5)
        self.assertEqual(mod._env_secs("CRT_SCREENSAVER_CAPTION_MOVE_SECS", 8.0), 8.0)

    def test_the_guard_that_keeps_windows_alive_does_not_kill_four_of_them(self):
        """CRT_LOOP_GUARD_TRACEBACK is a debugging switch someone sets by
        hand while chasing a window that keeps dying. `int('true')` raised in
        LoopGuard's constructor -- which book, bookanswer, bookidle and
        stttrain all call before their loops start."""
        mod = _load("crt_loop_guard_junk", "crt_loop_guard.py", self.JUNK)
        with mock.patch.dict(os.environ, self.JUNK, clear=False):
            self.assertTrue(mod.LoopGuard("book").verbose)
        with mock.patch.dict(os.environ, {"CRT_LOOP_GUARD_TRACEBACK": "wat"}, clear=False):
            self.assertFalse(mod.LoopGuard("book").verbose)

    def test_the_two_private_copies_are_gone(self):
        """crt-book-console.py and crt-screensaver.py each held a
        byte-for-byte copy of this helper, docstring included, and the third
        window needed a third. Both now re-export the one in crt_config."""
        book = _load("crt_book_console_shared", "crt-book-console.py")
        saver = _load("crt_screensaver_shared", "crt-screensaver.py")
        # Not assertIs: each module loads its own crt_config module object
        # through spec_from_file_location, so the function objects differ by
        # identity while being the same function. Name plus source is the
        # claim that actually matters -- it came from crt_config.py.
        for mod in (book, saver):
            with self.subTest(mod=mod.__name__):
                self.assertEqual(mod._env_secs.__qualname__, "env_number")
                self.assertEqual(mod._env_secs.__module__, mod.crt_config.__name__)
        for filename in ("crt-book-console.py", "crt-screensaver.py"):
            with self.subTest(filename=filename), \
                    open(os.path.join(BIN_DIR, filename)) as f:
                # Boolean, not assertNotIn: a failure here would otherwise
                # print the entire source file as the mismatch context.
                self.assertFalse(any(ln.startswith("def _env_secs") for ln in f),
                                 "%s still defines its own _env_secs" % filename)


if __name__ == "__main__":
    unittest.main(verbosity=2)
