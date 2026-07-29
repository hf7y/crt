#!/usr/bin/env python3
"""Tests for bin/crt-whisper-server.py and its mandark compat shim.

Why this file exists at all: the whisper server is the console's whole speech
path and had NO test of any kind. It also had two near-identical host-named
copies, which is how `bin/dexter-whisper-server.py` came to be deleted by
`3dee2d5` and still believed present by FOCUS.md four days later. So this
covers both halves -- the request handling (never covered before), and the
one-implementation property (the thing whose absence caused the wrong premise).

Runs with no faster-whisper and no flask installed: both are stubbed. That is
deliberate, not a shortcut -- dexter, where the nightly runs, has neither, and
a test that silently skips there would be worth nothing on the box that matters.
"""
import json
import os
import subprocess
import sys
import types
import unittest

DIR = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.join(os.path.dirname(DIR), "bin")
SERVER = os.path.join(BIN, "crt-whisper-server.py")
SHIM = os.path.join(BIN, "mandark-whisper-server.py")


class _Resp:
    """Stand-in for flask's jsonify() result: keeps the payload inspectable."""

    def __init__(self, payload):
        self.payload = payload


class _FakeApp:
    def __init__(self, *a, **kw):
        self.routes = {}

    def route(self, rule, **kw):
        def deco(fn):
            self.routes[rule] = fn
            return fn
        return deco

    def run(self, *a, **kw):  # pragma: no cover - never called under test
        raise AssertionError("app.run() must not fire on import")


class _FakeRequest:
    data = b""

    def get_data(self):
        return self.data


class _FakeModel:
    """Records what it was constructed with; returns fixed segments."""

    last_kwargs = None
    transcribed = []

    def __init__(self, size, **kw):
        _FakeModel.last_kwargs = dict(kw, size=size)

    def transcribe(self, path, **kw):
        # The real model reads the file, so assert the handler actually wrote
        # the body to disk before handing the path over.
        with open(path, "rb") as f:
            _FakeModel.transcribed.append((path, f.read()))
        seg = types.SimpleNamespace(text="  hello there  ")
        return [seg], types.SimpleNamespace()


def load_server(env=None):
    """Import bin/crt-whisper-server.py under stubs, return (module, app, request)."""
    fake_request = _FakeRequest()
    flask = types.ModuleType("flask")
    flask.Flask = _FakeApp
    flask.request = fake_request
    flask.jsonify = lambda *a, **kw: _Resp(kw if kw else (a[0] if a else None))
    fw = types.ModuleType("faster_whisper")
    fw.WhisperModel = _FakeModel

    saved_mods = {k: sys.modules.get(k) for k in ("flask", "faster_whisper")}
    saved_env = {k: os.environ.get(k) for k in (env or {})}
    sys.modules["flask"], sys.modules["faster_whisper"] = flask, fw
    os.environ.update(env or {})
    try:
        spec = __import__("importlib.util", fromlist=["util"]).spec_from_file_location(
            "crt_whisper_server_under_test", SERVER)
        mod = __import__("importlib.util", fromlist=["util"]).module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod, mod.app, fake_request
    finally:
        for k, v in saved_mods.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class TestRequestHandling(unittest.TestCase):
    def test_transcribe_writes_body_and_strips_text(self):
        _FakeModel.transcribed = []
        mod, app, req = load_server({"CRT_WHISPER_TAG": "testhost"})
        req.data = b"RIFF....fake wav bytes"
        resp = app.routes["/transcribe"]()
        self.assertEqual(resp.payload, {"text": "hello there"})
        self.assertEqual(len(_FakeModel.transcribed), 1)
        path, body = _FakeModel.transcribed[0]
        self.assertEqual(body, b"RIFF....fake wav bytes")
        # The temp WAV must not survive the request -- this handler runs for
        # every single utterance the console ever hears.
        self.assertFalse(os.path.exists(path), "temp wav leaked: %s" % path)

    def test_empty_body_is_a_400_not_a_crash(self):
        mod, app, req = load_server()
        req.data = b""
        resp, code = app.routes["/transcribe"]()
        self.assertEqual(code, 400)
        self.assertIn("error", resp.payload)

    def test_transcribe_failure_still_cleans_up(self):
        mod, app, req = load_server()
        req.data = b"x"
        leaked = []

        def boom(path, **kw):
            leaked.append(path)
            raise RuntimeError("model exploded")

        mod.model.transcribe = boom
        resp, code = app.routes["/transcribe"]()
        self.assertEqual(code, 500)
        self.assertIn("model exploded", resp.payload["error"])
        self.assertFalse(os.path.exists(leaked[0]), "temp wav leaked on error path")

    def test_health_names_the_host(self):
        # A client that thinks it reached dexter but actually reached mandark
        # is otherwise indistinguishable -- that confusion is why /health
        # reports a host at all, so pin it.
        mod, app, req = load_server({"CRT_WHISPER_TAG": "dexter"})
        self.assertEqual(app.routes["/health"]().payload["host"], "dexter")

    def test_tag_defaults_to_hostname(self):
        os.environ.pop("CRT_WHISPER_TAG", None)
        mod, app, req = load_server()
        import socket
        self.assertEqual(app.routes["/health"]().payload["host"], socket.gethostname())

    def test_env_knobs_reach_the_model(self):
        load_server({"CRT_WHISPER_MODEL_SIZE": "small.en",
                     "CRT_WHISPER_COMPUTE": "float32",
                     "CRT_WHISPER_THREADS": "4"})
        self.assertEqual(_FakeModel.last_kwargs["size"], "small.en")
        self.assertEqual(_FakeModel.last_kwargs["compute_type"], "float32")
        self.assertEqual(_FakeModel.last_kwargs["cpu_threads"], 4)


class TestOneImplementation(unittest.TestCase):
    """The duplication guard. This is the test that would have caught the
    2026-07-29 wrong premise, so it is mechanical, not a comment."""

    def test_no_host_named_server_reimplements_the_model(self):
        offenders = []
        for name in os.listdir(BIN):
            if not name.endswith("-whisper-server.py") or name == "crt-whisper-server.py":
                continue
            with open(os.path.join(BIN, name)) as f:
                if "WhisperModel(" in f.read():
                    offenders.append(name)
        self.assertEqual(
            offenders, [],
            "host-named whisper server(s) carry their own WhisperModel call: %s\n"
            "There must be exactly one implementation (crt-whisper-server.py); "
            "host differences belong in env vars. Two copies is how "
            "dexter-whisper-server.py got deleted and stayed 'present' in "
            "FOCUS.md for four days." % offenders)

    def test_mandark_shim_execs_the_real_server(self):
        with open(SHIM) as f:
            src = f.read()
        self.assertIn("crt-whisper-server.py", src)
        self.assertIn("os.execv", src)

    def test_shim_fails_loud_when_target_is_missing(self):
        # A shim that exits 0 with the server not running is the silent-failure
        # class this project keeps getting bitten by (the earcon bug).
        import shutil
        import tempfile
        tmp = tempfile.mkdtemp()
        try:
            shutil.copy(SHIM, os.path.join(tmp, "mandark-whisper-server.py"))
            p = subprocess.run([sys.executable, os.path.join(tmp, "mandark-whisper-server.py")],
                               capture_output=True, text=True, timeout=30)
            self.assertNotEqual(p.returncode, 0, "shim exited 0 with no server present")
            self.assertIn("shim target missing", p.stderr)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_fresh_install_units_point_at_the_real_server(self):
        for setup in ("setup-mandark-whisper-persistence.sh",
                      "setup-dexter-whisper-persistence.sh"):
            path = os.path.join(BIN, setup)
            with open(path) as f:
                src = f.read()
            self.assertIn("crt-whisper-server.py", src,
                          "%s installs a unit that does not name the real server" % setup)


class TestDexterSetupPreflight(unittest.TestCase):
    def test_preflight_refuses_when_the_server_file_is_absent(self):
        # The bug being pinned: this script's whole reason for existing is that
        # someone believed a server file was present when it was not.
        path = os.path.join(BIN, "setup-dexter-whisper-persistence.sh")
        env = dict(os.environ, CRT_REPO_DIR="/nonexistent/crt/checkout")
        p = subprocess.run(["bash", path], capture_output=True, text=True,
                           timeout=60, env=env)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("server not found", p.stderr)

    def test_preflight_names_the_apt_packages_it_needs(self):
        with open(os.path.join(BIN, "setup-dexter-whisper-persistence.sh")) as f:
            src = f.read()
        self.assertIn("python3-venv", src)
        self.assertIn("ensurepip", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
