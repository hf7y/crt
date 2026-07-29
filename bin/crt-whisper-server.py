#!/usr/bin/env python3
# The crt console's whisper transcription server -- ONE implementation, any host.
#
# History, because the duplication caused a real wrong-premise bug (2026-07-29):
# there used to be two of these, `dexter-whisper-server.py` and
# `mandark-whisper-server.py`, differing only in a log tag, a comment block, and
# a default model path. `3dee2d5` ("Refactor sweep: delete dead dexter/crt-vm
# code") deleted the dexter copy while dexter was legacy. The host policy then
# reversed on 2026-07-28 and dexter became the DEFAULT execution host, at which
# point FOCUS.md filed a work item that read "`bin/dexter-whisper-server.py`
# already exists in this repo ... so this is a deploy-and-repoint, not a build."
# It did not exist. Two host-named copies of one program is what let a file be
# deleted in one place and still believed present in another.
#
# So: the host is not in the filename and not in the code. Everything that
# actually varies per host is an env var, and the log tag defaults to the
# hostname so the logs still say where they came from.
#
#   CRT_WHISPER_MODEL_SIZE  base.en          faster-whisper model name or path
#   CRT_WHISPER_DEVICE      cpu              cpu | cuda
#   CRT_WHISPER_COMPUTE     int8             int8 is the fast CPU path
#   CRT_WHISPER_PORT        8991
#   CRT_WHISPER_THREADS     0                0 = ctranslate2 default (all cores)
#   CRT_WHISPER_TAG         <hostname>       log prefix only
#
# Run:   <venv>/bin/python bin/crt-whisper-server.py
# Call:  POST http://<host>:8991/transcribe   body: raw WAV bytes -> {"text": ...}
#        GET  http://<host>:8991/health                           -> {"ok": true, ...}
#
# `bin/mandark-whisper-server.py` is a compat shim onto this file: mandark's
# live `crt-whisper-server.service` names that path in its ExecStart and this
# run could not reach mandark to verify a unit edit, so the old path keeps
# working rather than being broken from a box that cannot test the fix.
import os
import socket
import tempfile

from flask import Flask, request, jsonify
from faster_whisper import WhisperModel

MODEL_SIZE = os.environ.get("CRT_WHISPER_MODEL_SIZE", "base.en")
DEVICE = os.environ.get("CRT_WHISPER_DEVICE", "cpu")
COMPUTE = os.environ.get("CRT_WHISPER_COMPUTE", "int8")
PORT = int(os.environ.get("CRT_WHISPER_PORT", "8991"))
CPU_THREADS = int(os.environ.get("CRT_WHISPER_THREADS", "0"))
TAG = os.environ.get("CRT_WHISPER_TAG") or socket.gethostname()

app = Flask(__name__)
print("[%s-whisper] loading model %s (device=%s compute=%s)..."
      % (TAG, MODEL_SIZE, DEVICE, COMPUTE))
model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE,
                     cpu_threads=CPU_THREADS or 0)
print("[%s-whisper] model loaded, listening on 0.0.0.0:%d" % (TAG, PORT))


@app.route("/health", methods=["GET"])
def health():
    # `host` is what makes a failover peer diagnosable: a client that thinks it
    # is talking to dexter and is actually talking to mandark looks identical
    # otherwise, and that exact confusion is why this file exists.
    return jsonify({"ok": True, "model": MODEL_SIZE, "host": TAG})


@app.route("/transcribe", methods=["POST"])
def transcribe():
    data = request.get_data()
    if not data:
        return jsonify({"error": "empty body"}), 400
    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        with open(path, "wb") as f:
            f.write(data)
        segments, info = model.transcribe(path, beam_size=1, language="en")
        text = " ".join(seg.text.strip() for seg in segments)
        return jsonify({"text": text.strip()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, threaded=True)
