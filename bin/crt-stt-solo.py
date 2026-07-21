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
import sys, os, array, time, wave, tempfile, subprocess, datetime, urllib.request, json, re
from collections import deque

# SINK: where recognized text goes.
#   stdout (default) -- scroll transcriptions; standalone STT/debug view.
#   claude           -- type into the tmux Claude Code pane + voice-control keys,
#                       exactly like stt-feed.sh, but from this SINGLE-reader
#                       engine (no dsnoop, no second reader) -- Approach B in
#                       AUDIO-DEBUG.md. Use via bin/crt-console-solo.sh.
#   secretary        -- fire-and-forget to crt-secretary.py (PARKING-LOT.md's
#                       "Local-first STT routing" plan, 2026-07-21) instead of
#                       typing straight into Claude's pane. Control keystrokes
#                       (yes/no/enter/etc, see CONTROL below) still go straight
#                       to tmux -- those are meta-interactions with whatever's
#                       on screen, not routable utterances. Non-blocking
#                       (Popen, not run) so the capture loop never stalls on
#                       crt-secretary.py's own Claude-escalation wait (up to
#                       CRT_SECRETARY_MAX_WAIT seconds). Deliberately NOT the
#                       default -- needs a live human to confirm playbooks
#                       actually fire correctly against real (not synthetic)
#                       transcriptions before it replaces `claude` as the
#                       boot default in crt-console.sh.
SINK    = os.environ.get("CRT_STT_SINK", "stdout")
SESSION = os.environ.get("CRT_TMUX_SESSION", "claude")
PANE    = os.environ.get("CRT_TMUX_PANE", "0")
BIN_DIR = os.path.dirname(os.path.abspath(__file__))

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


def send_to_secretary(text):
    """Fire-and-forget: hands the utterance to crt-secretary.py's local-
    playbook-first router (SECRETARY.md) instead of typing straight into
    Claude's pane -- PARKING-LOT.md's 'Local-first STT routing' plan.
    Popen, not run/check_call -- must never block this capture loop on
    crt-secretary.py's own Claude-escalation wait (up to
    CRT_SECRETARY_MAX_WAIT seconds for an unmatched request)."""
    subprocess.Popen(
        ["python3", os.path.join(BIN_DIR, "crt-secretary.py"), text],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

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
NR_AMT  = float(os.environ.get("CRT_NOISERED_AMT", "0.21"))  # noisered strength 0..1
# Live-tune control file: a knob/MIDI writer appends "<param> <value>" lines; the
# engine applies the change and flashes an on-screen bar. Empty = disabled.
CTL     = os.environ.get("CRT_CTL_FILE", "")
MUTED   = False
# "Ring" the phone: play a bursty tone N times; if the handset is picked up
# (voice detected) it stops immediately; if all rings finish unanswered, a
# message is printed (shows up on whatever screen this pane is on -- the
# CRT, if this is the visible tmux window). Triggered via the same CTL file
# ("ring <n>", default 4) so any script (e.g. bin/crt-ring.sh) can fire it
# without needing to touch the mic itself -- this process is the sole reader.
RING_ON_SECS  = float(os.environ.get("CRT_RING_ON_SECS", "1.5"))
RING_GAP_SECS = float(os.environ.get("CRT_RING_GAP_SECS", "2.5"))
RING_TIMEOUT_MSG = os.environ.get("CRT_RING_TIMEOUT_MSG", "[ring] no answer")
_ring_tone_path = None


def ring_tone_path():
    """Lazily synthesize a warbling ring tone once, cache the wav path."""
    global _ring_tone_path
    if _ring_tone_path and os.path.exists(_ring_tone_path):
        return _ring_tone_path
    fd, path = tempfile.mkstemp(suffix="_ring.wav"); os.close(fd)
    subprocess.run(["sox", "-n", path, "synth", str(RING_ON_SECS),
                    "sine", "900", "tremolo", "20", "80", "vol", "-6dB"],
                   stderr=subprocess.DEVNULL)
    _ring_tone_path = path
    return path
# Optional: send the WAV to a faster-whisper HTTP service running natively on
# dexter's Ryzen host instead of invoking whisper.cpp inside the (CPU-capped)
# guest. Same VAD/capture/denoise pipeline either way -- only the inference
# step moves. See bin/dexter-whisper-server.py. Empty = local whisper.cpp
# (default, unchanged behavior).
WHISPER_SERVER = os.environ.get("CRT_WHISPER_SERVER", "")   # e.g. http://192.168.0.22:8991/transcribe
WHISPER_SERVER_TIMEOUT = float(os.environ.get("CRT_WHISPER_SERVER_TIMEOUT", "8"))

CHUNK_DUR = CHUNK / RATE
THR_COL   = max(0, min(WIDTH - 1, int(THRESH / MFULL * WIDTH)))

# Flash state for the meter line -- shared by the knob/ctl HUD (apply_ctl_line)
# and by emit() flashing the raw STT output. Module-level (not main()-local)
# so emit() can set it directly; main()'s display loop just reads it.
hud_msg = ""
hud_until = 0.0
FLASH_SECS = float(os.environ.get("CRT_FLASH_SECS", "2.5"))

# Predictive-text double layer (2026-07-19, opt-in, off by default): the
# instant an utterance ends, flash a cheap local guess (bin/crt-predict.py,
# trained on this room's own ~/.crt/stt.log history) BEFORE whisper -- which
# genuinely takes real wall-clock time -- has run at all. emit() unconditionally
# overwrites hud_msg/hud_until with the real transcription once transcribe()
# returns, so the guess is always superseded, never mistaken for the real
# thing (marked with a "~" prefix regardless). This is PARKING-LOT.md's
# predictive-typing-then-overwrite aesthetic applied to the STT step itself.
# Off by default until someone can watch it run live and judge whether a
# wrong guess flashing for ~1s reads as charming or confusing (see
# PHILOSOPHY.md #6 on where the imperfection-as-character line is).
PREDICT_FLASH = os.environ.get("CRT_PREDICT_FLASH", "0") != "0"
PREDICT_BIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crt-predict.py")
PREDICT_TIMEOUT = float(os.environ.get("CRT_PREDICT_TIMEOUT", "0.3"))


def predictive_flash():
    """Best-effort: a slow/broken predictor must never delay or crash real
    transcription, so any failure here is silently swallowed."""
    global hud_msg, hud_until
    try:
        out = subprocess.run(["python3", PREDICT_BIN, "guess"],
                              capture_output=True, text=True,
                              timeout=PREDICT_TIMEOUT).stdout.strip()
    except Exception:
        return
    if out:
        hud_msg, hud_until = ("~ " + out)[:WIDTH + 20], time.time() + 10.0

# Sideband ambient-presence state (2026-07-20, opt-in, off by default --
# SIDEBAND.md). While CRT_SIDEBAND=1, this is the sole writer of
# "listening" (mic actively capturing, the default while running) and
# "thinking" (a real transcribe() call is in flight -- the same latency
# window predictive_flash() above addresses visually, now also audible).
# Never writes "idle"/"speaking" -- those belong to crt-idle-teaser.sh's
# screensaver gate and whatever's actually playing TTS, respectively, not
# to the mic-capture loop.
SIDEBAND = os.environ.get("CRT_SIDEBAND", "0") != "0"
SIDEBAND_SET_BIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crt-sideband-set.sh")
SIDEBAND_TIMEOUT = float(os.environ.get("CRT_SIDEBAND_SET_TIMEOUT", "0.5"))


def set_sideband_state(state):
    """Best-effort, like predictive_flash() -- a slow/broken sideband
    setter must never delay real transcription."""
    if not SIDEBAND:
        return
    try:
        subprocess.run(["bash", SIDEBAND_SET_BIN, state],
                        capture_output=True, timeout=SIDEBAND_TIMEOUT)
    except Exception:
        pass

# STT text always gets logged to CRT_STT_LOG (for the claude-feed merge to
# read), but only gets PRINTED/scrolled to this pane's terminal (persisting
# in scrollback) when debug mode is on. Off by default: raw STT should only
# flash briefly, never linger, to mask recognition errors -- the merged,
# cleaned-up text from claude is what should persist on screen instead.
STT_LOG = os.environ.get("CRT_STT_LOG", os.path.expanduser("~/.crt/stt.log"))
STT_DEBUG_PERSIST = os.environ.get("CRT_STT_DEBUG_PERSIST", "0") != "0"

# whisper's canonical noise/silence hallucinations -- never emit these.
HALLU = set("you thankyou thanks thankyouforwatching bye music musicplaying "
            "cricketschirping silence blankaudio sound soundeffects applause "
            "inaudible foreignspeech speaking".split())

# STT gate (FOCUS.md "Now (core STT)" / STT gate, 2026-07-20, Zach): without
# this, every utterance that clears VAD becomes a live Claude Code turn --
# including room chatter never addressed to the console. Opt-in, default
# off -- not hardware-verified against real room noise yet (see
# nightly-batch.md's acceptance-bar note); the raw always-escalate path
# below is unchanged when this is off. Only gates the free-text ->
# Claude-turn path, not single-word CONTROL keystrokes (see emit()) --
# those answer a prompt already on screen mid-interaction and shouldn't
# need the wake word repeated.
GATE       = os.environ.get("CRT_STT_GATE", "0") != "0"
WAKE_WORD  = os.environ.get("CRT_WAKE_WORD", "claude").lower()
GATE_LOG   = os.environ.get("CRT_STT_GATE_LOG", os.path.expanduser("~/.crt/thoughts.log"))
FIXUPS_PATH = os.environ.get("CRT_STT_FIXUPS",
                              os.path.join(os.path.dirname(os.path.abspath(__file__)), "stt-fixups.json"))


def load_fixups(path):
    """stt-fixups.json: {lowercased misheard fragment: {"intent": ..., ...}}.
    Ignores keys starting with "_" (the file's own "_comment" doc key) and
    tolerates a missing/malformed file -- the gate degrades to exact-word
    matching only, it doesn't fail closed or crash the whole engine."""
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if not k.startswith("_")}


FIXUPS = load_fixups(FIXUPS_PATH)


def _contains_phrase(words, phrase):
    """Whole-word containment check: `phrase` (space-separated) must appear
    as a contiguous run of whole words in `words`, not as a bare substring
    -- else a fixup fragment like "slide" would false-positive inside an
    unrelated word like "landslide"."""
    phrase_words = phrase.split()
    n = len(phrase_words)
    return any(words[i:i + n] == phrase_words for i in range(len(words) - n + 1))


def addressed_to_console(text, wake_word=WAKE_WORD, fixups=FIXUPS):
    """True if `text` was actually addressed to the console: the wake word
    appears as a whole word, or a stt-fixups.json fragment whose learned
    intent IS the wake word appears (e.g. "slide" -> confirmed mishear of
    "claude", see stt-fixups.json) -- makes that fixup entry load-bearing
    for the gate, not just a documentation note for a human reader.
    Whisper output rarely carries reliable punctuation, but a stray comma
    ("hey claude, run the tests") shouldn't defeat the match -- tokenize on
    word characters only rather than plain str.split()."""
    words = re.findall(r"[a-z0-9']+", text.lower())
    if wake_word in words:
        return True
    return any(info.get("intent") == wake_word and _contains_phrase(words, fragment)
                for fragment, info in fixups.items())


def read_exact(f, n):
    b = bytearray()
    while len(b) < n:
        c = f.read(n - len(b))
        if not c:
            break
        b += c
    return bytes(b)


def meter(peak):
    thr_col = max(0, min(WIDTH - 1, int(THRESH / MFULL * WIDTH)))  # tracks live THRESH
    filled = max(0, min(WIDTH, int(peak / MFULL * WIDTH)))
    bar = ''.join('#' if i < filled else ('|' if i == thr_col else '.')
                  for i in range(WIDTH))
    tag = 'MUTE' if MUTED else ('TALK' if filled > thr_col else '    ')
    sys.stdout.write('\rMIC [%s] %5.1f%% %s' % (bar, peak * 100, tag))
    sys.stdout.flush()


# Live-tunable params driven by the control file / MIDI knobs. Each entry:
#   name -> (global var, lo, hi, unit, value shown = raw*scale)
# THRESH is stored as a fraction but shown/entered as a percent (scale 100).
CTL_MAP = {
    "vad":   ("THRESH", 0.3, 8.0, "%",  100.0),
    "nr":    ("NR_AMT", 0.0, 0.3, "",   1.0),
    "trail": ("TRAIL",  0.3, 2.0, "s",  1.0),
    "min":   ("MINUTT", 0.2, 1.0, "s",  1.0),
}


def hud_bar(name, shown, lo, hi, unit):
    w = 14
    frac = 0.0 if hi == lo else (shown - lo) / (hi - lo)
    filled = max(0, min(w, round(frac * w)))
    bar = "#" * filled + "." * (w - filled)
    return "%-5s[%s] %5.2f%s" % (name.upper(), bar, shown, unit)


def apply_ctl_line(line):
    """Parse a '<param> <value>' control line, clamp+apply, return a HUD string.
    Values are given in display units (vad in %, trail/min in s, nr 0-0.3).
    Special: 'mute 1|0'."""
    global THRESH, NR_AMT, TRAIL, MINUTT, MUTED
    parts = line.split()
    if len(parts) < 2:
        return None
    name, raw = parts[0].lower(), parts[1]
    if name == "mute":
        MUTED = raw not in ("0", "off", "false")
        return "MUTE  %s" % ("ON" if MUTED else "off")
    if name not in CTL_MAP:
        return None
    gvar, lo, hi, unit, scale = CTL_MAP[name]
    try:
        shown = float(raw.rstrip("%s"))
    except ValueError:
        return None
    shown = max(lo, min(hi, shown))
    globals()[gvar] = shown / scale
    return hud_bar(name, shown, lo, hi, unit)


def transcribe_remote(wav_path):
    """POST the WAV to dexter's faster-whisper service; fall back to empty
    (silently dropped, same as any other transcription failure) on any error
    -- never block the capture loop on a flaky network call."""
    import json
    try:
        with open(wav_path, "rb") as f:
            data = f.read()
        req = urllib.request.Request(WHISPER_SERVER, data=data,
                                      headers={"Content-Type": "audio/wav"})
        with urllib.request.urlopen(req, timeout=WHISPER_SERVER_TIMEOUT) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        return result.get("text", "")
    except Exception:
        return ""


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
            effects += ["noisered", NR_PROF, "%.3f" % NR_AMT]
        if NORM:
            effects += ["gain", "-n", "-1"]
        if effects:
            norm = raw[:-4] + "_f.wav"
            if subprocess.run(["sox", raw, norm] + effects,
                              stderr=subprocess.DEVNULL).returncode == 0:
                feed = norm
        if WHISPER_SERVER:
            return transcribe_remote(feed)
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


def emit(text, peak=1.0):
    key = "".join(c for c in text.lower() if c.isalpha())
    if not text or len(key) < 2 or key in HALLU:
        return
    # Drop non-speech sound tags whisper emits on noise: "(metal clanging)",
    # "[BLANK_AUDIO]", "*applause*", "♪ music ♪" -- fully bracket/symbol-wrapped.
    t = text.strip()
    if t and t[0] in "([*♪" and t[-1] in ")]*♪":
        return
    global hud_msg, hud_until
    # How much of the utterance actually flashes on screen scales with how
    # loud it was spoken -- quiet mumbling shows a word or two, a loud/clear
    # utterance shows the whole thing. The full text still goes to the log
    # and to claude either way; this only affects the ephemeral flash.
    loud_frac = min(1.0, peak / MFULL)
    words = t.split()
    n_show = max(1, round(len(words) * loud_frac))
    shown = " ".join(words[:n_show]) + (" .." if n_show < len(words) else "")
    hud_msg, hud_until = shown[:WIDTH + 20], time.time() + FLASH_SECS
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    sys.stdout.write('\r' + ' ' * (WIDTH + 20) + '\r')   # clear meter line
    try:
        os.makedirs(os.path.dirname(STT_LOG), exist_ok=True)
        with open(STT_LOG, "a") as f:
            f.write("%s  %s\n" % (ts, text))
    except OSError:
        pass
    if SINK in ("claude", "secretary"):
        is_control = " " not in text and key in CONTROL
        if GATE and not is_control and not addressed_to_console(text):
            if STT_DEBUG_PERSIST:
                print("%s  (gated, no wake word) %s" % (ts, text))
            try:
                os.makedirs(os.path.dirname(GATE_LOG), exist_ok=True)
                with open(GATE_LOG, "a") as f:
                    f.write("%s  [stt-gate] dropped (no wake word): %s\n" % (ts, text))
            except OSError:
                pass
            return
        label = "(key %s)" % CONTROL[key] if is_control else "->"
        if STT_DEBUG_PERSIST:
            print("%s  %s %s" % (ts, label, text))
        # Control keystrokes are meta-interactions with whatever's already
        # on screen (confirm a prompt, jog scroll position, etc) -- those
        # always go straight to tmux even in secretary mode, never through
        # the playbook router, same as the claude sink always did.
        if SINK == "secretary" and not is_control:
            send_to_secretary(text)
        else:
            send_to_claude(text, key)
    elif STT_DEBUG_PERSIST:
        print("%s  %s" % (ts, text))


def main():
    # claude/secretary sinks: don't start feeding keystrokes/utterances until
    # the target session is up (it may still be launching `claude`), else
    # the first utterances are lost. secretary mode still needs window 0
    # for control keystrokes (see send_to_claude/CONTROL above).
    if SINK in ("claude", "secretary"):
        while subprocess.run(["tmux", "has-session", "-t", SESSION],
                             stderr=subprocess.DEVNULL).returncode != 0:
            time.sleep(1)
    proc = subprocess.Popen(
        ["arecord", "-D", DEV, "-f", "S16_LE", "-c", "1", "-r", str(RATE), "-t", "raw"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    print("[crt-stt] sole reader on %s  model=%s  thr=%.1f%% (peak)"
          % (DEV, os.path.basename(MODEL), THRESH * 100))
    print("-" * 40)
    set_sideband_state("listening")   # no-op unless CRT_SIDEBAND=1

    pre = deque(maxlen=PREROLL)
    in_utt = False
    utt_peak = 0.0
    buf = bytearray()
    above = 0
    sil = 0.0
    last_meter = 0.0
    global hud_msg, hud_until
    ctl_pos = 0
    ring_state = None     # None | "tone" | "gap"
    ring_remaining = 0
    ring_phase_until = 0.0
    ring_proc = None
    try:
        while True:
            data = read_exact(proc.stdout, NBYTES)
            if len(data) < NBYTES:
                break
            a = array.array('h'); a.frombytes(data)
            peak = (max(abs(x) for x in a) / FULL) if a else 0.0

            now = time.time()

            # Live-tune: a knob/MIDI writer appends "<param> <value>" to CTL.
            # On change, apply it and flash the level bar over the meter.
            if CTL:
                try:
                    sz = os.path.getsize(CTL)
                    if sz < ctl_pos:          # file truncated/rotated -> restart
                        ctl_pos = 0
                    if sz > ctl_pos:
                        with open(CTL) as fh:
                            fh.seek(ctl_pos)
                            chunk = fh.read()
                            ctl_pos = fh.tell()
                        for ln in chunk.splitlines():   # apply every new line once
                            if ln.startswith("ring"):
                                parts = ln.split()
                                n = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 4
                                ring_state, ring_remaining = "tone", n
                                ring_phase_until = now + RING_ON_SECS
                                ring_proc = subprocess.Popen(
                                    ["aplay", "-q", ring_tone_path()],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                print("[ring] ringing (%d)" % n)
                                continue
                            r = apply_ctl_line(ln)
                            if r:
                                hud_msg, hud_until = r, now + 1.6
                except OSError:
                    pass

            if ring_state is not None:
                if ring_state == "gap" and not MUTED and peak >= THRESH:
                    if ring_proc and ring_proc.poll() is None:
                        ring_proc.terminate()
                    ring_state, ring_proc = None, None
                    print("[ring] answered")
                elif now >= ring_phase_until:
                    if ring_state == "tone":
                        ring_state = "gap"
                        ring_phase_until = now + RING_GAP_SECS
                    else:   # gap elapsed, unanswered
                        ring_remaining -= 1
                        if ring_remaining > 0:
                            ring_state = "tone"
                            ring_phase_until = now + RING_ON_SECS
                            ring_proc = subprocess.Popen(
                                ["aplay", "-q", ring_tone_path()],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        else:
                            ring_state, ring_proc = None, None
                            print(RING_TIMEOUT_MSG)
                continue   # ringing suppresses normal VAD/utterance handling

            if not in_utt and now - last_meter > 0.1:
                if now < hud_until:
                    sys.stdout.write('\r%-40s' % hud_msg[:40]); sys.stdout.flush()
                else:
                    meter(peak)
                last_meter = now

            if not in_utt:
                pre.append(data)
                if not MUTED and peak >= THRESH:
                    above += 1
                    if above >= START:
                        in_utt = True
                        buf = bytearray(b"".join(pre)); pre.clear()
                        sil = 0.0
                        utt_peak = peak
                else:
                    above = 0
            else:
                buf += data
                utt_peak = max(utt_peak, peak)
                sil = sil + CHUNK_DUR if peak < THRESH else 0.0
                dur = len(buf) / 2 / RATE
                if sil >= TRAIL or dur >= MAXUTT:
                    in_utt = False; above = 0
                    if dur >= MINUTT:
                        if PREDICT_FLASH:
                            predictive_flash()
                        set_sideband_state("thinking")
                        emit(transcribe(bytes(buf)), utt_peak)
                        set_sideband_state("listening")
                    buf = bytearray()
    except KeyboardInterrupt:
        pass
    finally:
        try: proc.terminate()
        except Exception: pass


if __name__ == "__main__":
    main()
