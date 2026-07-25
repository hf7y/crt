#!/usr/bin/env python3
# The wake gate has to see stt-fixups.json as it is NOW, not as it was at
# boot (2026-07-25, tenth nightly cycle).
#
# Three things write that file while the console is up: the `stttrain`
# window (crt-stt-training-merge.py --loop), crt-calibration-game.py's wake
# round (a live human confirming a mishear by ear), and a person with an
# editor. Its only consumer -- crt-stt-solo.py's addressed_to_console() --
# read it once at import and bound the result as a DEFAULT ARGUMENT, so on
# a console that stays up for days none of those three ever changed what
# the gate does.
#
# Every test here loads the real crt-stt-solo.py with CRT_STT_FIXUPS
# pointed at a temp file and then changes that file, because the defect was
# in the module-level wiring, not in a function that could be handed a
# dict. All of them pass trivially against a snapshot taken at import only
# if the snapshot happens to be right; the first four fail against it.
import importlib.util
import json
import os
import tempfile
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")
SOLO_PATH = os.path.join(BIN_DIR, "crt-stt-solo.py")


def load_solo(fixups_path):
    """A fresh crt-stt-solo module whose FIXUPS_PATH is `fixups_path`."""
    old = os.environ.get("CRT_STT_FIXUPS")
    os.environ["CRT_STT_FIXUPS"] = fixups_path
    try:
        spec = importlib.util.spec_from_file_location("crt_stt_solo_reload", SOLO_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        if old is None:
            os.environ.pop("CRT_STT_FIXUPS", None)
        else:
            os.environ["CRT_STT_FIXUPS"] = old


def write_fixups(path, data):
    """Land the file the way crt-stt-training-merge.py does -- a new inode
    every time, so the test never races the filesystem's mtime resolution."""
    tmp = path + ".test-tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    os.replace(tmp, path)


class FixupsTempFile(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "stt-fixups.json")
        self.addCleanup(self.dir.cleanup)


class TestGateSeesLaterWrites(FixupsTempFile):
    def test_alias_added_after_boot_opens_the_gate(self):
        # The whole defect, in one case: the calibration game confirms
        # "greydog" is how this room's mic hears the wake word, writes it,
        # and the person says it into the same live process.
        write_fixups(self.path, {"_comment": "doc key", "slide": {"intent": "claude"}})
        solo = load_solo(self.path)
        self.assertFalse(solo.addressed_to_console("greydog are you there"))

        write_fixups(self.path, {"_comment": "doc key",
                                 "slide": {"intent": "claude"},
                                 "greydog": {"intent": "claude", "confidence": "confirmed"}})
        self.assertTrue(solo.addressed_to_console("greydog are you there"))
        self.assertTrue(solo.addressed_to_console("slide over here"))

    def test_alias_removed_after_boot_closes_the_gate(self):
        # The other direction matters just as much: a human deleting a
        # false-positive alias ("slide" firing on ordinary room talk) is
        # asking for it to stop working, and waiting for a reboot is not
        # an answer they can see.
        write_fixups(self.path, {"slide": {"intent": "claude"}})
        solo = load_solo(self.path)
        self.assertTrue(solo.addressed_to_console("slide over here"))

        write_fixups(self.path, {})
        self.assertFalse(solo.addressed_to_console("slide over here"))
        self.assertTrue(solo.addressed_to_console("claude are you there"))

    def test_classify_wake_match_sees_the_same_file(self):
        # The arm window asks WHICH word opened the gate. If it read an
        # older set than the gate did, an utterance could get through and
        # then be classified as no-match -- the sticky window would never
        # arm on exactly the alias that just worked.
        write_fixups(self.path, {})
        solo = load_solo(self.path)
        self.assertEqual(solo.classify_wake_match("greydog hello")[0], None)

        write_fixups(self.path, {"greydog": {"intent": "claude"}})
        kind, _, word = solo.classify_wake_match("greydog hello")
        self.assertEqual(kind, "exact")
        self.assertEqual(word, "greydog")
        self.assertTrue(solo.addressed_to_console("greydog hello"))

    def test_a_file_that_appears_later_is_picked_up(self):
        # Missing at boot is not permanent: the file lives in bin/ next to
        # the script, and a fresh checkout/deploy can land it a moment
        # after the console starts.
        solo = load_solo(self.path)
        self.assertFalse(solo.addressed_to_console("greydog hello"))
        write_fixups(self.path, {"greydog": {"intent": "claude"}})
        self.assertTrue(solo.addressed_to_console("greydog hello"))

    def test_explicit_fixups_argument_still_wins(self):
        write_fixups(self.path, {"greydog": {"intent": "claude"}})
        solo = load_solo(self.path)
        self.assertFalse(
            solo.addressed_to_console("greydog hello", fixups={"other": {"intent": "claude"}}))
        self.assertTrue(
            solo.addressed_to_console("other hello", fixups={"other": {"intent": "claude"}}))


class TestUnchangedFileIsNotReparsed(FixupsTempFile):
    def test_same_file_returns_the_same_object(self):
        # One os.stat per utterance is the budget; re-parsing JSON on every
        # utterance because nothing changed is not.
        write_fixups(self.path, {"slide": {"intent": "claude"}})
        solo = load_solo(self.path)
        store = solo.FixupsFile(self.path)
        first = store.current()
        self.assertIs(store.current(), first)
        self.assertIs(store.current(), first)


class TestBadFileKeepsTheLastGoodSet(FixupsTempFile):
    def setUp(self):
        super().setUp()
        write_fixups(self.path, {"slide": {"intent": "claude"}})
        self.solo = load_solo(self.path)
        self.errors = []
        self.changes = []
        self.store = self.solo.FixupsFile(self.path,
                                          on_change=self.changes.append,
                                          on_error=self.errors.append)

    def test_malformed_after_a_good_load_keeps_the_aliases(self):
        self.assertIn("slide", self.store.current())
        with open(self.path, "w") as f:
            f.write("{ this is not json")
        self.assertIn("slide", self.store.current())
        self.assertTrue(self.solo.addressed_to_console("slide over here",
                                                       fixups=self.store.current()))

    def test_malformed_reports_once_not_once_per_utterance(self):
        self.store.current()
        with open(self.path, "w") as f:
            f.write("{ this is not json")
        for _ in range(5):
            self.store.current()
        self.assertEqual(len(self.errors), 1, self.errors)
        self.assertIn("keeping the 1 I already had", self.errors[0])

    def test_repaired_file_reloads_and_says_so(self):
        self.store.current()
        with open(self.path, "w") as f:
            f.write("{ this is not json")
        self.store.current()
        write_fixups(self.path, {"slide": {"intent": "claude"},
                                 "greydog": {"intent": "claude"}})
        self.assertIn("greydog", self.store.current())
        self.assertEqual(len(self.changes), 1, self.changes)
        self.assertIn("greydog", self.changes[0])

    def test_deleted_file_keeps_the_aliases(self):
        self.store.current()
        os.remove(self.path)
        self.assertIn("slide", self.store.current())
        self.assertEqual(len(self.errors), 1, self.errors)

    def test_first_load_is_not_announced_as_a_change(self):
        # Boot is the baseline, not news. A line on window 1 every restart
        # saying "fixups reloaded" would be noise that teaches the room to
        # ignore that tag.
        self.store.current()
        self.assertEqual(self.changes, [])


class TestReportWording(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("crt_stt_solo_words", SOLO_PATH)
        self.solo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.solo)

    def test_names_only_the_entries_that_change_the_gate(self):
        line = self.solo.fixups_change_report(
            {"greydog": {"intent": "claude"}, "friction": {"intent": "fiction"}}, [])
        self.assertIn("+2", line)
        self.assertIn("greydog", line)
        # "friction" -> "fiction" is a Book Game answer mishear. Real data,
        # no effect on the gate -- naming it would imply otherwise.
        self.assertNotIn("friction", line)

    def test_caps_the_named_list_for_a_40_column_screen(self):
        added = {("alias%d" % i): {"intent": "claude"} for i in range(9)}
        line = self.solo.fixups_change_report(added, [])
        self.assertIn("+6 more", line)
        self.assertLess(len(line), 80)

    def test_removals_are_reported_too(self):
        line = self.solo.fixups_change_report({}, ["slide", "gload"])
        self.assertIn("-2", line)

    def test_error_line_distinguishes_stale_from_empty(self):
        stale = self.solo.fixups_error_report(ValueError("boom"), {"slide": {}})
        empty = self.solo.fixups_error_report(ValueError("boom"), {})
        self.assertIn("keeping", stale)
        self.assertNotIn("keeping", empty)
        self.assertIn("exact", empty)


class TestCalibrationGameWritesAtomically(FixupsTempFile):
    def setUp(self):
        super().setUp()
        spec = importlib.util.spec_from_file_location(
            "crt_calibration_game", os.path.join(BIN_DIR, "crt-calibration-game.py"))
        self.game = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.game)

    def test_a_failed_write_does_not_destroy_the_existing_file(self):
        # open(path, "w") truncates before anything is written. This file
        # holds human-confirmed judgments that cannot be re-derived, and it
        # is tracked in git -- a crash mid-dump used to take all of them.
        write_fixups(self.path, {"slide": {"intent": "claude"}})
        real_replace = os.replace

        def boom(src, dst):
            raise OSError("no space left on device")

        os.replace = boom
        try:
            with self.assertRaises(OSError):
                self.game.save_fixup("greydog", "claude", 0.8, self.path)
        finally:
            os.replace = real_replace
        with open(self.path) as f:
            self.assertEqual(json.load(f), {"slide": {"intent": "claude"}})

    def test_a_good_write_lands_and_leaves_no_temp_file(self):
        self.game.save_fixup("greydog", "claude", 0.8, self.path)
        with open(self.path) as f:
            saved = json.load(f)
        self.assertEqual(saved["greydog"]["intent"], "claude")
        self.assertEqual(saved["greydog"]["confidence"], "confirmed")
        self.assertEqual([n for n in os.listdir(os.path.dirname(self.path))
                          if ".tmp" in n], [])

    def test_a_save_keeps_every_entry_that_was_already_there(self):
        # save_fixups(data, path) took the whole dict from a caller holding
        # a snapshot; save_fixup() reads inside the store's lock, so nothing
        # written between the human's decision and their save is lost.
        write_fixups(self.path, {"_comment": "keep me",
                                 "read about": {"intent": "ring the bell"}})
        self.game.save_fixup("greydog", "claude", 0.8, self.path)
        with open(self.path) as f:
            saved = json.load(f)
        self.assertEqual(set(saved), {"_comment", "read about", "greydog"})

    def test_the_gate_sees_what_the_game_just_saved(self):
        # End to end, the loop this cycle closed: a human confirms a
        # mishear in the game, the running engine honours it.
        write_fixups(self.path, {})
        solo = load_solo(self.path)
        self.assertFalse(solo.addressed_to_console("greydog hello"))
        self.game.save_fixup("greydog", "claude", 0.8, self.path)
        self.assertTrue(solo.addressed_to_console("greydog hello"))


if __name__ == "__main__":
    unittest.main()
