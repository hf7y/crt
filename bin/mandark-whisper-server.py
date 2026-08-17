#!/usr/bin/env python3
# Native transcription server on mandark (Linux dev box) for the crt console:
# runs faster-whisper on mandark's full i7 CPU instead of on-device (Pi) or
# the old resource-capped crt-vm guest. Same request/response contract as
# dexter-whisper-server.py (POST raw WAV -> {"text": ...}) so any client
#   [rest: vault:crt/header-archaeology-20260817.md]
import os
import tempfile
from flask import Flask, request, jsonify
from faster_whisper import WhisperModel

MODEL_SIZE  = os.environ.get("CRT_WHISPER_MODEL_SIZE", "base.en")
DEVICE      = os.environ.get("CRT_WHISPER_DEVICE", "cpu")
COMPUTE     = os.environ.get("CRT_WHISPER_COMPUTE", "int8")
PORT        = int(os.environ.get("CRT_WHISPER_PORT", "8991"))
CPU_THREADS = int(os.environ.get("CRT_WHISPER_THREADS", "0"))  # 0 = ctranslate2 default (all cores)

app = Flask(__name__)
print("[mandark-whisper] loading model %s (device=%s compute=%s)..." % (MODEL_SIZE, DEVICE, COMPUTE))
model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE,
                     cpu_threads=CPU_THREADS or 0)
print("[mandark-whisper] model loaded, listening on 0.0.0.0:%d" % PORT)


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
