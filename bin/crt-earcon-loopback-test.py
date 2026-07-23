#!/usr/bin/env python3
# Acoustic loopback self-test (filed in FOCUS.md 2026-07-23, built same
# night): does an earcon played on a given output device actually reach
# the mic? Answers this by measurement, not by trusting a subprocess exit
# code -- exactly the gap that let the dexter-bridge earcon bug (silent
# no-op, exit 0, no sound) go unnoticed earlier tonight.
#
# Method: record from the capture device for RECORD_SECS, and partway
# through, play a pure sine tone (sox synth, not crt-earcon.sh's
# synthesized earcons -- a single clean tone is easier to detect
# reliably than a two-note contour) on the output device under test.
# Then run a Goertzel-algorithm energy check (stdlib math only, no scipy)
# for that exact frequency in the recording, compared against a silent
# baseline recorded first -- if the tone's bin has meaningfully more
# energy than the noise floor, the loopback path is real.
#
# Also reports the room's baseline peak/RMS (the noise-floor half of
# FOCUS.md's loopback idea) -- directly useful for retuning
# CRT_VAD_THRESHOLD without a live-by-ear session.
#
# Usage: crt-earcon-loopback-test.py [tv|handset|both]
# Env:
#   CRT_LOOPBACK_CAPTURE_DEV (default plughw:1,0 -- potato's only capture device)
#   CRT_LOOPBACK_TV_DEV (default plughw:2,0)
#   CRT_LOOPBACK_HANDSET_DEV (default plughw:1,0)
#   CRT_LOOPBACK_TONE_HZ (default 1200 -- picked away from typical room-noise/AC-hum energy)
#   CRT_LOOPBACK_RECORD_SECS (default 3.0)
import math
import os
import subprocess
import sys
import tempfile
import time
import wave

CAPTURE_DEV = os.environ.get("CRT_LOOPBACK_CAPTURE_DEV", "plughw:1,0")
TV_DEV = os.environ.get("CRT_LOOPBACK_TV_DEV", "plughw:2,0")
HANDSET_DEV = os.environ.get("CRT_LOOPBACK_HANDSET_DEV", "plughw:1,0")
TONE_HZ = float(os.environ.get("CRT_LOOPBACK_TONE_HZ", "1200"))
RECORD_SECS = float(os.environ.get("CRT_LOOPBACK_RECORD_SECS", "3.0"))
RATE = 16000


def goertzel_energy(samples, sample_rate, freq):
    """Energy of `samples` at `freq` Hz -- textbook Goertzel, stdlib
    math only. Returns a magnitude comparable across calls on
    same-length windows, not an absolute physical unit."""
    n = len(samples)
    if n == 0:
        return 0.0
    k = int(0.5 + (n * freq) / sample_rate)
    w = (2.0 * math.pi / n) * k
    cw, sw = math.cos(w), math.sin(w)
    coeff = 2.0 * cw
    s_prev, s_prev2 = 0.0, 0.0
    for s in samples:
        s0 = s + coeff * s_prev - s_prev2
        s_prev2, s_prev = s_prev, s0
    power = s_prev2 * s_prev2 + s_prev * s_prev - coeff * s_prev * s_prev2
    return math.sqrt(max(power, 0.0)) / n


def read_wav_samples(path):
    with wave.open(path, "rb") as w:
        raw = w.readframes(w.getnframes())
    n = len(raw) // 2
    samples = [0] * n
    for i in range(n):
        val = raw[2 * i] | (raw[2 * i + 1] << 8)
        if val >= 32768:
            val -= 65536
        samples[i] = val
    return samples


def record(seconds, path):
    # arecord's -d takes an INTEGER seconds count -- "1.5" fails outright
    # (arecord: main:675: invalid duration argument). Round up so a
    # sub-second request still records at least that long.
    subprocess.run(
        ["arecord", "-D", CAPTURE_DEV, "-f", "S16_LE", "-r", str(RATE), "-c", "1",
         "-d", str(max(1, math.ceil(seconds))), "-q", path],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def play_tone(device, freq, seconds):
    # Generate to a real file, then aplay it -- avoids a pipe racing
    # against device-open latency.
    fd, tmp = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    subprocess.run(["sox", "-n", "-r", str(RATE), tmp, "synth", str(seconds), "sine", str(freq)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["aplay", "-D", device, "-q", tmp],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.unlink(tmp)


def baseline_noise_floor():
    """Records with nothing intentionally playing -- FOCUS.md's
    "noise-floor calibration" half of this idea. Peak/RMS in raw sample
    units (16-bit signed), not dBFS -- callers compare relatively."""
    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    record(1.5, path)
    samples = read_wav_samples(path)
    os.unlink(path)
    if not samples:
        return 0, 0.0
    peak = max(abs(s) for s in samples)
    rms = math.sqrt(sum(s * s for s in samples) / len(samples))
    return peak, rms


def test_device(device, label):
    print("\n--- testing %s (%s) ---" % (label, device))
    fd, rec_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)

    recorder = subprocess.Popen(
        ["arecord", "-D", CAPTURE_DEV, "-f", "S16_LE", "-r", str(RATE), "-c", "1",
         "-d", str(int(RECORD_SECS)), "-q", rec_path],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(RECORD_SECS * 0.3)
    play_tone(device, TONE_HZ, max(0.5, RECORD_SECS * 0.4))
    recorder.wait()

    samples = read_wav_samples(rec_path)
    os.unlink(rec_path)
    if not samples:
        print("  FAIL: no samples captured (arecord/device error)")
        return False

    window = 4096
    best = 0.0
    for i in range(0, len(samples) - window, window // 2):
        e = goertzel_energy(samples[i:i + window], RATE, TONE_HZ)
        best = max(best, e)

    # Baseline comparison, same window size, no tone playing.
    base_peak, base_rms = baseline_noise_floor()
    ratio = best / (base_rms + 1e-6)
    detected = ratio > 8.0  # empirical margin, not a physical constant
    verdict = "DETECTED" if detected else "not detected"
    print("  tone energy=%.1f  baseline rms=%.1f  ratio=%.1fx  -> %s"
          % (best, base_rms, ratio, verdict))
    return detected


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    peak, rms = baseline_noise_floor()
    print("Room noise floor: peak=%d rms=%.1f (16-bit signed sample units)" % (peak, rms))

    results = {}
    if which in ("tv", "both"):
        results["tv"] = test_device(TV_DEV, "TV/HDMI")
    if which in ("handset", "both"):
        results["handset"] = test_device(HANDSET_DEV, "handset/USB")

    print("\n=== summary ===")
    for k, v in results.items():
        print("  %-10s %s" % (k, "OK, mic hears it" if v else "NOT detected by mic"))


if __name__ == "__main__":
    main()
