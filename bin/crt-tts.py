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
#   crt-tts.py --device tv "ring the TV"        # route via dexter's native
#   crt-tts.py --device handset "..."           # audio-out service (see below)
#   crt-tts.py --mood urgent "hurry"            # EXPRESSIVE-TONE.md register preset
#   crt-tts.py --pitch-semitones -1 --rate-mult 0.85 --volume-mult 0.8 "..."
#
# ROUTING: on the old dexter/crt-vm setup (2026-07-19), --device tv|handset
# POSTed to dexter-audio-server.py so VirtualBox's one-audio-device-per-VM
# limit could still reach two named outputs (see AUDIO-ROUTING.md, now
# legacy). potato is bare-metal with real ALSA, so tv/handset now default to
# local aplay against the same plughw devices crt-earcon.sh already uses
# (CRT_EARCON_TV_DEVICE/CRT_EARCON_HANDSET_DEVICE). The dexter path only
# still fires if CRT_AUDIO_OUT_URL is explicitly set (2026-07-24 fix -- it
# used to default to a dead dexter URL and silently no-op on potato, the
# same bug class the earcon routing had, see REFACTOR-ASSESSMENT.md #1).
#
# PER-CALL PROSODY (2026-07-20, EXPRESSIVE-TONE.md): pitch/rate/volume used
# to only come from flat tts.conf/env config, so every utterance sounded
# the same regardless of register. Backends differ too much to control this
# uniformly at synthesis time (piper's CLI has no pitch knob at all; espeak's
# flags are baked in before synthesis, not adjustable after) -- instead,
# apply_prosody() below post-processes whichever backend's raw wav with
# sox (pitch/tempo/vol effects), one mechanism for both backends. --mood
# is a shortcut onto EXPRESSIVE-TONE.md's register table; --pitch-semitones/
# --rate-mult/--volume-mult (or the speak() kwargs) override individually.
# No flags at all = byte-identical behavior to before this existed.
import sys, os, signal, subprocess, shlex, tempfile, urllib.request

DEXTER_URL = os.environ.get("CRT_AUDIO_OUT_URL")  # unset = no dexter, use local ALSA below
DEXTER_DEVICES = ("tv", "handset")
LOCAL_TV_DEVICE = os.environ.get("CRT_EARCON_TV_DEVICE", "plughw:2,0")
LOCAL_HANDSET_DEVICE = os.environ.get("CRT_EARCON_HANDSET_DEVICE", "plughw:1,0")

MOOD_PRESETS = {
    # name: (pitch_semitones, rate_mult, volume_mult) -- EXPRESSIVE-TONE.md's
    # register table, translated to sox's pitch/tempo/vol units.
    "urgent":  (0, 1.15, 1.0),    # clipped/urgent: faster, no pitch change
    "curious": (0, 1.0, 1.0),     # warm/curious: unmodified (the default)
    "content": (0, 0.95, 1.0),    # content/settled: a touch slower, calm
    "wistful": (-1, 0.85, 0.85),  # wistful/quiet: slower, softer, a shade lower
}

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


# Sideband duck (SIDEBAND.md): mute the ambient tone for the duration of
# actual TTS playback so the two never compete for the same device. Safe
# to touch unconditionally -- writing/removing this flag file is inert
# unless bin/crt-sideband.sh happens to be running and reading it (it's
# not auto-started anywhere), so this needs no opt-in flag of its own.
SIDEBAND_MUTE_FILE = os.path.expanduser(
    os.environ.get("CRT_SIDEBAND_MUTE_FILE", "~/.crt/sideband.mute"))


def _sideband_mute(muted):
    try:
        if muted:
            d = os.path.dirname(SIDEBAND_MUTE_FILE)
            if d:
                os.makedirs(d, exist_ok=True)
            open(SIDEBAND_MUTE_FILE, "w").close()
        else:
            os.unlink(SIDEBAND_MUTE_FILE)
    except OSError:
        pass


# Capture duck (2026-07-24, closes the stability-bar handset play-while-
# capture item): crt-earcon-loopback-test.py measured that the handset
# output (plughw:1,0) is the SAME USB adapter as the live capture device,
# and playing through it while crt-stt-solo.py's arecord is running leaves
# the recording at ~0.1x baseline -- this hardware can't reliably play+
# record at once. Software can't fix the missing signal, but it CAN stop
# treating that corrupted window as real audio: crt-stt-solo.py already has
# a CTL-file "mute N" reference count (apply_ctl_line) that suppresses VAD
# triggering without tearing down the sole-reader arecord process (see
# CRT_CTL_FILE in HANDOFF.md) -- ref-counted, not a last-write-wins flag, so
# an overlapping earcon duck can't get unmuted early by this one finishing
# first. Route handset playback through it, same duck-around-the-call shape
# as _sideband_mute above, so a stray earcon/TTS blip on the handset can't
# be misread as speech (or drown out a real utterance's start) while the
# adapter is deaf to the mic anyway.
CTL_FILE = os.path.expanduser(os.environ.get("CRT_CTL_FILE", "~/.crt/ctl"))


def _capture_mute(muted):
    try:
        d = os.path.dirname(CTL_FILE)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(CTL_FILE, "a") as f:
            f.write("mute %s\n" % ("1" if muted else "0"))
    except OSError:
        pass


def play_wav(wav, device):
    _sideband_mute(True)
    if device == "handset":
        _capture_mute(True)
    try:
        if device in DEXTER_DEVICES and DEXTER_URL:
            try:
                with open(wav, "rb") as f:
                    data = f.read()
                req = urllib.request.Request(
                    DEXTER_URL + "?device=" + device, data=data,
                    headers={"Content-Type": "audio/wav"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    resp.read()
                return True
            except Exception as e:
                sys.stderr.write("[crt-tts] dexter audio-out failed: %s\n" % e)
                return False
        if device == "tv":
            alsa_device = LOCAL_TV_DEVICE
        elif device == "handset":
            alsa_device = LOCAL_HANDSET_DEVICE
        else:
            alsa_device = device or DEV
        subprocess.run(["aplay", "-D", alsa_device, "-q", wav])
        return True
    finally:
        _sideband_mute(False)
        if device == "handset":
            _capture_mute(False)


def resolve_prosody(mood=None, pitch_semitones=None, rate_mult=None, volume_mult=None):
    """Explicit pitch/rate/volume kwargs win; otherwise --mood's preset;
    otherwise no override at all (None, None, None -- byte-identical to
    pre-2026-07-20 behavior). Pure function, no I/O -- the actual sox
    invocation lives in apply_prosody()."""
    p, r, v = None, None, None
    if mood:
        preset = MOOD_PRESETS.get(mood)
        if preset is None:
            sys.stderr.write("[crt-tts] unknown mood %r, ignoring\n" % mood)
        else:
            p, r, v = preset
    if pitch_semitones is not None:
        p = pitch_semitones
    if rate_mult is not None:
        r = rate_mult
    if volume_mult is not None:
        v = volume_mult
    return p, r, v


def build_sox_effects(pitch_semitones=None, rate_mult=None, volume_mult=None):
    """Pure -- translates prosody overrides into a sox effects-chain
    argument list, or [] if there's nothing to apply."""
    effects = []
    if pitch_semitones:
        effects += ["pitch", str(pitch_semitones * 100)]  # sox pitch is in cents
    if rate_mult and rate_mult != 1.0:
        effects += ["tempo", str(rate_mult)]
    if volume_mult and volume_mult != 1.0:
        effects += ["vol", str(volume_mult)]
    return effects


def apply_prosody(wav, pitch_semitones=None, rate_mult=None, volume_mult=None):
    """Post-processes a synthesized wav with sox to apply per-call
    pitch/tempo/volume, uniformly across both backends (see the module
    header for why this can't happen at synthesis time instead). Returns
    the wav to actually play -- the SAME path, unmodified, if there's
    nothing to apply or sox isn't installed (never blocks playback on a
    missing optional dependency)."""
    effects = build_sox_effects(pitch_semitones, rate_mult, volume_mult)
    if not effects or not have("sox"):
        return wav
    out = wav[:-4] + "_prosody.wav"
    r = subprocess.run(["sox", wav] + [out] + effects, capture_output=True)
    if r.returncode != 0:
        sys.stderr.write("[crt-tts] prosody sox effects failed, playing unmodified: %s\n"
                          % r.stderr[-300:])
        return wav
    return out


def synth_piper(text):
    fd, wav = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    p = subprocess.run(
        [PIPER_BIN, "--model", PIPER_MODEL, "--output_file", wav,
         "--length_scale", str(LENGTH_SCALE)],
        input=text, text=True, capture_output=True)
    if p.returncode != 0:
        sys.stderr.write("[crt-tts] piper failed: %s\n" % p.stderr[-400:])
        try: os.unlink(wav)
        except OSError: pass
        return None
    return wav


def synth_espeak(text):
    binname = "espeak-ng" if have("espeak-ng") else "espeak"
    fd, wav = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    p = subprocess.run(
        [binname, "-v", VOICE, "-s", str(RATE_WPM), "-p", str(PITCH),
         "-a", str(VOLUME), "-w", wav, text],
        capture_output=True, text=True)
    if p.returncode != 0:
        sys.stderr.write("[crt-tts] %s failed: %s\n" % (binname, p.stderr[-400:]))
        try: os.unlink(wav)
        except OSError: pass
        return None
    return wav


def speak(text, device=None, mood=None, pitch_semitones=None, rate_mult=None, volume_mult=None):
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

    raw_wav = synth_piper(text) if backend == "piper" else synth_espeak(text)
    if raw_wav is None:
        return False

    p, r, v = resolve_prosody(mood, pitch_semitones, rate_mult, volume_mult)
    play_wav_path = apply_prosody(raw_wav, p, r, v)
    try:
        return play_wav(play_wav_path, device)
    finally:
        for p_ in {raw_wav, play_wav_path}:
            try: os.unlink(p_)
            except OSError: pass


def main():
    device = None
    mood = None
    pitch_semitones = None
    rate_mult = None
    volume_mult = None
    args = sys.argv[1:]
    rest = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--device" and i + 1 < len(args):
            device = args[i + 1]; i += 2
        elif a == "--mood" and i + 1 < len(args):
            mood = args[i + 1]; i += 2
        elif a == "--pitch-semitones" and i + 1 < len(args):
            pitch_semitones = float(args[i + 1]); i += 2
        elif a == "--rate-mult" and i + 1 < len(args):
            rate_mult = float(args[i + 1]); i += 2
        elif a == "--volume-mult" and i + 1 < len(args):
            volume_mult = float(args[i + 1]); i += 2
        else:
            rest.append(a); i += 1
    text = " ".join(rest) if rest else sys.stdin.read()
    ok = speak(text, device, mood, pitch_semitones, rate_mult, volume_mult)
    sys.exit(0 if ok else 1)


def install_term_handler():
    """Turn SIGTERM into a normal exception-driven exit so play_wav()'s
    finally: still runs. Measured 2026-07-25: Python skips finally blocks
    entirely on an untrapped SIGTERM (bash's EXIT trap, which crt-earcon.sh
    relies on for the same job, does NOT), so `tmux kill-window`/pkill on a
    mid-playback crt-tts.py left its "mute 1" duck unreleased and capture
    deaf. crt-stt-solo.py's MUTE_MAX_SECS watchdog is the backstop for the
    cases this can't cover (SIGKILL, power loss); this closes the common
    one cleanly instead of waiting the watchdog out."""
    def _bail(signum, frame):
        raise SystemExit(143)      # 128 + SIGTERM, the usual shell convention
    try:
        signal.signal(signal.SIGTERM, _bail)
    except (ValueError, OSError):  # not the main thread / no signal support
        pass


if __name__ == "__main__":
    install_term_handler()
    main()
