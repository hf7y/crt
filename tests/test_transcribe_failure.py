#!/usr/bin/env python3
# Offline tests for crt-stt-solo.py's transcription-failure signal
# (2026-07-25, seventh cycle). The bug these pin down: transcribe_remote()
# returned "" for BOTH "the server transcribed this clip as nothing" and
# "there is no server" -- so an unreachable mandark made potato go silent
#   [rest: vault:crt/header-archaeology-20260817.md]
import http.server
import importlib.util
import json
import os
import socket
import stat
import tempfile
import threading
import time
import unittest

BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")
spec = importlib.util.spec_from_file_location(
    "crt_stt_solo_transcribe", os.path.join(BIN_DIR, "crt-stt-solo.py"))
stt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stt)


class FakeWhisperHandler(http.server.BaseHTTPRequestHandler):
    """Serves whatever the test told it to serve. `behaviour` is set on the
    server object, not here, so one handler class covers every case."""

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.server.last = (self.headers.get("Content-Type", ""), self.rfile.read(length))
        behaviour = self.server.behaviour
        if behaviour == "hang":
            time.sleep(3.0)
            behaviour = ("json", {"text": "too late"})
        if behaviour == "http500":
            self.send_error(500, "whisper exploded")
            return
        kind, payload = behaviour
        body = (json.dumps(payload) if kind == "json" else payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class FakeWhisperServer:
    """A real HTTP server on a real ephemeral port."""

    def __init__(self, behaviour):
        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), FakeWhisperHandler)
        self.httpd.behaviour = behaviour
        self.url = "http://127.0.0.1:%d/transcribe" % self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)


def dead_port_url():
    """A port that is guaranteed to have nothing listening: bind it, read the
    number, close it. This is the unreachable-mandark case."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return "http://127.0.0.1:%d/transcribe" % port


class TranscribeRemoteTest(unittest.TestCase):
    """The core split: "" means heard-nothing, None means asked-nobody."""

    def setUp(self):
        fd, self.wav = tempfile.mkstemp(suffix=".wav")
        os.write(fd, b"RIFF....WAVEfmt ")
        os.close(fd)
        self._saved_server = stt.WHISPER_SERVER
        self._saved_timeout = stt.WHISPER_SERVER_TIMEOUT
        stt.WHISPER_SERVER_TIMEOUT = 1.0

    def tearDown(self):
        stt.WHISPER_SERVER = self._saved_server
        stt.WHISPER_SERVER_TIMEOUT = self._saved_timeout
        os.unlink(self.wav)

    def _against(self, behaviour):
        server = FakeWhisperServer(behaviour)
        stt.WHISPER_SERVER = server.url
        try:
            return stt.transcribe_remote(self.wav)
        finally:
            server.stop()

    def test_real_transcription_comes_back(self):
        self.assertEqual(self._against(("json", {"text": "potato this is zach"})),
                         "potato this is zach")

    def test_the_request_is_the_form_the_container_wants(self):
        # whisper.cpp refuses the raw body mandark took, and that refusal
        # is indistinguishable from any other HTTP error once it is None.
        server = FakeWhisperServer(("json", {"text": "ok"}))
        stt.WHISPER_SERVER = server.url
        try:
            stt.transcribe_remote(self.wav)
        finally:
            server.stop()
        ctype, body = server.httpd.last
        self.assertIn("multipart/form-data; boundary=", ctype)
        self.assertIn(b'name="file"; filename=', body)
        self.assertIn(b"RIFF", body)

    def test_genuinely_empty_transcription_is_empty_string(self):
        # The server ran and heard nothing. This is a silent room, and it
        # must stay distinguishable from every case below.
        self.assertEqual(self._against(("json", {"text": ""})), "")

    def test_unreachable_server_is_none_not_empty(self):
        # The regression this whole file exists for: before 2026-07-25 this
        # returned "" and the console treated a dead mandark as a quiet room.
        stt.WHISPER_SERVER = dead_port_url()
        self.assertIsNone(stt.transcribe_remote(self.wav))

    def test_http_error_is_none(self):
        self.assertIsNone(self._against("http500"))

    def test_http_error_response_is_closed_not_leaked(self):
        # urllib hands back an HTTPError that IS an open file-like object
        # over a spooled temp file. A whisper server 500ing on every
        # utterance leaks one per utterance until the GC gets to it, and
        # potato had 183MB free the last time anyone measured. If it is left
        # open, collecting it emits a ResourceWarning -- so that warning is
        # the witness.
        import gc
        import warnings
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self._against("http500")
            gc.collect()
        leaks = [w for w in caught if issubclass(w.category, ResourceWarning)]
        self.assertEqual(leaks, [], "leaked an unclosed HTTPError response")

    def test_unparseable_body_is_none(self):
        self.assertIsNone(self._against(("raw", "<html>proxy error</html>")))

    def test_json_without_text_key_is_none(self):
        # A server that answered a different question than the one asked.
        self.assertIsNone(self._against(("json", {"error": "no model loaded"})))

    def test_non_string_text_is_none(self):
        self.assertIsNone(self._against(("json", {"text": None})))

    def test_json_that_is_not_an_object_is_none(self):
        self.assertIsNone(self._against(("json", ["potato"])))

    def test_timeout_is_none(self):
        stt.WHISPER_SERVER_TIMEOUT = 0.3
        self.assertIsNone(self._against("hang"))


class TranscribePropagationTest(unittest.TestCase):
    """transcribe() must not launder None back into "" on the way up."""

    def setUp(self):
        self._saved = {k: getattr(stt, k) for k in
                       ("WHISPER_SERVER", "WHISPER_SERVER_TIMEOUT", "WBIN",
                        "MODEL", "NORM", "HP", "NR_PROF")}
        # No sox pass: this test is about the recogniser branch, and sox may
        # not even be installed on the machine running the suite.
        stt.NORM = False
        stt.HP = "0"
        stt.NR_PROF = ""
        stt.WHISPER_SERVER_TIMEOUT = 1.0
        self.frames = b"\x00\x00" * 1600

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(stt, k, v)

    def test_remote_failure_propagates_as_none(self):
        stt.WHISPER_SERVER = dead_port_url()
        self.assertIsNone(stt.transcribe(self.frames))

    def test_remote_success_propagates(self):
        server = FakeWhisperServer(("json", {"text": "hello"}))
        stt.WHISPER_SERVER = server.url
        try:
            self.assertEqual(stt.transcribe(self.frames), "hello")
        finally:
            server.stop()

    def _fake_whisper(self, script):
        fd, path = tempfile.mkstemp(suffix=".sh")
        os.write(fd, script.encode("utf-8"))
        os.close(fd)
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
        self.addCleanup(os.unlink, path)
        return path

    def test_local_whisper_nonzero_exit_is_none(self):
        # An empty stdout from a whisper-cli that failed is not silence
        # either -- missing model file, unreadable WAV, OOM on the Pi.
        stt.WHISPER_SERVER = ""
        stt.WBIN = self._fake_whisper("#!/bin/sh\nexit 1\n")
        self.assertIsNone(stt.transcribe(self.frames))

    def test_local_whisper_success_propagates(self):
        stt.WHISPER_SERVER = ""
        stt.WBIN = self._fake_whisper("#!/bin/sh\necho '  hello   there '\n")
        self.assertEqual(stt.transcribe(self.frames), "hello there")

    def test_missing_local_whisper_binary_is_none(self):
        stt.WHISPER_SERVER = ""
        stt.WBIN = "/no/such/whisper-cli"
        self.assertIsNone(stt.transcribe(self.frames))


class FailureReportTest(unittest.TestCase):
    """The wording is the deliverable here: this is the only thing that tells
    a human the difference between a dead pipeline and a quiet room."""

    def test_first_failure_announces_itself(self):
        hud, line = stt.transcribe_failure_report(1, "http://mandark:8991/transcribe")
        self.assertIsNotNone(line)
        self.assertIn("http://mandark:8991/transcribe", line)

    def test_line_says_it_is_not_silence(self):
        _, line = stt.transcribe_failure_report(1, "http://mandark:8991/transcribe")
        self.assertIn("NOT a silent room", line)

    def test_local_failure_names_the_local_binary(self):
        _, line = stt.transcribe_failure_report(1, "")
        self.assertIn(stt.WBIN, line)
        self.assertNotIn("whisper server", line)

    def test_ongoing_outage_does_not_repeat_every_utterance(self):
        for n in (2, 3, 4, 5, 9):
            _, line = stt.transcribe_failure_report(n, "http://x/t")
            self.assertIsNone(line, "failure %d should be folded into the outage" % n)

    def test_ongoing_outage_still_speaks_up_periodically(self):
        _, line = stt.transcribe_failure_report(stt.TRANSCRIBE_FAIL_REPEAT, "http://x/t")
        self.assertIsNotNone(line)
        self.assertIn("in a row", line)

    def test_hud_always_says_something_and_fits_the_tube(self):
        # The person is looking at the CRT, not at this pane's scrollback,
        # so the HUD half fires on every single failure -- and has to fit.
        for n in (1, 2, 17, 4321):
            hud, _ = stt.transcribe_failure_report(n, "http://x/t")
            self.assertTrue(hud)
            self.assertLessEqual(len(hud), 40, "HUD %r too wide for the tube" % hud)

    def test_hud_does_not_read_as_silence(self):
        # "nothing heard" would be the same lie in a shorter form.
        for n in (1, 5):
            hud, _ = stt.transcribe_failure_report(n, "http://x/t")
            self.assertIn("lost", hud.lower())

    def test_recovery_is_silent_when_nothing_was_lost(self):
        self.assertIsNone(stt.transcribe_recovery_report(0))

    def test_recovery_reports_the_gap(self):
        line = stt.transcribe_recovery_report(3)
        self.assertIsNotNone(line)
        self.assertIn("3", line)
        self.assertIn("recovered", line)

    def test_recovery_singular_plural(self):
        self.assertIn("1 lost utterance", stt.transcribe_recovery_report(1))
        self.assertIn("2 lost utterances", stt.transcribe_recovery_report(2))


class ReportLineTest(unittest.TestCase):
    def test_a_dead_pty_does_not_turn_a_message_into_a_crash(self):
        # `tmux kill-window` takes the pty out from under this process; an
        # unguarded write raises EIO. A message about a failure must not
        # become a second failure. Same guard as main()'s exit message.
        import io

        class DeadPty(io.StringIO):
            def write(self, *a):
                raise OSError(5, "Input/output error")

        saved_out, saved_err = stt.sys.stdout, stt.sys.stderr
        stt.sys.stdout, stt.sys.stderr = DeadPty(), DeadPty()
        try:
            stt.report_line("anything at all")   # must not raise
        finally:
            stt.sys.stdout, stt.sys.stderr = saved_out, saved_err


if __name__ == "__main__":
    unittest.main(verbosity=2)
