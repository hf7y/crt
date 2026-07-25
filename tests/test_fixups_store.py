#!/usr/bin/env python3
# Two writers, one file, and no lock (2026-07-25, twelfth nightly cycle).
#
# stt-fixups.json has two writers -- crt-calibration-game.py (a human
# confirming a mishear by ear) and crt-stt-training-merge.py's `stttrain`
# window (unattended, every 600s) -- and since 24a94ac they agree on which
# file that is. Both did read-modify-write-whole-file through a temp path
# named `<file>.tmp`. The same one.
#
# Two things follow. A TORN FILE: open(tmp, "w") truncates, so a merge tick
# landing inside a calibration save can truncate that save's half-written
# temp and put the wreckage where the real file was -- destroying every
# hand-authored "confirmed" entry, which this project can only re-earn by
# someone standing at the mic. And a LOST UPDATE: each writer computes from
# a snapshot and writes the whole file, so the later write silently drops
# whatever the earlier one added.
#
# The concurrency tests here use real processes and real threads, because
# the defect is in what two of them do to one file -- an assertion about
# the source string would be the "grep proves it" shape ad41f5a called out.
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN_DIR = os.path.join(REPO, "bin")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, os.path.join(BIN_DIR, path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


store = _load("crt_fixups_store", "crt_fixups_store.py")


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "stt-fixups.json")

    def write(self, data):
        with open(self.path, "w") as f:
            json.dump(data, f)

    def read_raw(self):
        with open(self.path) as f:
            return f.read()


class TestRead(StoreTestCase):
    def test_missing_file_is_empty_not_a_raise(self):
        self.assertEqual(store.read(self.path), {})

    def test_malformed_file_is_empty_not_a_raise(self):
        with open(self.path, "w") as f:
            f.write("{ this is not json")
        self.assertEqual(store.read(self.path), {})

    def test_a_json_document_that_is_not_an_object_is_empty(self):
        with open(self.path, "w") as f:
            f.write('["potato"]')
        self.assertEqual(store.read(self.path), {})


class TestUpdate(StoreTestCase):
    def test_mutate_sees_the_current_file_and_the_result_is_written(self):
        self.write({"a": {"intent": "claude"}})
        seen = {}

        def mutate(current):
            seen.update(current)
            current["b"] = {"intent": "claude"}
            return current

        store.update(self.path, mutate)
        self.assertEqual(seen, {"a": {"intent": "claude"}})
        self.assertEqual(set(store.read(self.path)), {"a", "b"})

    def test_returning_none_writes_nothing_and_leaves_no_temp(self):
        self.write({"a": {"intent": "claude"}})
        before = self.read_raw()
        self.assertIsNone(store.update(self.path, lambda cur: None))
        self.assertEqual(self.read_raw(), before)
        self.assertEqual([n for n in os.listdir(os.path.dirname(self.path))
                          if ".tmp" in n], [])

    def test_the_temp_path_carries_the_pid(self):
        # The whole fix: `<file>.tmp` was one name shared by every process
        # that ever wrote this file, so two writers truncated each other's
        # half-finished temp.
        seen = []
        real_replace = os.replace

        def spy(src, dst):
            seen.append(src)
            return real_replace(src, dst)

        os.replace = spy
        try:
            store.update(self.path, lambda cur: {"a": {"intent": "claude"}})
        finally:
            os.replace = real_replace
        self.assertEqual(len(seen), 1)
        self.assertTrue(seen[0].endswith(".%d.tmp" % os.getpid()), seen[0])

    def test_a_failed_write_leaves_no_stray_temp_and_still_raises(self):
        self.write({"a": {"intent": "claude"}})
        real_replace = os.replace

        def boom(src, dst):
            raise OSError("no space left on device")

        os.replace = boom
        try:
            with self.assertRaises(OSError):
                store.update(self.path, lambda cur: {"b": {"intent": "claude"}})
        finally:
            os.replace = real_replace
        strays = [n for n in os.listdir(os.path.dirname(self.path)) if ".tmp" in n]
        self.assertEqual(strays, [])
        # The old file is still intact -- that is what the temp is for.
        self.assertEqual(set(store.read(self.path)), {"a"})

    def test_the_on_disk_format_matches_what_the_file_is_committed_as(self):
        store.update(self.path, lambda cur: {"b": {"intent": "claude"},
                                             "a": {"intent": "claude"}})
        text = self.read_raw()
        self.assertTrue(text.endswith("}\n"))
        self.assertIn('\n  "a"', text)                 # indent 2, not 4
        self.assertLess(text.index('"a"'), text.index('"b"'))   # sorted


class TestConcurrentWriters(StoreTestCase):
    """The actual defect. Both of these fail against the parent's
    unlocked read-then-write-whole-file shape."""

    def test_no_update_is_lost_when_many_writers_interleave(self):
        # Each thread adds its own key. Whole-file writes from stale
        # snapshots lose all but the last; a locked read-modify-write keeps
        # every one.
        self.write({})
        n = 12
        errors = []

        def writer(i):
            def add(current):
                time.sleep(0.002)          # widen the window a real one has
                current["w%02d" % i] = {"intent": "claude"}
                return current
            try:
                store.update(self.path, add)
            except Exception as e:          # noqa: BLE001 - reported, not swallowed
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(store.read(self.path)), n)

    def test_the_file_is_never_torn_by_two_processes(self):
        # Separate PROCESSES, not threads: the flock is what makes this hold
        # across them, and a torn file is what the shared `<file>.tmp` name
        # produced. A reader polling throughout must never see a file that
        # exists but does not parse.
        self.write({})
        script = (
            "import importlib.util, sys, time\n"
            "spec = importlib.util.spec_from_file_location('s', %r)\n"
            "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
            "tag = sys.argv[1]\n"
            "for i in range(25):\n"
            "    m.update(%r, lambda cur, i=i: dict(cur, **{tag + str(i): {'intent': 'claude', 'pad': 'x' * 4000}}))\n"
            % (os.path.join(BIN_DIR, "crt_fixups_store.py"), self.path)
        )
        procs = [subprocess.Popen([sys.executable, "-c", script, tag])
                 for tag in ("a", "b", "c")]
        torn = []
        while any(p.poll() is None for p in procs):
            try:
                with open(self.path) as f:
                    json.load(f)
            except ValueError:
                torn.append(True)
            except OSError:
                pass
        for p in procs:
            self.assertEqual(p.wait(), 0)
        self.assertEqual(torn, [])
        self.assertEqual(len(store.read(self.path)), 75)
        strays = [n for n in os.listdir(os.path.dirname(self.path)) if n.endswith(".tmp")]
        self.assertEqual(strays, [])


if __name__ == "__main__":
    unittest.main()
