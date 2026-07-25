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


def last_line(text):
    """The last non-blank line of a subprocess's stderr -- the part that
    names the cause. Pure."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    return lines[-1][:200] if lines else "no error text"


def record(seconds, path):
    """Returns None if the recording ran, or a reason string if it did not.

    The reason matters (2026-07-25): arecord's status and stderr both went
    to /dev/null here, so a capture device that could not be opened produced
    an empty wav, which read downstream as a silent room."""
    # arecord's -d takes an INTEGER seconds count -- "1.5" fails outright
    # (arecord: main:675: invalid duration argument). Round up so a
    # sub-second request still records at least that long.
    try:
        r = subprocess.run(
            ["arecord", "-D", CAPTURE_DEV, "-f", "S16_LE", "-r", str(RATE), "-c", "1",
             "-d", str(max(1, math.ceil(seconds))), "-q", path],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
        )
    except OSError as e:
        return "could not run arecord: %s" % e
    if r.returncode != 0:
        return "arecord exited %d on %s: %s" % (r.returncode, CAPTURE_DEV,
                                                last_line(r.stderr))
    return None


def play_tone(device, freq, seconds):
    """Returns None if the tone really played, or a reason string if it did
    not.

    This function used to send sox's and aplay's status AND stderr to
    /dev/null (2026-07-25). That is a strange thing for THIS tool to have
    done: its own header says it exists because a subprocess exit code is
    not evidence a sound was made -- and it swung so far that it stopped
    reading the exit code at all, leaving it unable to tell "played and the
    mic could not hear it" from "never played". Those two produce identical
    recordings and opposite conclusions: one indicts the hardware, the other
    indicts a device name. FOCUS.md's 2026-07-23 handset finding (0.1x above
    baseline, read as a USB adapter that cannot play and record at once)
    rests on exactly this distinction and could not have made it."""
    # Generate to a real file, then aplay it -- avoids a pipe racing
    # against device-open latency.
    fd, tmp = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        try:
            r = subprocess.run(
                ["sox", "-n", "-r", str(RATE), tmp, "synth", str(seconds),
                 "sine", str(freq)],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        except OSError as e:
            return "could not run sox: %s" % e
        if r.returncode != 0:
            return "sox exited %d: %s" % (r.returncode, last_line(r.stderr))
        if os.path.getsize(tmp) == 0:
            return "sox produced an empty tone file"
        try:
            r = subprocess.run(["aplay", "-D", device, "-q", tmp],
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                               text=True)
        except OSError as e:
            return "could not run aplay: %s" % e
        if r.returncode != 0:
            return "aplay exited %d on %s: %s" % (r.returncode, device,
                                                  last_line(r.stderr))
        return None
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def baseline_noise_floor():
    """Records with nothing intentionally playing -- FOCUS.md's
    "noise-floor calibration" half of this idea. Peak/RMS in raw sample
    units (16-bit signed), not dBFS -- callers compare relatively.

    Returns (peak, rms, error). error is None when the number is real.
    It used to return (0, 0.0) for a failed recording, which is worse than
    useless downstream: the detection ratio is best/(base_rms + 1e-6), so a
    baseline of zero made EVERY device come back DETECTED. A tool that
    reports success when its own measurement failed is the exact thing this
    tool was built to replace."""
    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        err = record(1.5, path)
        if err:
            return 0, 0.0, err
        try:
            samples = read_wav_samples(path)
        except (wave.Error, EOFError, OSError) as e:
            return 0, 0.0, "unreadable baseline recording: %s" % e
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    if not samples:
        return 0, 0.0, "baseline recording was empty"
    peak = max(abs(s) for s in samples)
    rms = math.sqrt(sum(s * s for s in samples) / len(samples))
    return peak, rms, None


DETECTED = "DETECTED"
NOT_DETECTED = "NOT DETECTED"
INCONCLUSIVE = "INCONCLUSIVE"

DETECT_RATIO = float(os.environ.get("CRT_LOOPBACK_DETECT_RATIO", "8.0"))


def loopback_verdict(best, base_rms, play_error=None, capture_error=None):
    """(status, detail) for one device. Pure -- the whole point is that the
    three-way distinction is decidable and testable without a sound card.

    Three outcomes, not two. "the mic did not hear it" is a claim about the
    room and the hardware, and it may only be made when a tone was really
    played and a recording was really captured. Otherwise the honest answer
    is that this run measured nothing."""
    if capture_error:
        return INCONCLUSIVE, "nothing was recorded -- %s" % capture_error
    if play_error:
        return INCONCLUSIVE, "nothing was played -- %s" % play_error
    ratio = best / (base_rms + 1e-6)
    detail = "tone energy=%.1f  baseline rms=%.1f  ratio=%.1fx" % (best, base_rms, ratio)
    return (DETECTED if ratio > DETECT_RATIO else NOT_DETECTED), detail


def test_device(device, label):
    print("\n--- testing %s (%s) ---" % (label, device))
    fd, rec_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)

    err_f = tempfile.NamedTemporaryFile(prefix="crt-loopback-arecord-", suffix=".err")
    recorder = subprocess.Popen(
        ["arecord", "-D", CAPTURE_DEV, "-f", "S16_LE", "-r", str(RATE), "-c", "1",
         "-d", str(int(RECORD_SECS)), "-q", rec_path],
        stdout=subprocess.DEVNULL, stderr=err_f,
    )
    time.sleep(RECORD_SECS * 0.3)
    play_error = play_tone(device, TONE_HZ, max(0.5, RECORD_SECS * 0.4))
    rc = recorder.wait()

    capture_error = None
    if rc != 0:
        err_f.seek(0)
        capture_error = "arecord exited %d on %s: %s" % (
            rc, CAPTURE_DEV, last_line(err_f.read().decode("utf-8", "replace")))
    samples = []
    if capture_error is None:
        try:
            samples = read_wav_samples(rec_path)
        except (wave.Error, EOFError, OSError) as e:
            capture_error = "unreadable recording: %s" % e
        if capture_error is None and not samples:
            capture_error = "no samples captured from %s" % CAPTURE_DEV
    os.unlink(rec_path)

    window = 4096
    best = 0.0
    for i in range(0, len(samples) - window, window // 2):
        e = goertzel_energy(samples[i:i + window], RATE, TONE_HZ)
        best = max(best, e)

    # Baseline comparison, same window size, no tone playing.
    base_peak, base_rms, base_error = baseline_noise_floor()
    status, detail = loopback_verdict(
        best, base_rms, play_error=play_error,
        capture_error=capture_error or base_error)
    print("  %s  -> %s" % (detail, status))
    return status


SUMMARY_TEXT = {
    DETECTED: "OK, mic hears it",
    NOT_DETECTED: "NOT detected by mic",
    INCONCLUSIVE: "MEASURED NOTHING -- see above, this run proves nothing",
}

# Exit status, so this can be a real check rather than something a person has
# to read (FOCUS.md ranked-backlog item 6 asks for exactly this: pass/fail
# plus numbers, not exit 0 regardless). 3 rather than 2 for inconclusive:
# 2 is a usage error elsewhere in this repo, and "the test could not run" must
# not be confused with "you called it wrong" -- or, worse, with a pass.
EXIT_OK, EXIT_NOT_DETECTED, EXIT_INCONCLUSIVE = 0, 1, 3


def summary_exit_code(results):
    """Pure. An inconclusive run outranks a clean not-detected: if the tool
    did not measure anything, the not-detected verdicts beside it are not
    trustworthy either."""
    if not results:
        return EXIT_INCONCLUSIVE
    if any(v == INCONCLUSIVE for v in results.values()):
        return EXIT_INCONCLUSIVE
    return EXIT_OK if all(v == DETECTED for v in results.values()) else EXIT_NOT_DETECTED


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    peak, rms, base_error = baseline_noise_floor()
    if base_error:
        print("Room noise floor: UNAVAILABLE -- %s" % base_error)
    else:
        print("Room noise floor: peak=%d rms=%.1f (16-bit signed sample units)"
              % (peak, rms))

    results = {}
    if which in ("tv", "both"):
        results["tv"] = test_device(TV_DEV, "TV/HDMI")
    if which in ("handset", "both"):
        results["handset"] = test_device(HANDSET_DEV, "handset/USB")

    print("\n=== summary ===")
    for k, v in results.items():
        print("  %-10s %s" % (k, SUMMARY_TEXT.get(v, v)))
    sys.exit(summary_exit_code(results))


if __name__ == "__main__":
    main()
