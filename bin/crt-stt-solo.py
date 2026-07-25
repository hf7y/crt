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
import sys, os, array, time, wave, tempfile, subprocess, datetime, urllib.request, urllib.error, json, re, signal
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


# Earcon feedback added 2026-07-23 live-tuning session, per Zach's direct
# ask for beeps at three pipeline stages: audio-threshold (VAD detects an
# utterance starting), the STT gate (wake word recognized or not), and
# the "watchword" (single-word CONTROL keystroke) gate -- three distinct
# code paths above, not one. Popen fire-and-forget like send_to_secretary
# -- an earcon must NEVER add latency to (or risk blocking) the sole mic
# reader's capture loop. Default device is the handset (--device handset,
# see crt-earcon.sh's 2026-07-23 device-routing fix) since that's what
# the person actually holding it hears.
#
# EARCON_ON_THRESHOLD defaults OFF: this fires on every utterance the mic
# picks up, including all the room chatter that never has a wake word --
# on by default this would be near-constant noise (see stt.log/thoughts.log
# from tonight's session for just how much of that there is). Opt in only
# if you actually want an audible "still capturing" tick per utterance.
EARCON_ON_THRESHOLD = os.environ.get("CRT_EARCON_ON_THRESHOLD", "0") == "1"
EARCON_ON_ADDRESSED = os.environ.get("CRT_EARCON_ON_ADDRESSED", "1") == "1"
EARCON_ON_CONTROL = os.environ.get("CRT_EARCON_ON_CONTROL", "1") == "1"
EARCON_DEVICE = os.environ.get("CRT_EARCON_DEVICE", "handset")


def play_earcon(name):
    try:
        subprocess.Popen(
            [os.path.join(BIN_DIR, "crt-earcon.sh"), name, "--device", EARCON_DEVICE],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass

RATE   = 16000
CHUNK  = int(RATE * 0.1)                 # 100 ms analysis window
NBYTES = CHUNK * 2                        # S16_LE mono
FULL   = 32768.0

# Capture device resolution (2026-07-23 07:10/07:20 notes): a hardcoded ALSA
# card INDEX (plughw:0,0) silently breaks whenever a USB replug/reboot
# renumbers cards -- hit live on potato when "KT USB Audio" moved from card 0
# to card 1 mid-session. resolve_capture_device_by_name() parses `arecord -l`
# for a card whose name matches CRT_AUDIO_DEV_NAME (default "USB Audio", case-
# insensitive) and returns "plughw:<card>,<device>" for it. CRT_AUDIO_DEV
# stays a hard override on top of this -- if set, it always wins outright and
# name-resolution never runs (same "never remove the manual escape hatch"
# posture as stt-fixups.json's tiered confidence).
DEV_NAME_PATTERN = os.environ.get("CRT_AUDIO_DEV_NAME", "USB Audio")
DEV_FALLBACK = "plughw:0,0"

ARECORD_CARD_RE = re.compile(
    r"^card (\d+):.*\[(.*?)\],\s*device (\d+):", re.IGNORECASE)


def resolve_capture_device_by_name(arecord_l_output, name_pattern=DEV_NAME_PATTERN,
                                    fallback=DEV_FALLBACK):
    """Pure string parse of `arecord -l` CAPTURE-device listing output --
    returns 'plughw:<card>,<device>' for the first card whose bracketed name
    contains name_pattern (case-insensitive). If nothing matches by name but
    the listing DOES name capture cards, returns the first one listed rather
    than `fallback`: every card in this listing can at least be opened for
    capture, whereas the hardcoded fallback index is exactly what broke on
    potato (plughw:0,0 there is the onboard playback-only card, absent from
    this listing entirely -- arecord on it exits instantly with no capture).
    `fallback` is only for a listing with no cards at all. Does not touch
    hardware itself; callers pass in the already-captured `arecord -l` text
    so this stays unit-testable."""
    if not arecord_l_output:
        return fallback
    needle = name_pattern.lower()
    first = None
    for line in arecord_l_output.splitlines():
        m = ARECORD_CARD_RE.match(line.strip())
        if not m:
            continue
        dev = "plughw:%s,%s" % (m.group(1), m.group(3))
        if needle in m.group(2).lower():
            return dev
        if first is None:
            first = dev
    return first if first else fallback


def _detect_capture_device():
    explicit = os.environ.get("CRT_AUDIO_DEV")
    if explicit:
        return explicit
    # Broad except deliberately: this runs at import time, so anything going
    # wrong here (arecord missing, a test harness monkeypatching subprocess
    # globally, whatever) must fall back quietly rather than ever crash the
    # whole process -- same posture as set_sideband_state()/predictive_flash().
    try:
        out = subprocess.run(["arecord", "-l"], capture_output=True,
                              text=True, timeout=5).stdout
    except Exception:
        return DEV_FALLBACK
    dev = resolve_capture_device_by_name(out)
    # Say so when we didn't get what we asked for. Guessing a device is a
    # legitimate degraded mode, but doing it silently is how "the console
    # just stopped hearing anything" turns into an evening of debugging.
    if DEV_NAME_PATTERN.lower() not in (out or "").lower():
        sys.stderr.write(
            "[crt-stt] WARNING: no capture card matching %r in `arecord -l`; "
            "falling back to %s. Set CRT_AUDIO_DEV to pin one explicitly, or "
            "CRT_AUDIO_DEV_NAME to match this box's adapter.\n"
            % (DEV_NAME_PATTERN, dev))
    return dev


DEV    = _detect_capture_device()   # single reader; NOT dsnoop
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
# Reference count behind MUTED, not a plain last-write-wins flag: if a TTS
# reply and an earcon both duck capture around the same handset playback
# (2026-07-24 fe46ac1's known limitation), one finishing and writing
# "mute 0" must not unmute while the other duck is still active. Each
# "mute 1"/"mute 0" line increments/decrements this counter instead of
# setting an absolute state; MUTED is true iff the count is still > 0.
# Also makes crt-midi-knobs.py's manual mute toggle compose correctly with
# an in-flight duck instead of racing it.
MUTE_COUNT = 0
# Safety net on that reference count (2026-07-25). Ref-counting made
# overlapping ducks compose, but it also removed the old flag's accidental
# self-healing: with last-write-wins, ANY later "mute 0" restored capture,
# so a duck whose producer died mid-playback (aplay SIGKILLed, crt-tts.py
# killed before its finally:, crt-earcon.sh's EXIT trap skipped on an
# untrapped fatal signal) got cleaned up by the next sound that played.
# With a counter, that leaked increment never comes back down and the
# console goes permanently deaf -- exactly this project's worst failure
# class (silent, no error, looks like the mic died). So: a mute is held for
# at most CRT_CTL_MUTE_MAX_SECS of wall clock, then force-cleared LOUDLY.
# Longer than any real handset duck (a tone is <1s, a spoken reply a few
# seconds); 0 disables the watchdog. Clearing early only risks VAD hearing
# our own playback -- which this adapter can barely record anyway (0.1x,
# the measurement that motivated the duck) -- so the safe direction is
# unmuting, not staying muted.
MUTE_MAX_SECS = float(os.environ.get("CRT_CTL_MUTE_MAX_SECS", "45"))
MUTE_SINCE = 0.0
# How long an ALREADY-OPEN utterance may stay frozen by a duck that arrived
# mid-utterance before we give up and close it out (2026-07-25). See
# utt_chunk() for what "frozen" means and why the duck is not simply ignored
# once speech has started. 0 = never close on a duck alone (freeze until it
# lifts, with MUTE_MAX_SECS above as the only backstop).
#
# 2.0s default: the reachable mid-utterance duck today is one short earcon
# (~0.3s), so this never fires in normal use; it exists for the long case --
# a multi-sentence spoken reply, where each sentence ducks separately and the
# speaker can start talking in a gap between them. Once playback has covered
# two seconds of an open utterance, whatever was being said is over as far as
# this buffer is concerned, and holding it open only delays the transcription
# of the speech we DID capture.
MUTE_UTT_MAX_SECS = float(os.environ.get("CRT_MUTE_UTT_MAX_SECS", "2.0"))
# Control lines that are MOMENTARY (an edge/command owned by a live
# producer) rather than a LEVEL that should persist. The CTL file is an
# append-only log and main() replays it from byte 0 on startup, which is
# deliberate for levels -- a threshold tuned by knob survives a restart.
# Replaying momentary commands is nonsense and was actively harmful: one
# leaked "mute 1" left in the history muted capture on EVERY subsequent
# start (and stayed leaked, since the file is never truncated), and a
# stale "ring 4" re-rang the phone at every boot.
MOMENTARY_CTL = ("mute", "ring")
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

# Arm-window / wake-judge wiring (2026-07-23, see bin/crt-wake-arm.py's
# own header for the full story -- this is the "sticky conversation
# window" fix, wired to crt-wake-judge.py's dormant autonomous tuning
# judge). Opt-in, default OFF: with CRT_WAKE_ARM_ENABLED unset, every
# line below that references ARM_STATE/wake_arm is dead code and the
# gate behaves EXACTLY as it did before this change -- do not flip the
# default on without a live session confirming the arm window feels
# right (see crt-wake-arm.py's own STATUS note).
WAKE_ARM_ENABLED = os.environ.get("CRT_WAKE_ARM_ENABLED", "0") == "1"
if WAKE_ARM_ENABLED:
    import importlib.util as _importlib_util
    _wa_spec = _importlib_util.spec_from_file_location(
        "crt_wake_arm", os.path.join(os.path.dirname(os.path.abspath(__file__)), "crt-wake-arm.py"))
    wake_arm = _importlib_util.module_from_spec(_wa_spec)
    _wa_spec.loader.exec_module(wake_arm)
    ARM_STATE = wake_arm.ArmState()


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


def log_user_thought(text, log_path=None, timestamp=None):
    """Writes a '[you] ...' line to the same log crt-monologue.py already
    tails for Claude's own replies (crt-claude-bridge.py's thoughts.log) --
    the window-1 gap flagged repeatedly ("no visual signal of the USER's
    own speech"). Best-effort, same convention as every other logging
    write in this project (a broken write here must never block the real
    STT->secretary/claude routing that follows it)."""
    log_path = log_path or GATE_LOG
    ts = timestamp or time.strftime("%H:%M:%S")
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a") as f:
            f.write("%s  [you] %s\n" % (ts, text))
    except OSError:
        pass


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


def classify_wake_match(text, wake_word=WAKE_WORD, fixups=FIXUPS):
    """Only called when WAKE_ARM_ENABLED -- identifies WHICH word/fragment
    made addressed_to_console() true, so the arm-window has enough detail
    to hand crt-wake-judge.py a real match-kind/matched-word. Deliberately
    kept in sync with addressed_to_console()'s own exact/fixup logic by
    hand (same two checks) rather than refactored to share code, since
    addressed_to_console() is the proven, unchanged-tonight gate function
    and this is new, opt-in, unverified code -- not worth the risk of a
    shared-code regression in the existing gate for this. Returns
    ("exact", None, matched_word) or (None, None, None); no pool/fuzzy
    kind yet -- crt-wake-pool.py isn't wired into the gate itself yet,
    see FOCUS.md."""
    words = re.findall(r"[a-z0-9']+", text.lower())
    if wake_word in words:
        return "exact", None, wake_word
    for fragment, info in fixups.items():
        if info.get("intent") == wake_word and _contains_phrase(words, fragment):
            return "exact", None, fragment
    return None, None, None


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


def is_momentary_ctl(line):
    """True if this control line is a one-shot command (see MOMENTARY_CTL)
    rather than a level to restore. Used to skip such lines while replaying
    the CTL file's existing history at startup."""
    parts = line.split()
    return bool(parts) and parts[0].lower() in MOMENTARY_CTL


def check_mute_timeout(now):
    """Force-clear a mute that has been held past MUTE_MAX_SECS -- a duck
    whose producer died without writing its matching 'mute 0'. Returns a
    warning string when it fires (caller prints/HUDs it), else None."""
    global MUTED, MUTE_COUNT, MUTE_SINCE
    if not MUTED or MUTE_MAX_SECS <= 0:
        return None
    held = now - MUTE_SINCE
    if held < MUTE_MAX_SECS:
        return None
    stuck = MUTE_COUNT
    MUTE_COUNT, MUTED, MUTE_SINCE = 0, False, 0.0
    return ("[crt-stt] WARNING: capture mute stuck %.0fs (%d unreleased duck%s) "
            "-- force-unmuting; a handset duck leaked its 'mute 0'"
            % (held, stuck, "" if stuck == 1 else "s"))


def utt_chunk(muted, peak, sil, mute_hold, dur):
    """Decide what one 100ms capture chunk does to an ALREADY-OPEN utterance.

    Pure; main()'s loop owns the actual byte buffer. Returns
    ``(keep, ended, sil, mute_hold)`` -- keep the chunk's audio or drop it,
    and whether the utterance is over after it.

    `dur` is the buffered duration BEFORE this chunk (the MAXUTT cap is
    checked against what the buffer becomes if the chunk is kept).

    The mute half is the point of this function (2026-07-25, from Zach's note
    on the previous cycle's report). The VAD's start gate has always checked
    MUTED -- `if not MUTED and peak >= THRESH` -- so an utterance never BEGINS
    during handset playback. Nothing checked it again afterwards, so a duck
    arriving mid-utterance did not stop the buffering, and our own playback
    was recorded into the middle of the speaker's sentence and sent to
    whisper as if they had said it.

    Three behaviours were possible and this is why it is the middle one:

      buffer it (what it did) -- whisper transcribes our own earcon/reply as
        words in the user's utterance. Worst of the three.
      close the utterance at the duck -- truncates. With
        CRT_EARCON_ON_THRESHOLD=1 the "heard" earcon fires at the very
        instant of onset, so this would cut EVERY utterance to nothing.
      freeze and excise (this) -- ducked chunks are dropped, and the silence
        timer does not advance while they are, so playback neither enters the
        buffer nor ends the utterance. Speech either side of a short duck is
        spliced. A duck that outlasts MUTE_UTT_MAX_SECS ends the utterance
        normally, so a long reply cannot hold one open indefinitely.

    Excising can drop real speech if the speaker talks straight through the
    duck. That is accepted deliberately: this adapter records its own
    playback at ~0.1x (the measurement the duck exists for), so those frames
    are mostly playback anyway, and a short splice is far kinder to whisper
    than a beep or half a spoken reply sitting inside the sentence. Whether
    the 2.0s bound is right is a by-ear call for a live potato session.
    """
    if muted:
        mute_hold += CHUNK_DUR
        return False, (0 < MUTE_UTT_MAX_SECS <= mute_hold), sil, mute_hold
    sil = sil + CHUNK_DUR if peak < THRESH else 0.0
    return True, (sil >= TRAIL or dur + CHUNK_DUR >= MAXUTT), sil, 0.0


def apply_ctl_line(line, now=None):
    """Parse a '<param> <value>' control line, clamp+apply, return a HUD string.
    Values are given in display units (vad in %, trail/min in s, nr 0-0.3).
    Special: 'mute 1|0'."""
    global THRESH, NR_AMT, TRAIL, MINUTT, MUTED, MUTE_COUNT, MUTE_SINCE
    parts = line.split()
    if len(parts) < 2:
        return None
    name, raw = parts[0].lower(), parts[1]
    if name == "mute":
        if raw not in ("0", "off", "false"):
            if MUTE_COUNT == 0:
                MUTE_SINCE = time.time() if now is None else now
            MUTE_COUNT += 1
        else:
            MUTE_COUNT = max(0, MUTE_COUNT - 1)
        MUTED = MUTE_COUNT > 0
        if not MUTED:
            MUTE_SINCE = 0.0
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
    """POST the WAV to mandark's faster-whisper service and return its text.

    Returns None when we could not get an answer out of the server at all
    (unreachable, timeout, HTTP error, unparseable body, no "text" key) and
    "" only when the server genuinely transcribed the clip as nothing.
    Until 2026-07-25 this returned "" for both, which made an unreachable
    mandark indistinguishable from a silent room -- the console just stopped
    responding, with no line anywhere saying why (FOCUS.md 2026-07-23 00:40).
    Same sentinel convention as crt-secretary.py's capture_pane(): failure
    gets its own value so no caller can reason confidently from it.

    Still never blocks or raises: a flaky network call must not take the
    capture loop down with it, only stop lying about what happened."""
    import json
    try:
        with open(wav_path, "rb") as f:
            data = f.read()
        req = urllib.request.Request(WHISPER_SERVER, data=data,
                                      headers={"Content-Type": "audio/wav"})
        with urllib.request.urlopen(req, timeout=WHISPER_SERVER_TIMEOUT) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        if not isinstance(result, dict) or "text" not in result:
            return None
        text = result["text"]
        return text if isinstance(text, str) else None
    except urllib.error.HTTPError as e:
        # An HTTPError is an open file-like object holding a spooled temp
        # file. A whisper server that 500s on every utterance would leak one
        # per utterance until the GC happens to collect them -- on a Pi with
        # 183MB free, that is not a hypothetical.
        try:
            e.close()
        except Exception:
            pass
        return None
    except Exception:
        return None


def transcribe(frames):
    """Return the transcription of these frames, "" if the recogniser ran and
    heard nothing, or None if the recognition step itself failed (see
    transcribe_remote). The caller must not treat None as silence."""
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
        run = subprocess.run([WBIN, "-m", MODEL, "-f", feed, "-nt", "-np"],
                             capture_output=True, text=True)
        # A whisper-cli that exits nonzero produced no transcription; its
        # empty stdout is not a silent room either (missing model file, bad
        # WAV, OOM on the Pi). Same reason the remote branch returns None.
        if run.returncode != 0:
            return None
        return " ".join(run.stdout.split())
    except Exception:
        return None
    finally:
        for p in (raw, norm):
            if p:
                try: os.unlink(p)
                except OSError: pass


# How often a continuing transcription outage repeats itself on the pane.
# The first failure always prints; after that only every Nth, so a mandark
# that is down for an hour leaves a readable trail instead of burying the
# capture pane -- and never goes fully quiet either.
TRANSCRIBE_FAIL_REPEAT = int(os.environ.get("CRT_TRANSCRIBE_FAIL_REPEAT", "10"))


def transcribe_failure_report(fails, remote_url):
    """(hud, line) for an utterance that was heard but not transcribed.

    Pure string builder, same posture as capture_death_report() above: the
    wording is testable without a dead whisper server. `line` is None when
    this failure is being folded into an ongoing outage rather than
    announced again. The HUD half matters most -- the person is looking at
    the tube, not at this pane's scrollback -- so it always says something,
    and it says the utterance was LOST, not that nothing was heard."""
    where = ("whisper server %s" % remote_url) if remote_url else ("local whisper %s" % WBIN)
    hud = "! stt lost it" if fails <= 1 else "! stt lost it x%d" % fails
    line = None
    if fails == 1 or (TRANSCRIBE_FAIL_REPEAT > 0 and fails % TRANSCRIBE_FAIL_REPEAT == 0):
        line = ("[crt-stt] TRANSCRIPTION FAILED (%d utterance%s in a row) -- %s "
                "gave no answer. The mic is fine and the audio was captured; "
                "nothing came back to say. This is NOT a silent room."
                % (fails, "" if fails == 1 else "s", where))
    return hud, line


def transcribe_recovery_report(fails):
    """The other half: say when it starts working again, so the pane never
    ends on a failure line that has since stopped being true."""
    if fails <= 0:
        return None
    return ("[crt-stt] transcription recovered after %d lost utterance%s"
            % (fails, "" if fails == 1 else "s"))


def report_line(line):
    """Put a diagnostic on this pane without taking the capture loop down.

    Guarded for the same reason the "stopped; released" message at the end of
    main() is: on a `tmux kill-window` the pty is already gone, and an
    unguarded write raises EIO. A message about a failure must not become a
    second failure. Clears the meter line first, like emit() does, so the
    text isn't overwritten by the next meter repaint."""
    try:
        sys.stdout.write('\r' + ' ' * (WIDTH + 20) + '\r')
        sys.stdout.flush()
        sys.stderr.write(line + "\n")
        sys.stderr.flush()
    except OSError:
        pass


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

        # Arm-window follow-up check (opt-in, WAKE_ARM_ENABLED, see
        # bin/crt-wake-arm.py) -- MUST run before the normal gate below,
        # since its entire point is letting a follow-up through WITHOUT
        # repeating the wake word. When disarmed/expired/disabled this is
        # a no-op and every line below is completely unaffected -- the
        # existing gate logic is untouched otherwise.
        if WAKE_ARM_ENABLED and not is_control and \
                wake_arm.consume_arm_with_followup(ARM_STATE, text):
            if STT_DEBUG_PERSIST:
                print("%s  (arm follow-up) %s" % (ts, text))
            log_user_thought(text)
            if EARCON_ON_ADDRESSED:
                play_earcon("addressed")
            if SINK == "secretary":
                send_to_secretary(text)
            else:
                send_to_claude(text, key)
            return

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
        if EARCON_ON_CONTROL and is_control:
            play_earcon("control")
        elif EARCON_ON_ADDRESSED and not is_control:
            play_earcon("addressed")
        if WAKE_ARM_ENABLED and not is_control:
            kind, source, word = classify_wake_match(text)
            if kind:
                ARM_STATE.arm(text, kind, source, word)
        label = "(key %s)" % CONTROL[key] if is_control else "->"
        if STT_DEBUG_PERSIST:
            print("%s  %s %s" % (ts, label, text))
        # Window 1 ("mono") previously only ever showed Claude's own
        # replies (crt-claude-bridge.py tailing its transcript) -- flagged
        # repeatedly in HANDOFF.md/crt-console.sh as the missing other half
        # of the conversation. Free-text utterances that actually got past
        # the gate (not bare control keystrokes -- those're just yes/no/up/
        # down, not worth the clutter) get a tagged line into the same
        # thoughts.log crt-monologue.py already renders, so the person's
        # own speech and Claude's reply show up interleaved.
        if not is_control:
            log_user_thought(text)
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


def capture_death_report(dev, rc, stderr_text, seconds_alive):
    """The message printed when the arecord that feeds this whole console
    stops producing audio (2026-07-23 07:10 note, still open until now: the
    process "restarted silently exits (no error, no capture) rather than
    failing loudly" -- resolving the device by name fixed one CAUSE of that,
    never the silence itself). Pure string builder so the wording is
    testable without killing a real capture. Exit code, not just a print:
    a dead-and-gone process is visible to a supervisor/`tmux respawn-pane
    -k`; a live process that hears nothing forever is not."""
    lines = ["", "[crt-stt] CAPTURE DIED -- no more audio from %s" % dev]
    if seconds_alive is not None and seconds_alive < 2.0:
        lines.append("[crt-stt] it never produced any audio at all (%.1fs) -- "
                     "that device probably can't be opened for capture."
                     % seconds_alive)
        lines.append("[crt-stt] check `arecord -l`; pin a known-good one with "
                     "CRT_AUDIO_DEV=plughw:<card>,<device>.")
    else:
        lines.append("[crt-stt] ran %s before dying (USB replug? device grabbed "
                     "by another reader?)."
                     % ("%.0fs" % seconds_alive if seconds_alive is not None else "a while"))
    if rc is not None:
        lines.append("[crt-stt] arecord exit code: %s" % rc)
    err = (stderr_text or "").strip()
    if err:
        for ln in err.splitlines()[-4:]:
            lines.append("[crt-stt] arecord: %s" % ln)
    else:
        lines.append("[crt-stt] arecord said nothing on stderr.")
    return "\n".join(lines)


def reap_capture(proc, timeout=2.0):
    """Make sure the arecord child is actually GONE, not merely signalled.

    Scope note, measured 2026-07-25 so nobody re-derives it: this is DEFENSIVE,
    not the fix for an observed leak. The suspicion was that killing this
    process orphans arecord holding the USB capture device -- which would be
    serious, since this process is the documented SOLE reader of the mic and
    capture death now exits 3, so an orphan would turn one restart into a
    supervisor restart loop blocked by the corpse of the previous run. It does
    not happen: when this process exits, the read end of arecord's stdout pipe
    closes and arecord dies of SIGPIPE on its next write, with or without any
    handler. Verified against both the pre-fix and post-fix versions with a
    fake arecord -- the child was gone within ~3s either way. (An earlier probe
    that seemed to show an orphan was signalling `setsid`'s already-exited pid
    rather than python's, so nothing was ever killed.)

    What this adds is determinism rather than a repair: the release happens
    because we waited for it, not because of the child's write timing. Cheap
    insurance on the one resource this console cannot share. terminate() only
    asks -- so wait, then SIGKILL if it did not go, then reap that too so no
    zombie holds the fd. Best-effort throughout: a failure to clean up must
    never mask the exit path this runs on.
    """
    if proc is None:
        return
    try:
        if proc.poll() is not None:      # already dead; still needs reaping
            try: proc.wait(timeout=timeout)
            except Exception: pass
            return
        proc.terminate()
        try:
            proc.wait(timeout=timeout)
            return
        except Exception:
            pass
        proc.kill()
        try: proc.wait(timeout=timeout)
        except Exception: pass
    except Exception:
        pass


def install_signal_handlers():
    """Turn SIGTERM/SIGHUP into KeyboardInterrupt so main()'s existing
    "deliberate stop" path runs -- which reaps arecord and does NOT print a
    CAPTURE DIED report, because a human/supervisor stopping us is not a
    failure.

    Measured 2026-07-25: Python runs `finally:` on SIGINT only -- an untrapped
    SIGTERM *or* SIGHUP skips it entirely, so before this, every teardown that
    was not a literal Ctrl-C ran no cleanup at all. Both signals are trapped,
    because they are two different real teardowns here:

      SIGTERM -- `pkill -f crt-stt-solo.py`, `systemctl stop`, any supervisor
        restarting just this process.
      SIGHUP  -- what tmux actually delivers when a window/pane is destroyed
        (verified the same day with a real `tmux kill-window`: the pane
        process receives signal 1, not 15). Worth knowing generally: the
        sibling handler in crt-tts.py named `tmux kill-window` as its
        motivating case while trapping only SIGTERM, and so missed it.

    See reap_capture() for why this is hardening rather than a bug fix -- the
    mic does get released without it. What the handler buys is that the
    release is deliberate and says so on the pane, instead of the process
    vanishing mid-loop and leaving "did it stop or did it go deaf?" as the
    only thing a human can tell -- the exact ambiguity this file keeps
    getting bitten by.

    SIGINT is deliberately left alone -- Python already turns it into
    KeyboardInterrupt, which is exactly what these handlers synthesize.
    """
    def _bail(signum, frame):
        raise KeyboardInterrupt
    for sig in (signal.SIGTERM, signal.SIGHUP):
        try:
            signal.signal(sig, _bail)
        except (ValueError, OSError, AttributeError):
            # not the main thread, or a platform without SIGHUP
            pass


def main():
    # claude/secretary sinks: don't start feeding keystrokes/utterances until
    # the target session is up (it may still be launching `claude`), else
    # the first utterances are lost. secretary mode still needs window 0
    # for control keystrokes (see send_to_claude/CONTROL above).
    if SINK in ("claude", "secretary"):
        while subprocess.run(["tmux", "has-session", "-t", SESSION],
                             stderr=subprocess.DEVNULL).returncode != 0:
            time.sleep(1)
    # arecord's stderr goes to a temp file rather than /dev/null: it is the
    # ONLY explanation of why capture died (see capture_death_report), and
    # this process cannot afford to lose it. A pipe would risk blocking on a
    # full buffer nobody is draining.
    err_f = tempfile.NamedTemporaryFile(prefix="crt-stt-arecord-", suffix=".err")
    proc = subprocess.Popen(
        ["arecord", "-D", DEV, "-f", "S16_LE", "-c", "1", "-r", str(RATE), "-t", "raw"],
        stdout=subprocess.PIPE, stderr=err_f)
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
    mute_hold = 0.0       # seconds an open utterance has been frozen by a duck
    transcribe_fails = 0  # consecutive utterances heard but not transcribed
    last_meter = 0.0
    global hud_msg, hud_until
    ctl_pos = 0
    ctl_replay = True     # first CTL read is the file's history, not live input
    ring_state = None     # None | "tone" | "gap"
    ring_remaining = 0
    ring_phase_until = 0.0
    ring_proc = None
    started = time.time()
    capture_died = False
    try:
        while True:
            data = read_exact(proc.stdout, NBYTES)
            if len(data) < NBYTES:
                capture_died = True
                break
            a = array.array('h'); a.frombytes(data)
            peak = (max(abs(x) for x in a) / FULL) if a else 0.0

            now = time.time()

            # Watchdog on a leaked capture duck (see MUTE_MAX_SECS). Runs
            # before the CTL read so a stuck mute clears even if nothing is
            # writing to the control file any more -- the exact case where
            # the producer that owed us a "mute 0" is already dead.
            warn = check_mute_timeout(now)
            if warn:
                print("\n" + warn)
                hud_msg, hud_until = "MUTE  force-cleared", now + 1.6

            # Live-tune: a knob/MIDI writer appends "<param> <value>" to CTL.
            # On change, apply it and flash the level bar over the meter.
            if CTL:
                try:
                    sz = os.path.getsize(CTL)
                    if sz < ctl_pos:          # file truncated/rotated -> restart
                        ctl_pos, ctl_replay = 0, True
                    if sz > ctl_pos:
                        with open(CTL) as fh:
                            fh.seek(ctl_pos)
                            chunk = fh.read()
                            ctl_pos = fh.tell()
                        lines = chunk.splitlines()
                        if ctl_replay:
                            # Catching up on the file's existing history, not
                            # reacting live: restore levels, drop one-shots
                            # (see MOMENTARY_CTL -- a stale "mute 1" here used
                            # to deafen capture on every restart, a stale
                            # "ring" re-rang the phone at boot).
                            lines = [l for l in lines if not is_momentary_ctl(l)]
                        for ln in lines:               # apply every new line once
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
                            r = apply_ctl_line(ln, now)
                            if r:
                                hud_msg, hud_until = r, now + 1.6
                except OSError:
                    pass
                # One catch-up pass only, cleared whether or not the file
                # existed/had content this iteration -- otherwise a console
                # that boots before anything creates the CTL file would treat
                # the first LIVE duck as replayable history and drop it.
                ctl_replay = False

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

            # Cheap tick, opt-in only -- see bin/crt-wake-arm.py. Must run
            # even with no speech happening at all, since a timeout is
            # defined by silence, not by the next utterance arriving.
            if WAKE_ARM_ENABLED:
                wake_arm.check_arm_timeout(ARM_STATE, now)

            if not in_utt:
                # Ducked audio does not go in the pre-roll either (2026-07-25).
                # The deque's whole job is to prepend the moments before onset,
                # since the attack of a first word sits under the threshold --
                # so anything in it is handed to whisper as the opening of the
                # next utterance. The start gate below refuses to BEGIN an
                # utterance while muted and utt_chunk() excises a duck that
                # arrives mid-utterance, but neither helps if our own handset
                # playback is already sitting in the deque when the speaker
                # starts. Skipping the append splices the pre-roll across the
                # duck, exactly as utt_chunk() splices the utterance body:
                # what leads the utterance is then the room tone from just
                # before playback started, not the tail of the playback.
                if not MUTED:
                    pre.append(data)
                if not MUTED and peak >= THRESH:
                    above += 1
                    if above >= START:
                        in_utt = True
                        buf = bytearray(b"".join(pre)); pre.clear()
                        sil = 0.0
                        mute_hold = 0.0
                        utt_peak = peak
                        if EARCON_ON_THRESHOLD:
                            play_earcon("heard")
                else:
                    above = 0
            else:
                keep, ended, sil, mute_hold = utt_chunk(
                    MUTED, peak, sil, mute_hold, len(buf) / 2 / RATE)
                if keep:
                    buf += data
                    utt_peak = max(utt_peak, peak)
                dur = len(buf) / 2 / RATE
                if ended:
                    in_utt = False; above = 0; mute_hold = 0.0
                    if dur >= MINUTT:
                        if PREDICT_FLASH:
                            predictive_flash()
                        set_sideband_state("thinking")
                        text = transcribe(bytes(buf))
                        if text is None:
                            # Heard, captured, and then lost between here and
                            # the recogniser. Anything that stays quiet here
                            # is claiming the room was silent (see
                            # transcribe_remote's None/"" split).
                            transcribe_fails += 1
                            hud, line = transcribe_failure_report(
                                transcribe_fails, WHISPER_SERVER)
                            hud_msg, hud_until = hud, time.time() + FLASH_SECS
                            if line:
                                report_line(line)
                        else:
                            rec = transcribe_recovery_report(transcribe_fails)
                            if rec:
                                report_line(rec)
                            transcribe_fails = 0
                            emit(text, utt_peak)
                        set_sideband_state("listening")
                    buf = bytearray()
    except KeyboardInterrupt:
        capture_died = False       # deliberate stop, not a failure
    finally:
        # Release the mic before anything else. The next crt-stt-solo.py
        # cannot open the device until this child is gone (see reap_capture).
        reap_capture(proc)
        if ring_proc is not None:
            reap_capture(ring_proc)
    if not capture_died:
        # Say it on the way out: a console that stops hearing should never be
        # ambiguous about whether it stopped on purpose. Cheap, and it is the
        # human-readable half of "the device was actually released".
        #
        # Guarded, because the single most likely reason we are here is
        # `tmux kill-window` -- which delivers SIGHUP precisely BECAUSE the
        # pty went away, so this write can fail with EIO/EPIPE. Unguarded it
        # would raise at the very end of a clean shutdown and exit 1, turning
        # the deliberate stop back into something a supervisor reads as a
        # crash -- the exact thing this message exists to prevent.
        try:
            print("\n[crt-stt] stopped; released %s" % DEV)
        except OSError:
            pass
    if capture_died:
        try:
            proc.wait(timeout=2)
        except Exception:
            pass
        try:
            err_f.seek(0)
            err_text = err_f.read().decode("utf-8", "replace")
        except Exception:
            err_text = ""
        sys.stderr.write(capture_death_report(
            DEV, proc.poll(), err_text, time.time() - started) + "\n")
        sys.stderr.flush()
        sys.exit(3)


if __name__ == "__main__":
    install_signal_handlers()
    main()
