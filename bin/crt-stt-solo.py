#!/usr/bin/env python3
# Single-reader standalone STT engine -- no Claude Code, no dsnoop.
#
# WHY THIS EXISTS: on the VirtualBox guest the emulated capture does NOT fan out
# through dsnoop -- a *second* reader gets a starved signal (measured: sole
# reader ~12% peak, second reader ~0.7%). So the old design (stt-feed + a
# separate crt-levels meter, both reading the 'crtmic' dsnoop) had the meter
# quietly stealing stt-feed's audio. This engine is instead the ONE process that
# reads the mic: it keeps a single arecord open continuously (which also keeps
# the emulated capture warm, no per-utterance open/close) and does metering,
# voice-activity detection, and whisper transcription all off that one stream.
#
# VAD is PEAK-based, not average/RMS. sox's `silence` gates on average level,
# which at the current low input gain (~0.3% speech RMS) never crosses a usable
# threshold. Speech *peaks*, though, hit 2-12% while the noise floor peaks ~0.5%
# -- so a per-chunk peak gate separates them cleanly without the Windows mic
# boost. Raise CRT_VAD_THRESHOLD once input gain is restored.
#
# Output: transcriptions scroll; a live "MIC [####|....] 12.3% TALK" meter is
# redrawn on the bottom line (same widget as crt-meter.py). Ctrl-C to quit.
import sys, os, array, time, wave, tempfile, subprocess, datetime
from collections import deque

# SINK: where recognized text goes.
#   stdout (default) -- scroll transcriptions; standalone STT/debug view.
#   claude           -- type into the tmux Claude Code pane + voice-control keys,
#                       exactly like stt-feed.sh, but from this SINGLE-reader
#                       engine (no dsnoop, no second reader) -- Approach B in
#                       AUDIO-DEBUG.md. Use via bin/crt-console-solo.sh.
SINK    = os.environ.get("CRT_STT_SINK", "stdout")
SESSION = os.environ.get("CRT_TMUX_SESSION", "claude")
PANE    = os.environ.get("CRT_TMUX_PANE", "0")

# Single-word control utterances -> keystrokes (kept in sync with stt-feed.sh).
CONTROL = {
    "enter": "Enter", "submit": "Enter", "send": "Enter", "return": "Enter",
    "go": "Enter", "proceed": "Enter", "yes": "Enter", "yeah": "Enter",
    "yep": "Enter", "confirm": "Enter", "accept": "Enter", "okay": "Enter",
    "ok": "Enter",
    "no": "Escape", "nope": "Escape", "cancel": "Escape", "escape": "Escape",
    "abort": "Escape", "dismiss": "Escape", "nevermind": "Escape",
    "up": "Up", "previous": "Up", "back": "Up",
    "down": "Down", "next": "Down",
    "clear": "C-u", "scratch": "C-u", "backspace": "C-u",
}


def send_to_claude(text, key):
    """Type text (or send a control keystroke) into the tmux Claude pane."""
    target = "%s:%s" % (SESSION, PANE)
    if " " not in text and key in CONTROL:
        subprocess.run(["tmux", "send-keys", "-t", target, CONTROL[key]])
        return
    subprocess.run(["tmux", "send-keys", "-t", target, "-l", text])
    subprocess.run(["tmux", "send-keys", "-t", target, "Enter"])

RATE   = 16000
CHUNK  = int(RATE * 0.1)                 # 100 ms analysis window
NBYTES = CHUNK * 2                        # S16_LE mono
FULL   = 32768.0

DEV    = os.environ.get("CRT_AUDIO_DEV", "plughw:0,0")   # single reader; NOT dsnoop
WBIN   = os.environ.get("CRT_WHISPER_BIN",   os.path.expanduser("~/whisper.cpp/build/bin/whisper-cli"))
MODEL  = os.environ.get("CRT_WHISPER_MODEL", os.path.expanduser("~/whisper.cpp/models/ggml-base.en.bin"))
THRESH = float(os.environ.get("CRT_VAD_THRESHOLD", "1.0")) / 100.0   # peak fraction
START  = int(os.environ.get("CRT_VAD_START_CHUNKS", "2"))            # chunks above -> speech
TRAIL  = float(os.environ.get("CRT_VAD_TRAIL", "0.8"))              # s below -> end
MAXUTT = float(os.environ.get("CRT_VAD_MAX", "20"))                 # hard cap
MINUTT = float(os.environ.get("CRT_VAD_MIN", "0.4"))               # drop shorter
PREROLL= int(os.environ.get("CRT_VAD_PREROLL", "3"))               # chunks kept before onset
WIDTH  = int(os.environ.get("CRT_METER_WIDTH", "20"))
MFULL  = float(os.environ.get("CRT_METER_FULL", "0.30"))          # peak that fills the bar
NORM   = os.environ.get("CRT_NORMALIZE", "1") != "0"
# Noise pre-filtering before whisper (helps in a noisy room, e.g. AC hum making
# whisper hallucinate sound tags). All opt-in / off by default.
HP      = os.environ.get("CRT_HIGHPASS", "0")          # high-pass cutoff Hz; "0" = off
NR_PROF = os.environ.get("CRT_NOISERED_PROF", "")      # sox noise profile (from `sox ac.wav -n noiseprof x.prof`)
NR_AMT  = os.environ.get("CRT_NOISERED_AMT", "0.21")   # noisered strength 0..1 (higher = more aggressive)

CHUNK_DUR = CHUNK / RATE
THR_COL   = max(0, min(WIDTH - 1, int(THRESH / MFULL * WIDTH)))

# whisper's canonical noise/silence hallucinations -- never emit these.
HALLU = set("you thankyou thanks thankyouforwatching bye music musicplaying "
            "cricketschirping silence blankaudio sound soundeffects applause "
            "inaudible foreignspeech speaking".split())


def read_exact(f, n):
    b = bytearray()
    while len(b) < n:
        c = f.read(n - len(b))
        if not c:
            break
        b += c
    return bytes(b)


def meter(peak):
    filled = max(0, min(WIDTH, int(peak / MFULL * WIDTH)))
    bar = ''.join('#' if i < filled else ('|' if i == THR_COL else '.')
                  for i in range(WIDTH))
    tag = 'TALK' if filled > THR_COL else '    '
    sys.stdout.write('\rMIC [%s] %5.1f%% %s' % (bar, peak * 100, tag))
    sys.stdout.flush()


def transcribe(frames):
    raw = norm = None
    try:
        fd, raw = tempfile.mkstemp(suffix=".wav"); os.close(fd)
        with wave.open(raw, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
            w.writeframes(frames)
        feed = raw
        # One sox pass: high-pass -> noise reduction -> peak normalize, in that
        # order (denoise before normalizing so we don't amplify the noise first).
        effects = []
        if HP != "0":
            effects += ["highpass", HP]
        if NR_PROF and os.path.exists(NR_PROF):
            effects += ["noisered", NR_PROF, NR_AMT]
        if NORM:
            effects += ["gain", "-n", "-1"]
        if effects:
            norm = raw[:-4] + "_f.wav"
            if subprocess.run(["sox", raw, norm] + effects,
                              stderr=subprocess.DEVNULL).returncode == 0:
                feed = norm
        out = subprocess.run([WBIN, "-m", MODEL, "-f", feed, "-nt", "-np"],
                             capture_output=True, text=True).stdout
        return " ".join(out.split())
    except Exception:
        return ""
    finally:
        for p in (raw, norm):
            if p:
                try: os.unlink(p)
                except OSError: pass


def emit(text):
    key = "".join(c for c in text.lower() if c.isalpha())
    if not text or len(key) < 2 or key in HALLU:
        return
    # Drop non-speech sound tags whisper emits on noise: "(metal clanging)",
    # "[BLANK_AUDIO]", "*applause*", "♪ music ♪" -- fully bracket/symbol-wrapped.
    t = text.strip()
    if t and t[0] in "([*♪" and t[-1] in ")]*♪":
        return
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    sys.stdout.write('\r' + ' ' * (WIDTH + 20) + '\r')   # clear meter line
    if SINK == "claude":
        # Show what was sent (so the meter strip still doubles as a log), then
        # type it into Claude / fire the control keystroke.
        label = "(key %s)" % CONTROL[key] if (" " not in text and key in CONTROL) else "->"
        print("%s  %s %s" % (ts, label, text))
        send_to_claude(text, key)
    else:
        print("%s  %s" % (ts, text))


def main():
    # claude sink: don't start feeding keystrokes until the target session is up
    # (it may still be launching `claude`), else the first utterances are lost.
    if SINK == "claude":
        while subprocess.run(["tmux", "has-session", "-t", SESSION],
                             stderr=subprocess.DEVNULL).returncode != 0:
            time.sleep(1)
    proc = subprocess.Popen(
        ["arecord", "-D", DEV, "-f", "S16_LE", "-c", "1", "-r", str(RATE), "-t", "raw"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    print("[crt-stt] sole reader on %s  model=%s  thr=%.1f%% (peak)"
          % (DEV, os.path.basename(MODEL), THRESH * 100))
    print("-" * 40)

    pre = deque(maxlen=PREROLL)
    in_utt = False
    buf = bytearray()
    above = 0
    sil = 0.0
    last_meter = 0.0
    try:
        while True:
            data = read_exact(proc.stdout, NBYTES)
            if len(data) < NBYTES:
                break
            a = array.array('h'); a.frombytes(data)
            peak = (max(abs(x) for x in a) / FULL) if a else 0.0

            now = time.time()
            if not in_utt and now - last_meter > 0.1:
                meter(peak); last_meter = now

            if not in_utt:
                pre.append(data)
                if peak >= THRESH:
                    above += 1
                    if above >= START:
                        in_utt = True
                        buf = bytearray(b"".join(pre)); pre.clear()
                        sil = 0.0
                else:
                    above = 0
            else:
                buf += data
                sil = sil + CHUNK_DUR if peak < THRESH else 0.0
                dur = len(buf) / 2 / RATE
                if sil >= TRAIL or dur >= MAXUTT:
                    in_utt = False; above = 0
                    if dur >= MINUTT:
                        emit(transcribe(bytes(buf)))
                    buf = bytearray()
    except KeyboardInterrupt:
        pass
    finally:
        try: proc.terminate()
        except Exception: pass


if __name__ == "__main__":
    main()
