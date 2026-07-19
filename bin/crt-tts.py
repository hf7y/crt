#!/usr/bin/env python3
# Text -> speech for the crt console. Pluggable backend: piper (preferred,
# better/faster neural voices, fully offline) or espeak-ng (fallback, always
# available on Debian, no model download). Params come from ~/.crt/tts.conf
# (written by crt-tts-calibrate.py) with env vars as override, so the runtime
# and the calibration tool share one profile.
#
# STATUS: NOT hardware-verified -- written without access to crt-vm. Backend
# detection, argument shapes, and the aplay pipeline are correct as designed
# but need a real run once the VM is reachable: `pip`/`apt` for piper voices
# aren't installed there yet either (see crt-tts-calibrate.py header).
#
# Usage:
#   crt-tts.py "text to speak"          # speak once
#   echo "text" | crt-tts.py            # or via stdin
#   CRT_TTS_DEV=plughw:1,0 crt-tts.py "ring the TV"   # override output device
import sys, os, subprocess, shlex, tempfile

CONF = os.path.expanduser(os.environ.get("CRT_TTS_CONF", "~/.crt/tts.conf"))


def load_conf():
    cfg = {}
    if os.path.exists(CONF):
        for line in open(CONF):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip().strip('"')
    return cfg


CFG = load_conf()


def get(name, default):
    # env var wins, then tts.conf, then default
    return os.environ.get(name, CFG.get(name, default))


BACKEND   = get("CRT_TTS_BACKEND", "auto")          # auto | piper | espeak
DEV       = get("CRT_TTS_DEV", "default")           # ALSA device for aplay
RATE_WPM  = get("CRT_TTS_RATE", "165")               # words/min (espeak) or piper length-scale below
PITCH     = get("CRT_TTS_PITCH", "50")               # espeak 0-99
VOLUME    = get("CRT_TTS_VOLUME", "100")             # espeak 0-200 (%)
VOICE     = get("CRT_TTS_VOICE", "en-us")            # espeak voice, or piper model path
PIPER_BIN = get("CRT_PIPER_BIN", os.path.expanduser("~/.local/bin/piper"))
PIPER_MODEL = get("CRT_PIPER_MODEL", os.path.expanduser("~/.crt/voices/en_US-voice.onnx"))
LENGTH_SCALE = get("CRT_TTS_LENGTH_SCALE", "1.0")   # piper speed: >1 slower, <1 faster


def have(cmd):
    return subprocess.run(["which", cmd], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL).returncode == 0


def pick_backend():
    if BACKEND in ("piper", "espeak"):
        return BACKEND
    if os.path.exists(PIPER_BIN) and os.path.exists(PIPER_MODEL):
        return "piper"
    if have("espeak-ng") or have("espeak"):
        return "espeak"
    return None


def speak_piper(text):
    fd, wav = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        p = subprocess.run(
            [PIPER_BIN, "--model", PIPER_MODEL, "--output_file", wav,
             "--length_scale", str(LENGTH_SCALE)],
            input=text, text=True, capture_output=True)
        if p.returncode != 0:
            sys.stderr.write("[crt-tts] piper failed: %s\n" % p.stderr[-400:])
            return False
        subprocess.run(["aplay", "-D", DEV, "-q", wav])
        return True
    finally:
        try: os.unlink(wav)
        except OSError: pass


def speak_espeak(text):
    binname = "espeak-ng" if have("espeak-ng") else "espeak"
    fd, wav = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        p = subprocess.run(
            [binname, "-v", VOICE, "-s", str(RATE_WPM), "-p", str(PITCH),
             "-a", str(VOLUME), "-w", wav, text],
            capture_output=True, text=True)
        if p.returncode != 0:
            sys.stderr.write("[crt-tts] %s failed: %s\n" % (binname, p.stderr[-400:]))
            return False
        subprocess.run(["aplay", "-D", DEV, "-q", wav])
        return True
    finally:
        try: os.unlink(wav)
        except OSError: pass


def speak(text, device=None):
    global DEV
    if device:
        DEV = device
    text = text.strip()
    if not text:
        return False
    backend = pick_backend()
    if backend is None:
        sys.stderr.write(
            "[crt-tts] no TTS backend available. Install one:\n"
            "  apt-get install espeak-ng   # quick, robotic, zero setup\n"
            "  or piper (better quality): "
            "https://github.com/rhasspy/piper -> ~/.local/bin/piper + a voice "
            ".onnx in ~/.crt/voices/\n")
        return False
    if backend == "piper":
        return speak_piper(text)
    return speak_espeak(text)


def main():
    device = None
    args = sys.argv[1:]
    if args and args[0] == "--device":
        device = args[1]
        args = args[2:]
    text = " ".join(args) if args else sys.stdin.read()
    ok = speak(text, device)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
