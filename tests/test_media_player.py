#!/usr/bin/env python3
# Tests for bin/crt-media-player.py -- PARKING-LOT.md's "play media" job.
# No audio hardware, no real cvlc/mpv -- FakeBackend records calls,
# VlcBackend is only exercised for its OSError-swallowing behavior.
import importlib.util
import os
import tempfile
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")
spec = importlib.util.spec_from_file_location("crt_media_player", os.path.join(BIN_DIR, "crt-media-player.py"))
mp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mp)


class TestParseMediaCommand(unittest.TestCase):
    def test_play_with_query(self):
        self.assertEqual(mp.parse_media_command("play some jazz"),
                          {"action": "play", "query": "some jazz"})

    def test_play_the_prefix(self):
        self.assertEqual(mp.parse_media_command("play the beatles"),
                          {"action": "play", "query": "beatles"})

    def test_put_on_prefix(self):
        self.assertEqual(mp.parse_media_command("put on some music"),
                          {"action": "play", "query": "some music"})

    def test_bare_play_with_no_query_is_not_a_command(self):
        self.assertIsNone(mp.parse_media_command("play"))

    def test_control_words(self):
        self.assertEqual(mp.parse_media_command("pause"), {"action": "pause", "query": None})
        self.assertEqual(mp.parse_media_command("resume"), {"action": "resume", "query": None})
        self.assertEqual(mp.parse_media_command("skip"), {"action": "next", "query": None})
        self.assertEqual(mp.parse_media_command("stop"), {"action": "stop", "query": None})

    def test_bare_next_deliberately_not_a_trigger(self):
        # 2026-07-21: bare "next" is claimed by crt-stt-solo.py's own
        # CONTROL dict (-> Down arrow) for single-word utterances -- this
        # playbook would never even see it in CRT_STT_SINK=secretary mode,
        # so it's deliberately NOT registered here; "skip"/"next song"/
        # "next track" are the reachable equivalents instead.
        self.assertIsNone(mp.parse_media_command("next"))

    def test_next_phrasing_does_not_get_captured_as_a_play_query(self):
        # "play the next one" must resolve to next, not play(query="the next one").
        self.assertEqual(mp.parse_media_command("play the next one"), {"action": "next", "query": None})

    def test_unrelated_speech_returns_none(self):
        self.assertIsNone(mp.parse_media_command("what time is it"))
        self.assertIsNone(mp.parse_media_command(""))

    def test_case_insensitive(self):
        self.assertEqual(mp.parse_media_command("PAUSE"), {"action": "pause", "query": None})


class TestHandleMediaCommandWithFakeBackend(unittest.TestCase):
    def setUp(self):
        self.backend = mp.FakeBackend()

    def test_play_dispatches_and_confirms(self):
        result = mp.handle_media_command("play some jazz", self.backend)
        self.assertEqual(result, "playing some jazz.")
        self.assertEqual(self.backend.calls, [("play", "some jazz")])

    def test_pause_dispatches(self):
        mp.handle_media_command("pause", self.backend)
        self.assertEqual(self.backend.calls, [("pause", None)])

    def test_resume_dispatches(self):
        mp.handle_media_command("resume", self.backend)
        self.assertEqual(self.backend.calls, [("resume", None)])

    def test_next_dispatches(self):
        mp.handle_media_command("skip", self.backend)
        self.assertEqual(self.backend.calls, [("next", None)])

    def test_stop_dispatches(self):
        mp.handle_media_command("stop", self.backend)
        self.assertEqual(self.backend.calls, [("stop", None)])

    def test_non_media_text_returns_none_and_calls_nothing(self):
        result = mp.handle_media_command("what's the weather", self.backend)
        self.assertIsNone(result)
        self.assertEqual(self.backend.calls, [])


class TestVlcBackendNeverRaises(unittest.TestCase):
    def test_play_missing_library_dir_returns_false_not_raise(self):
        backend = mp.VlcBackend(library_dir="/nonexistent/dir")
        self.assertFalse(backend.play("anything"))

    def test_play_finds_file_by_substring(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "some_jazz_track.mp3"), "w").close()
            backend = mp.VlcBackend(library_dir=d)
            found = backend._find_file("jazz")
            self.assertIsNotNone(found)
            self.assertTrue(found.endswith("some_jazz_track.mp3"))

    def test_control_methods_swallow_missing_binary(self):
        backend = mp.VlcBackend(library_dir="/nonexistent/dir")
        # cvlc-control isn't a real binary -- these must not raise.
        self.assertFalse(backend.pause())
        self.assertFalse(backend.resume())
        self.assertFalse(backend.next())
        self.assertFalse(backend.stop())


if __name__ == "__main__":
    unittest.main()
