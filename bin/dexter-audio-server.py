#!/usr/bin/env python3
# Native Windows-side audio OUTPUT server: plays a posted WAV to an explicit
# device (TV/HDMI or the handset's analog jack) via sounddevice/PortAudio,
# which can target a specific device per call -- no need to ever touch
# Windows' systemwide default output device. This is the fix for the
# COM/IPolicyConfig dead end documented in AUDIO-ROUTING.md: we don't need to
# switch the default at all, just tell PortAudio which device to use for
# this one call.
#
# STATUS: written + deps installed (pip install sounddevice numpy) on dexter
# 2026-07-19. Device name matching below is based on `sd.query_devices()`
# output on THIS dexter -- re-run --list if the device names ever differ.
#
# Run on dexter:  python dexter-audio-server.py
# From the guest, POST a WAV to:
#   http://<dexter-lan-ip>:8992/play?device=tv        (or device=handset)
import io
import os
import sys
import wave

import numpy as np
import sounddevice as sd
from flask import Flask, request, jsonify

PORT = int(os.environ.get("CRT_AUDIO_OUT_PORT", "8992"))

# Match by substring against sd.query_devices() names, preferring WASAPI
# (hostapi index tends to be 2 on this machine, but match by name not index
# since device indices can shift across reboots/driver updates).
DEVICE_MATCH = {
    "tv":      "MACROSILICON",
    "handset": "Speakers (2- Realtek",
}

app = Flask(__name__)


def find_device(key):
    substr = DEVICE_MATCH.get(key)
    if not substr:
        return None
    devices = sd.query_devices()
    # Prefer WASAPI (usually gives the most reliable exclusive/shared mode
    # behavior); fall back to the first name match of any host API.
    candidates = [i for i, d in enumerate(devices)
                  if substr in d['name'] and d['max_output_channels'] > 0]
    if not candidates:
        return None
    # WASAPI entries on this machine come back with hostapi name containing
    # "Windows WASAPI" -- query_devices() doesn't expose the api name
    # directly per-device without cross-referencing query_hostapis().
    hostapis = sd.query_hostapis()
    for i in candidates:
        if "WASAPI" in hostapis[devices[i]['hostapi']]['name']:
            return i
    return candidates[0]


@app.route("/list", methods=["GET"])
def list_devices():
    devices = sd.query_devices()
    hostapis = sd.query_hostapis()
    out = [{"index": i, "name": d['name'],
            "hostapi": hostapis[d['hostapi']]['name'],
            "out_channels": d['max_output_channels']}
           for i, d in enumerate(devices) if d['max_output_channels'] > 0]
    return jsonify(out)


@app.route("/health", methods=["GET"])
def health():
    resolved = {k: find_device(k) for k in DEVICE_MATCH}
    return jsonify({"ok": True, "resolved_devices": resolved})


@app.route("/play", methods=["POST"])
def play():
    device_key = request.args.get("device", "handset")
    idx = find_device(device_key)
    if idx is None:
        return jsonify({"error": "no device matched for '%s'" % device_key}), 400
    data = request.get_data()
    if not data:
        return jsonify({"error": "empty body"}), 400
    try:
        with wave.open(io.BytesIO(data), "rb") as w:
            sr = w.getframerate()
            nch = w.getnchannels()
            sw = w.getsampwidth()
            frames = w.readframes(w.getnframes())
        dtype = {1: np.uint8, 2: np.int16, 4: np.int32}.get(sw)
        if dtype is None:
            return jsonify({"error": "unsupported sample width %d" % sw}), 400
        audio = np.frombuffer(frames, dtype=dtype)
        if nch > 1:
            audio = audio.reshape(-1, nch)
        sd.play(audio, samplerate=sr, device=idx)
        sd.wait()
        return jsonify({"ok": True, "device": device_key, "device_index": idx})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    print("[dexter-audio] resolved devices: %s"
          % {k: find_device(k) for k in DEVICE_MATCH})
    app.run(host="0.0.0.0", port=PORT, threaded=False)
