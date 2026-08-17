#!/usr/bin/env python3
# Offline test: a console that cannot speak has to SAY SO somewhere a person
# will find it (2026-07-25).
#
# Two defects, one chain. bin/crt-tts.py's play_wav() discarded aplay's exit
#   [rest: vault:crt/header-archaeology-20260817.md]
import importlib.util
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

BIN_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))


def load(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(BIN_DIR, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def write_exe(path, body):
    with open(path, "w") as f:
        f.write("#!/bin/sh\n" + body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


class TestAplayErrorDetail(unittest.TestCase):
    """The pure half: the wording is testable without a broken sound card."""

    def setUp(self):
        self.tts = load("crt_tts_detail", "crt-tts.py")

    def test_reports_the_last_line_not_the_preamble(self):
        # aplay's real shape: a preamble that names no cause, then the cause.
        detail = self.tts.aplay_error_detail(
            "ALSA lib pcm.c:2660:(snd_pcm_open_noupdate) Unknown PCM plughw:9,0\n"
            "aplay: main:834: audio open error: No such file or directory\n")
        self.assertIn("No such file or directory", detail)

    def test_silent_failure_still_says_something_actionable(self):
        detail = self.tts.aplay_error_detail("")
        self.assertTrue(detail.strip())
        self.assertIn("aplay -l", detail)

    def test_detail_is_one_line(self):
        self.assertNotIn("\n", self.tts.aplay_error_detail("a\nb\nc\n"))


class TestPlayWavChecksAplay(unittest.TestCase):
    """play_wav()'s return value must mean 'this was audible', not 'a
    subprocess was launched'."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir, True)
        self.binstub = os.path.join(self.tmpdir, "bin")
        os.makedirs(self.binstub)
        self.wav = os.path.join(self.tmpdir, "x.wav")
        open(self.wav, "w").close()
        self.tts = load("crt_tts_play", "crt-tts.py")
        self.tts.CTL_FILE = os.path.join(self.tmpdir, "ctl")
        self.orig_path = os.environ["PATH"]
        os.environ["PATH"] = self.binstub + os.pathsep + self.orig_path
        self.addCleanup(os.environ.__setitem__, "PATH", self.orig_path)

    def _aplay(self, exit_code, stderr=""):
        write_exe(os.path.join(self.binstub, "aplay"),
                  ("printf '%s' >&2\n" % stderr) + "exit %d\n" % exit_code)

    def test_failed_aplay_is_not_a_successful_utterance(self):
        self._aplay(1, "aplay: main:834: audio open error: No such file or directory\\n")
        self.assertFalse(self.tts.play_wav(self.wav, "tv"))

    def test_successful_aplay_still_reports_success(self):
        self._aplay(0)
        self.assertTrue(self.tts.play_wav(self.wav, "tv"))

    def test_the_duck_is_still_released_when_playback_fails(self):
        # A failing handset playback must not leave capture muted -- that
        # would turn a dead speaker into a dead microphone as well.
        self._aplay(1)
        self.assertFalse(self.tts.play_wav(self.wav, "handset"))
        with open(self.tts.CTL_FILE) as f:
            self.assertEqual([l.strip() for l in f if l.strip()],
                             ["mute 1", "mute 0"])


class TestTtsCliExitStatus(unittest.TestCase):
    """End-to-end through crt-tts.py's real CLI, with a fake synthesizer and
    a fake sound card. The exit status is what every shell caller
    (crt-announce.sh, crt-stt-speakback.sh, crt-secretary.py) has to trust."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir, True)
        self.binstub = os.path.join(self.tmpdir, "bin")
        os.makedirs(self.binstub)
        # A synthesizer that really produces the wav file it was asked for.
        write_exe(os.path.join(self.binstub, "espeak-ng"), """
while [ $# -gt 0 ]; do
  if [ "$1" = "-w" ]; then shift; printf 'RIFFfake' > "$1"; fi
  shift
done
exit 0
""")
        self.env = dict(os.environ)
        self.env["PATH"] = self.binstub + os.pathsep + os.environ["PATH"]
        self.env["CRT_TTS_BACKEND"] = "espeak"
        self.env["CRT_CTL_FILE"] = os.path.join(self.tmpdir, "ctl")
        self.env["CRT_SIDEBAND_MUTE_FILE"] = os.path.join(self.tmpdir, "sideband.mute")
        self.env["CRT_TTS_CONF"] = os.path.join(self.tmpdir, "no-such.conf")

    def _run(self, aplay_exit, aplay_stderr=""):
        write_exe(os.path.join(self.binstub, "aplay"),
                  ("printf '%s' >&2\n" % aplay_stderr) + "exit %d\n" % aplay_exit)
        return subprocess.run(
            [sys.executable, os.path.join(BIN_DIR, "crt-tts.py"),
             "--device", "tv", "hello there"],
            capture_output=True, text=True, env=self.env, timeout=60)

    def test_dead_sound_card_exits_nonzero(self):
        r = self._run(1, "aplay: main:834: audio open error: Device or resource busy\\n")
        self.assertNotEqual(r.returncode, 0)

    def test_dead_sound_card_names_the_device_and_the_cause(self):
        r = self._run(1, "aplay: main:834: audio open error: Device or resource busy\\n")
        self.assertIn("PLAYED NOTHING", r.stderr)
        self.assertIn("Device or resource busy", r.stderr)
        # The device string is the single most useful fact for fixing this --
        # every audio bug this project has had was a wrong device name.
        self.assertIn("plughw:2,0", r.stderr)

    def test_a_working_sound_card_is_unchanged(self):
        r = self._run(0)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("PLAYED NOTHING", r.stderr)


class TestSecretarySurfacesUnspokenReplies(unittest.TestCase):
    """The secretary half. crt-tts.py exiting nonzero must reach a person:
    the words go to the tube, because a reply that cannot be heard is not
    thereby a reply that has to be lost."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir, True)
        self.fakebin = os.path.join(self.tmpdir, "bin")
        os.makedirs(self.fakebin)
        self.thoughts = os.path.join(self.tmpdir, "thoughts.log")
        # The real crt-think.sh -- the tube path is not faked, only the
        # synthesizer is.
        shutil.copy(os.path.join(BIN_DIR, "crt-think.sh"),
                    os.path.join(self.fakebin, "crt-think.sh"))
        os.environ["CRT_THOUGHT_LOG"] = self.thoughts
        self.addCleanup(os.environ.pop, "CRT_THOUGHT_LOG", None)
        self.sec = load("crt_secretary_speech", "crt-secretary.py")
        self.sec.BIN_DIR = self.fakebin

    def _tts(self, exit_code, stderr=""):
        # Written as PYTHON, not sh: speak() invokes it as `python3
        # crt-tts.py`, so a /bin/sh stub here would exit nonzero with a
        # SyntaxError and every failure assertion below would pass without
        # the code under test ever being reached. (It did, on the first run
        # of this file.)
        path = os.path.join(self.fakebin, "crt-tts.py")
        with open(path, "w") as f:
            f.write("import sys\n"
                    "sys.stderr.write(%r)\n"
                    "sys.exit(%d)\n" % (stderr, exit_code))

    def _tube(self):
        if not os.path.exists(self.thoughts):
            return []
        with open(self.thoughts) as f:
            return [l.strip() for l in f if l.strip()]

    def test_speak_reports_failure(self):
        self._tts(1, "[crt-tts] PLAYED NOTHING: aplay exited 1 on device plughw:1,0\n")
        self.assertFalse(self.sec.speak("the answer is 42"))

    def test_unspoken_words_reach_the_tube(self):
        self._tts(1, "[crt-tts] PLAYED NOTHING: aplay exited 1\n")
        self.sec.speak("the answer is 42")
        self.assertTrue(any("the answer is 42" in ln for ln in self._tube()),
                        "a reply nobody could hear also never reached the screen")

    def test_the_tube_line_says_it_was_not_heard(self):
        self._tts(1)
        self.sec.speak("the answer is 42")
        self.assertTrue(any("unspoken" in ln for ln in self._tube()),
                        "the screen showed the words with no sign they went unheard")

    def test_successful_speech_does_not_clutter_the_tube(self):
        self._tts(0)
        self.assertTrue(self.sec.speak("the answer is 42"))
        self.assertEqual(self._tube(), [])

    def test_bad_news_survives_a_dead_speaker(self):
        # The one that matters most: every honest-failure line this project
        # added over the last three cycles is delivered BY speak(). If the
        # output device is dead, the report about the silence was silent too.
        self._tts(1)
        self.sec.play_earcon = lambda name: None
        self.sec.report_brain_unreachable()
        tube = "\n".join(self._tube())
        self.assertIn("can't reach my brain", tube)

    def test_reporting_a_failure_never_raises(self):
        # report_unspoken runs on the failure path of the failure path.
        os.unlink(os.path.join(self.fakebin, "crt-think.sh"))
        self._tts(1)
        self.assertFalse(self.sec.speak("the answer is 42"))


if __name__ == "__main__":
    unittest.main()
