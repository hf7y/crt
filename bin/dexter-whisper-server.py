#!/usr/bin/env python3
# Native Windows-side transcription server for the crt console: runs
# faster-whisper (CTranslate2, int8) on dexter's full Ryzen CPU instead of
# inside the resource-capped crt-vm guest. The guest posts a WAV, gets text
# back -- everything else (mic capture, VAD, tmux wiring) stays on the VM as
# before; only the CPU-bound transcription step moves to the host.
#
# STATUS: written + dependency-installed on dexter 2026-07-19
# (pip install faster-whisper flask), NOT yet load-tested with real speech.
#
# Run on dexter:  python dexter-whisper-server.py
# (loads the model once at startup; first request after that is fast)
#
# From the guest, call:
#   POST http://<dexter-lan-ip>:8991/transcribe   body: raw WAV bytes
#   -> {"text": "..."}
import os
import tempfile
from flask import Flask, request, jsonify
from faster_whisper import WhisperModel

MODEL_SIZE = os.environ.get("CRT_WHISPER_MODEL_SIZE", r"C:\Users\Zach\fw-base-en")
DEVICE     = os.environ.get("CRT_WHISPER_DEVICE", "cpu")   # cpu | cuda (no NVIDIA GPU here)
COMPUTE    = os.environ.get("CRT_WHISPER_COMPUTE", "int8")  # int8 is the fast CPU path
PORT       = int(os.environ.get("CRT_WHISPER_PORT", "8991"))
CPU_THREADS = int(os.environ.get("CRT_WHISPER_THREADS", "0"))  # 0 = ctranslate2 default (all cores)

app = Flask(__name__)
print("[dexter-whisper] loading model %s (device=%s compute=%s)..." % (MODEL_SIZE, DEVICE, COMPUTE))
model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE,
                     cpu_threads=CPU_THREADS or 0)
print("[dexter-whisper] model loaded, listening on 0.0.0.0:%d" % PORT)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "model": MODEL_SIZE})


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
