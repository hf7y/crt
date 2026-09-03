#!/usr/bin/env python3
# Single-reader standalone STT engine -- no Claude Code, no dsnoop.
#
# WHY THIS EXISTS: on the VirtualBox guest the emulated capture does NOT fan out
# through dsnoop -- a *second* reader gets a starved signal (measured: sole
#   [rest: vault:crt/header-archaeology-20260817.md]
import sys, os, array, time, wave, tempfile, subprocess, datetime, urllib.request, urllib.error, json, re, signal, fcntl, termios
import importlib.util
from collections import deque

# Loaded by path, not by plain `import`: the tests load this file with
# spec_from_file_location, which does not put bin/ on sys.path.
_cfg_spec = importlib.util.spec_from_file_location(
    "crt_config_for_stt_solo",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "crt_config.py"))
crt_config = importlib.util.module_from_spec(_cfg_spec)
_cfg_spec.loader.exec_module(crt_config)

# The wake-word rule itself, shared with crt-book-answer-listen.py so the
# Book Game's grader can tell "an answer" from "a question for Claude".
_wg_spec = importlib.util.spec_from_file_location(
    "crt_wake_gate_for_stt_solo",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "crt_wake_gate.py"))
wake_gate = importlib.util.module_from_spec(_wg_spec)
_wg_spec.loader.exec_module(wake_gate)

_mp_spec = importlib.util.spec_from_file_location(
    "crt_media_player_for_stt_solo",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "crt-media-player.py"))
media_player = importlib.util.module_from_spec(_mp_spec)
_mp_spec.loader.exec_module(media_player)

# SINK: where recognized text goes.
#   stdout (default) -- scroll transcriptions; standalone STT/debug view.
#   claude           -- type into the tmux Claude Code pane + voice-control keys,
#                       exactly like stt-feed.sh, but from this SINGLE-reader
#   [rest: vault:crt/header-archaeology-20260817.md]
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

# crt#34: True releases a CONTROL word to whatever playbook wants it instead.
PERSONA_CONTROL_OVERRIDES = {"next": lambda: media_player.is_media_active()}


# Is the pane above a Claude brain, or the potato idle face? One shared
# answer, in bin/crt_config.py, whose header carries the whole finding. False
# in the historical layout (CRT_IDLE_FACE_WINDOW unset), so nothing about
# this engine's behaviour changes there.
PANE_IS_IDLE_FACE = crt_config.pane_is_idle_face()
# Snapshotted next to the decision, not rebuilt when it is reported: a
# message that reads the environment later can describe a different
# configuration than the one that was actually acted on.
IDLE_FACE_PANE_REPORT = crt_config.idle_face_pane_report(PANE)
_idle_face_reported = False


def send_to_claude(text, key):
    """Type text (or send a control keystroke) into the tmux Claude pane.

    Unless that pane is the idle face (2026-07-25). CONTROL keystrokes
    deliberately BYPASS the wake gate -- they are meta-interactions with
    whatever is on screen -- so in the idle-lean layout every ambient
    "okay"/"no"/"next"/"back" in the room was being typed into
    crt-screensaver.py's stdin: echoed onto the potato by the tty, Enter
    scrolling the frame, nothing anywhere able to act on it, and the
    "control" earcon (suppressed below) beeping as though something had.
    Refuse and say so instead. The utterance is already in stt.log by the
    time this runs, so the Book Game's answer listener still sees a spoken
    "yes" exactly as before."""
    global _idle_face_reported
    if PANE_IS_IDLE_FACE:
        print("[crt-stt] not sent -- %s: %r" % (IDLE_FACE_PANE_REPORT, text))
        if not _idle_face_reported:
            # Once per process, on window 1: the cause never changes and this
            # can fire on any stray single word, but a failure only the stt
            # pane knows about is a failure nobody at the tube can see. Same
            # once-per-distinct-cause rule crt-window-switcher.py uses.
            _idle_face_reported = True
            log_console_thought("voice keys have nowhere to go -- %s"
                                % IDLE_FACE_PANE_REPORT)
        return
    target = "%s:%s" % (SESSION, PANE)
    if " " not in text and key in CONTROL:
        subprocess.run(["tmux", "send-keys", "-t", target, CONTROL[key]])
        return
    subprocess.run(["tmux", "send-keys", "-t", target, "-l", text])
    subprocess.run(["tmux", "send-keys", "-t", target, "Enter"])


# Fire-and-forget must not mean nobody-ever-looks (2026-07-25). In the live
# boot config this is THE destination for every utterance that gets past the
# wake gate -- crt-console.sh runs this engine with CRT_STT_SINK=secretary --
# and both of the child's streams went to /dev/null with its exit status read
#   [rest: vault:crt/header-archaeology-20260817.md]
DISPATCH_MAX_TRACKED = int(os.environ.get("CRT_DISPATCH_MAX_TRACKED", "8"))
DISPATCH_ERR_TAIL = 8192          # bytes of a chatty child's stderr worth keeping
_dispatches = []


class Dispatch:
    """One utterance handed to crt-secretary.py, still in flight: the process,
    the file its stderr went to, and the words themselves. Same shape as
    RingTone below, for the same reason -- an exit status with no stderr beside
    it names no cause, and this project has now spent several cycles on
    evidence it collected and never read."""

    def __init__(self, text, proc, err):
        self.text, self.proc, self.err = text, proc, err

    def failure(self):
        """Why this utterance was never acted on, or None if the secretary is
        still working or finished cleanly. Non-blocking -- poll(), never
        wait()."""
        rc = self.proc.poll()
        if rc is None or rc == 0:
            return None
        detail = ""
        try:
            size = os.fstat(self.err.fileno()).st_size
            self.err.seek(max(0, size - DISPATCH_ERR_TAIL))
            detail = self.err.read().decode("utf-8", "replace")
        except (OSError, ValueError):
            pass
        how = "killed by signal %d" % -rc if rc < 0 else "exited %d" % rc
        return "crt-secretary.py %s: %s" % (how, last_line(detail))

    def close(self):
        try:
            self.err.close()
        except OSError:
            pass


def dispatch_failure_report(text, detail):
    """(hud, line) for an utterance that reached crt-secretary.py and died
    there. Pure string builder, same posture as capture_death_report() and
    ring_unplayable_report(). The distinction it exists to protect: a gate drop
    and a dead secretary are the same silence in the room, and only one of them
    is this machine's fault."""
    return ("! nothing handled that",
            "[stt] DISPATCH FAILED -- %s. \"%s\" got past the wake gate, so the "
            "earcon said it had been heard, and then nothing acted on it. The "
            "fault is here, not in what you said." % (detail, text[:120]))


def dispatch_untracked_line(reason):
    """Said when an utterance is dispatched without a handle to read later. The
    utterance still goes through -- never drop one to keep a diagnostic -- but
    a failure from here on is invisible again, so it does not pass unremarked."""
    return ("[stt] handing this utterance over untracked -- %s. If it fails, "
            "nothing here will say so." % reason)


def send_to_secretary(text):
    """Fire-and-forget: hands the utterance to crt-secretary.py's local-
    playbook-first router (SECRETARY.md) instead of typing straight into
    Claude's pane -- PARKING-LOT.md's 'Local-first STT routing' plan.
    Popen, not run/check_call -- must never block this capture loop on
    crt-secretary.py's own Claude-escalation wait (up to
    CRT_SECRETARY_MAX_WAIT seconds for an unmatched request)."""
    err, untracked = None, None
    if len(_dispatches) >= DISPATCH_MAX_TRACKED:
        untracked = "%d already in flight" % len(_dispatches)
    else:
        try:
            err = tempfile.NamedTemporaryFile(prefix="crt-stt-dispatch-",
                                              suffix=".err")
        except OSError as e:
            untracked = "no file to keep its stderr in: %s" % e
    try:
        proc = subprocess.Popen(
            ["python3", os.path.join(BIN_DIR, "crt-secretary.py"), text],
            stdout=subprocess.DEVNULL,
            stderr=err if err is not None else subprocess.DEVNULL,
        )
    except OSError as e:
        # Spawning can fail for reasons that have nothing to do with the words:
        # ENOMEM on a 905MB Pi already running whisper and ten tmux windows is
        # the realistic one. This used to raise straight out of the capture
        # loop, so a moment of memory pressure cost the console its hearing
        # rather than one utterance.
        if err is not None:
            err.close()
        _report_dispatch_failure(text, "could not start it: %s" % e)
        return
    if err is None:
        print("\n" + dispatch_untracked_line(untracked))
        return
    _dispatches.append(Dispatch(text, proc, err))


def _report_dispatch_failure(text, detail):
    """Three surfaces, because the person may be looking at any of them: the
    pane, the meter line, and window 1 (where their own utterance was just
    echoed as '[you] ...' -- this lands right under it)."""
    hud, line = dispatch_failure_report(text, detail)
    print("\n" + line)
    set_hud(hud)
    log_console_thought(hud)


def reap_dispatches():
    """Read the exit status of every dispatch that has finished, report the
    ones that failed, and stop tracking them. Non-blocking, so the capture loop
    can call this on every chunk."""
    still = []
    for d in _dispatches:
        if d.proc.poll() is None:
            still.append(d)
            continue
        fault = d.failure()
        d.close()
        if fault:
            _report_dispatch_failure(d.text, fault)
    _dispatches[:] = still


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
    # stderr is INHERITED, not discarded (2026-07-25). crt-earcon.sh is silent
    # on success -- it only writes to stderr to say sox is missing, the name is
    # unknown, or (via set -e) that aplay failed -- so letting it through costs
    # nothing when things work and is the only evidence when they do not. It
    # stays fire-and-forget: this is the sole mic reader's loop and an earcon
    # must never add latency to it, so nothing waits on the exit status. That
    # is why the stderr has to be readable somewhere instead.
    try:
        subprocess.Popen(
            [os.path.join(BIN_DIR, "crt-earcon.sh"), name, "--device", EARCON_DEVICE],
            stdout=subprocess.DEVNULL,
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
#   [rest: vault:crt/header-archaeology-20260817.md]
DEV_NAME_PATTERN = os.environ.get("CRT_AUDIO_DEV_NAME", "USB Audio")
DEV_FALLBACK = "plughw:0,0"

ARECORD_CARD_RE = re.compile(
    r"^card (\d+):.*\[(.*?)\],\s*device (\d+):", re.IGNORECASE)

# HOW a device was arrived at. The resolver has always had three outcomes;
# it used to return only the device, so the caller had to re-derive which one
# had happened -- and did it by testing whether DEV_NAME_PATTERN appeared
# anywhere in the raw `arecord -l` text. That is not the same question.
#   [rest: vault:crt/header-archaeology-20260817.md]
BY_NAME      = "name"           # a card's bracketed name actually matched
FIRST_LISTED = "first-listed"   # no name matched; guessed a real capture card
NO_CARDS     = "no-cards"       # the listing named no capture cards at all


def resolve_capture_device(arecord_l_output, name_pattern=DEV_NAME_PATTERN,
                           fallback=DEV_FALLBACK):
    """Pure string parse of `arecord -l` CAPTURE-device listing output.
    Returns (device, reason, card_names): 'plughw:<card>,<device>' for the
    first card whose bracketed name contains name_pattern (case-insensitive),
    with reason BY_NAME. If nothing matches by name but the listing DOES name
    capture cards, returns the first one listed (FIRST_LISTED) rather than
    `fallback`: every card in this listing can at least be opened for capture,
    whereas the hardcoded fallback index is exactly what broke on potato
    (plughw:0,0 there is the onboard playback-only card, absent from this
    listing entirely -- arecord on it exits instantly with no capture).
    `fallback` is only for a listing with no cards at all (NO_CARDS).

    card_names is every bracketed card name seen, in order, so a caller
    reporting a miss can name what WAS there without re-running arecord.

    Does not touch hardware itself; callers pass in the already-captured
    `arecord -l` text so this stays unit-testable."""
    needle = (name_pattern or "").lower()
    first = None
    names = []
    for line in (arecord_l_output or "").splitlines():
        m = ARECORD_CARD_RE.match(line.strip())
        if not m:
            continue
        dev = "plughw:%s,%s" % (m.group(1), m.group(3))
        names.append(m.group(2))
        if needle and needle in m.group(2).lower():
            return dev, BY_NAME, names
        if first is None:
            first = dev
    if first:
        return first, FIRST_LISTED, names
    return fallback, NO_CARDS, names


def resolve_capture_device_by_name(arecord_l_output, name_pattern=DEV_NAME_PATTERN,
                                    fallback=DEV_FALLBACK):
    """The device alone, for callers that don't report on how it was found."""
    return resolve_capture_device(arecord_l_output, name_pattern, fallback)[0]


def capture_device_warning(dev, reason, names, name_pattern=DEV_NAME_PATTERN):
    """The message for a device that was GUESSED rather than matched, or None
    when it was matched by name and there is nothing to say. Separate from the
    resolver and from the writing of it so the wording is testable without a
    subprocess -- same shape as capture_death_report() below.

    Guessing a capture device is a legitimate degraded mode. Doing it silently
    is how "the console just stopped hearing anything" turns into an evening
    of debugging, which is the entire reason this resolver exists."""
    if reason == BY_NAME:
        return None
    if reason == NO_CARDS:
        return ("[crt-stt] WARNING: `arecord -l` listed NO capture cards at "
                "all; falling back to %s, which may not be a capture device "
                "on this box. Check the mic is plugged in, or set "
                "CRT_AUDIO_DEV to pin one explicitly.\n" % dev)
    seen = ", ".join(repr(n) for n in (names or [])) or "(none)"
    return ("[crt-stt] WARNING: no capture card NAMED %r in `arecord -l`; "
            "guessing %s, the first one listed. Cards seen: %s. Set "
            "CRT_AUDIO_DEV to pin a device explicitly, or CRT_AUDIO_DEV_NAME "
            "to match this box's adapter.\n" % (name_pattern, dev, seen))


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
    dev, reason, names = resolve_capture_device(out)
    warning = capture_device_warning(dev, reason, names)
    if warning:
        sys.stderr.write(warning)
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
#   [rest: vault:crt/header-archaeology-20260817.md]
MUTE_COUNT = 0
# Safety net on that reference count (2026-07-25). Ref-counting made
# overlapping ducks compose, but it also removed the old flag's accidental
# self-healing: with last-write-wins, ANY later "mute 0" restored capture,
# so a duck whose producer died mid-playback (aplay SIGKILLed, crt-tts.py
#   [rest: vault:crt/header-archaeology-20260817.md]
MUTE_MAX_SECS = float(os.environ.get("CRT_CTL_MUTE_MAX_SECS", "45"))
MUTE_SINCE = 0.0
# How long an ALREADY-OPEN utterance may stay frozen by a duck that arrived
# mid-utterance before we give up and close it out (2026-07-25). See
# utt_chunk() for what "frozen" means and why the duck is not simply ignored
# once speech has started. 0 = never close on a duck alone (freeze until it
#   [rest: vault:crt/header-archaeology-20260817.md]
MUTE_UTT_MAX_SECS = float(os.environ.get("CRT_MUTE_UTT_MAX_SECS", "2.0"))
# Control lines that are MOMENTARY (an edge/command owned by a live
# producer) rather than a LEVEL that should persist. The CTL file is an
# append-only log and main() replays it from byte 0 on startup, which is
# deliberate for levels -- a threshold tuned by knob survives a restart.
#   [rest: vault:crt/header-archaeology-20260817.md]
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
    """Lazily synthesize a warbling ring tone once, cache the wav path.
    Returns None if the tone could not be made -- the caller must not then
    pretend to ring.

    Why None and not a path (2026-07-25): this used to ignore sox's exit
    status AND its stderr, and cache `path` regardless. mkstemp has already
    created that file, so on a box with no sox -- or a sox that failed --
    the cache held a real, existing, ZERO-BYTE wav. `os.path.exists()` said
    yes forever after, so every ring for the life of the process handed
    aplay an empty file, and the console reported "[ring] no answer": it
    blamed the person for not picking up a phone that had never rung.
    crt-earcon.sh checks for sox by name and exits 1 with a message; this
    path, which is the one that summons someone to the handset, checked
    nothing."""
    global _ring_tone_path
    if _ring_tone_path and os.path.exists(_ring_tone_path):
        return _ring_tone_path
    fd, path = tempfile.mkstemp(suffix="_ring.wav"); os.close(fd)
    try:
        r = subprocess.run(["sox", "-n", path, "synth", str(RING_ON_SECS),
                            "sine", "900", "tremolo", "20", "80", "vol", "-6dB"],
                           capture_output=True, text=True)
        failure = ("sox exited %d: %s" % (r.returncode, last_line(r.stderr))
                   if r.returncode != 0 else None)
    except OSError as e:
        failure = "could not run sox: %s" % e
    if failure is None and os.path.getsize(path) == 0:
        # sox can exit 0 and still leave nothing usable. The size check is
        # the witness that matters -- it is what aplay would choke on.
        failure = "sox produced an empty wav"
    if failure is not None:
        try:
            os.unlink(path)          # never cache an unplayable tone
        except OSError:
            pass
        hud, line = ring_unplayable_report(failure)
        print("\n" + line)
        set_hud(hud)
        return None
    _ring_tone_path = path
    return path


def last_line(text):
    """The last non-blank line of a subprocess's stderr -- the part that
    names the cause. Pure; shared by the ring reports below."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    return lines[-1][:200] if lines else "no error text"


class RingTone:
    """One ring burst in flight: the aplay process, plus the file its stderr
    went to. Kept together because the second is the only explanation of the
    first's exit status -- and evidence this project collects and never reads
    has been indistinguishable from evidence never collected three cycles
    running."""

    def __init__(self, proc, err):
        self.proc, self.err = proc, err

    # Delegates, so this stays a drop-in wherever a Popen used to be --
    # notably reap_capture(), which the exit path hands the in-flight ring to.
    def poll(self):
        return self.proc.poll()

    def terminate(self):
        self.proc.terminate()

    def kill(self):
        self.proc.kill()

    def wait(self, timeout=None):
        return self.proc.wait(timeout=timeout)

    def failure(self):
        """Why this burst never reached the earpiece, or None if it is still
        playing or played fine. Non-blocking -- poll(), never wait().

        A negative exit code means a signal, which on this path is only ever
        our own terminate() when the ring was answered. That is a ring that
        worked, not one that failed."""
        rc = self.proc.poll()
        if rc is None or rc <= 0:
            return None
        detail = ""
        try:
            self.err.seek(0)
            detail = self.err.read().decode("utf-8", "replace")
        except (OSError, ValueError):
            pass
        return "aplay exited %d: %s" % (rc, last_line(detail))


def start_ring_tone():
    """Begin one ring burst, or return None if it could not be started.

    Every caller must treat None as "the phone did not ring" -- the whole
    point of this function existing separately from the two bare
    subprocess.Popen calls it replaced."""
    path = ring_tone_path()
    if path is None:
        return None                     # already reported by ring_tone_path
    err = tempfile.NamedTemporaryFile(prefix="crt-stt-ring-", suffix=".err")
    try:
        proc = subprocess.Popen(["aplay", "-q", path],
                                stdout=subprocess.DEVNULL, stderr=err)
    except OSError as e:
        hud, line = ring_unplayable_report("could not run aplay: %s" % e)
        print("\n" + line)
        set_hud(hud)
        return None
    return RingTone(proc, err)


def ring_unplayable_report(detail):
    """(hud, line) for a ring that could not be produced at all.

    Pure string builder, same posture as capture_death_report() and
    transcribe_failure_report(). The wording has one job: not to be mistaken
    for an unanswered call. Those are opposite facts -- one is about the
    person, one is about this machine -- and the console used to report the
    second as the first."""
    return ("! phone never rang",
            "[ring] RANG NOTHING -- %s. The handset never made a sound, so "
            "nobody declined to answer it. This is a fault here, not a "
            "missed call." % detail)
# Optional: send the WAV to a faster-whisper HTTP service on another machine
# instead of invoking whisper.cpp on this one. Same VAD/capture/denoise
# pipeline either way -- only the inference step moves. Live shape as of
# 2026-07-25: potato POSTs to bin/mandark-whisper-server.py on mandark, wired
#   [rest: vault:crt/header-archaeology-20260817.md]
WHISPER_SERVER = os.environ.get("CRT_WHISPER_SERVER", "")   # e.g. http://100.107.253.56:8090/inference
WHISPER_SERVER_TIMEOUT = float(os.environ.get("CRT_WHISPER_SERVER_TIMEOUT", "8"))
WHISPER_LOCAL_FALLBACK = os.environ.get("CRT_WHISPER_LOCAL_FALLBACK", "1") != "0"  # crt#132

CHUNK_DUR = CHUNK / RATE
THR_COL   = max(0, min(WIDTH - 1, int(THRESH / MFULL * WIDTH)))

# Flash state for the meter line -- shared by the knob/ctl HUD (apply_ctl_line)
# and by emit() flashing the raw STT output. Module-level (not main()-local)
# so emit() can set it directly; main()'s display loop just reads it.
hud_msg = ""
hud_until = 0.0
FLASH_SECS = float(os.environ.get("CRT_FLASH_SECS", "2.5"))


def set_hud(msg, secs=None):
    """Flash one line over the meter. The tube is where the person is
    looking; a fault that only reaches this pane's scrollback has not really
    been reported."""
    global hud_msg, hud_until
    hud_msg = msg[:WIDTH + 20]
    hud_until = time.time() + (FLASH_SECS if secs is None else secs)

# Predictive-text double layer (2026-07-19, opt-in, off by default): the
# instant an utterance ends, flash a cheap local guess (bin/crt-predict.py,
# trained on this room's own ~/.crt/stt.log history) BEFORE whisper -- which
# genuinely takes real wall-clock time -- has run at all. emit() unconditionally
#   [rest: vault:crt/header-archaeology-20260817.md]
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
#   [rest: vault:crt/header-archaeology-20260817.md]
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
#   [rest: vault:crt/header-archaeology-20260817.md]
GATE       = os.environ.get("CRT_STT_GATE", "0") != "0"
WAKE_WORD  = wake_gate.wake_word()   # one source: bin/crt_wake_gate.py
# 2026-07-28, live, Zach-directed ("clean up claude output to mono ...
# junk on screen"): this defaulted to the SAME file as THOUGHT_LOG below
# -- window 1 (mono, crt-monologue.py) renders thoughts.log directly, so
# every ambient utterance in the room that never reached Claude (gated,
#   [rest: vault:crt/header-archaeology-20260817.md]
GATE_LOG   = os.environ.get("CRT_STT_GATE_LOG", os.path.expanduser("~/.crt/gate.log"))
# Resolved through bin/crt_config.py rather than read here, so this gate
# and the two scripts that WRITE stt-fixups.json can no longer be pointed
# at different files by setting one env var (crt-stt-training-merge.py
# spelled it CRT_STT_FIXUPS_PATH; see that module's header).
FIXUPS_PATH = crt_config.fixups_path()

# Arm-window / wake-judge wiring (2026-07-23, see bin/crt-wake-arm.py's
# own header for the full story -- this is the "sticky conversation
# window" fix, wired to crt-wake-judge.py's dormant autonomous tuning
# judge). Opt-in, default OFF: with CRT_WAKE_ARM_ENABLED unset, every
#   [rest: vault:crt/header-archaeology-20260817.md]
WAKE_ARM_ENABLED = os.environ.get("CRT_WAKE_ARM_ENABLED", "0") == "1"
if WAKE_ARM_ENABLED:
    import importlib.util as _importlib_util
    _wa_spec = _importlib_util.spec_from_file_location(
        "crt_wake_arm", os.path.join(os.path.dirname(os.path.abspath(__file__)), "crt-wake-arm.py"))
    wake_arm = _importlib_util.module_from_spec(_wa_spec)
    _wa_spec.loader.exec_module(wake_arm)
    ARM_STATE = wake_arm.ArmState()


def publish_arm_window():
    """Tell the rest of the console whether a sticky-conversation window is
    open. Called after EVERY arm-state transition below and nowhere else --
    the state lives in this process, so this is the only place that knows.

    A no-op when arming is disabled, which is also why nothing else has to
    know about CRT_WAKE_ARM_ENABLED: with the feature off the file is never
    written, and bin/crt-wake-arm.py's arm_window_open() reads that as
    closed. See that function for the reader (crt-book-answer-listen.py,
    which grades utterances this engine has already routed to Claude)."""
    if WAKE_ARM_ENABLED:
        wake_arm.publish_arm_window(ARM_STATE)


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


def fixups_signature(path):
    """(inode, mtime_ns, size) for `path`, or None when it isn't there.
    Three fields rather than mtime alone: crt-stt-training-merge.py lands
    this file with os.replace(), which brings a whole new inode, and a hand
    edit can rewrite it inside a single filesystem timestamp tick."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_ino, st.st_mtime_ns, st.st_size)


def fixups_change_report(added, removed, wake_word=WAKE_WORD, max_named=3):
    """One short line for a 40-column tube saying what just changed in
    stt-fixups.json. `added` is {key: info}, `removed` a list of keys.
    Names the added entries whose intent IS the wake word, because those
    are the only ones that change what this gate does -- the rest are
    plumbing for a consumer that doesn't exist yet (see
    crt-stt-training-merge.py's own honest-scope note)."""
    counts = []
    if added:
        counts.append("+%d" % len(added))
    if removed:
        counts.append("-%d" % len(removed))
    line = "fixups reloaded (%s)" % ", ".join(counts or ["no change"])
    wake_new = sorted(k for k, info in added.items()
                      if (info or {}).get("intent") == wake_word)
    if wake_new:
        named = ", ".join(repr(k) for k in wake_new[:max_named])
        if len(wake_new) > max_named:
            named += ", +%d more" % (len(wake_new) - max_named)
        line += " -- now wakes me: %s" % named
    return line


def fixups_error_report(err, kept):
    """The line for a fixups file that is there but unreadable. Says which
    set is actually in force, because the two cases differ in what the room
    will experience: a stale-but-good set still opens the gate on every
    alias it knew, an empty one silently narrows the gate to the exact wake
    word and nothing else."""
    if kept:
        held = "keeping the %d I already had" % len(kept)
    else:
        held = "exact %r only until it parses" % WAKE_WORD
    return "fixups unreadable: %s -- %s" % (err, held)


class FixupsFile:
    """The wake gate's live view of stt-fixups.json, re-read when it changes.

    Until 2026-07-25 this was a single module-level `FIXUPS =
    load_fixups(...)` evaluated at import, which `addressed_to_console` then
    bound as a *default argument* -- two separate reasons a later edit could
    never reach the gate. Three things write this file while the engine is
    running: crt-stt-training-merge.py's `stttrain` window (--loop, every
    CRT_STT_TRAINING_MERGE_INTERVAL_SECS), crt-calibration-game.py's wake
    round (a live human confirming a mishear by ear -- the strongest
    evidence this project ever collects), and a person with an editor. The
    file's only consumer read it once at boot, and this console stays up for
    days, so every one of those wrote to a file that changed nothing until
    the next restart. The learning loop was open at its last inch.

    A failed re-read keeps the last good set rather than falling back to
    {}: an aliased wake word that stops working is exactly the failure this
    room cannot tell apart from being misheard.
    """

    # "no failure recorded yet" cannot be None: None is what
    # fixups_signature() returns for a file that isn't there, and a deleted
    # fixups file is a failure that must be reported, not the one state the
    # de-duplication silently swallows. (Caught by
    # tests/test_fixups_reload.py before it ever ran on the tube.)
    NEVER_FAILED = object()

    def __init__(self, path, on_change=None, on_error=None):
        self.path = path
        self.fixups = {}
        self.signature = None
        self.loaded = False
        self.failed_signature = self.NEVER_FAILED
        self._on_change = on_change
        self._on_error = on_error

    def current(self):
        """The fixups in force right now. One os.stat per call -- called
        once per utterance from the gate, not per audio chunk."""
        sig = fixups_signature(self.path)
        if self.loaded and sig == self.signature:
            return self.fixups
        try:
            with open(self.path) as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            # Report once per distinct bad state, not once per utterance:
            # a file left malformed would otherwise fill window 1 with the
            # same line and push the person's own words off the top.
            if sig != self.failed_signature or not self.loaded:
                self.failed_signature = sig
                if self._on_error:
                    self._on_error(fixups_error_report(e, self.fixups))
            return self.fixups
        fresh = {k: v for k, v in data.items() if not k.startswith("_")}
        added = {k: v for k, v in fresh.items() if k not in self.fixups}
        removed = [k for k in self.fixups if k not in fresh]
        was_loaded, self.loaded = self.loaded, True
        self.fixups, self.signature = fresh, sig
        self.failed_signature = self.NEVER_FAILED
        # Silent at boot: the first load is not news, it is the baseline.
        if was_loaded and (added or removed) and self._on_change:
            self._on_change(fixups_change_report(added, removed))
        return fresh


def _report_fixups_note(line):
    """Same three surfaces as a dispatch failure, for the same reason --
    whichever one the person happens to be looking at."""
    print("\n[crt-stt] " + line)
    set_hud(line)
    log_console_thought(line)


FIXUPS_FILE = FixupsFile(FIXUPS_PATH,
                         on_change=_report_fixups_note,
                         on_error=_report_fixups_note)


def _log_thought(tag, text, log_path=None, timestamp=None):
    """Best-effort append to the log crt-monologue.py renders on window 1.
    Same convention as every other logging write in this project: a broken
    write here must never block the real STT->secretary/claude routing that
    follows it."""
    log_path = log_path or GATE_LOG
    ts = timestamp or time.strftime("%H:%M:%S")
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a") as f:
            f.write("%s  %s %s\n" % (ts, tag, text))
    except OSError:
        pass


def log_user_thought(text, log_path=None, timestamp=None):
    """Writes a '[you] ...' line to the same log crt-monologue.py already
    tails for Claude's own replies (crt-claude-bridge.py's thoughts.log) --
    the window-1 gap flagged repeatedly ("no visual signal of the USER's
    own speech")."""
    _log_thought("[you]", text, log_path, timestamp)


def log_console_thought(text, log_path=None, timestamp=None):
    """The console's own bad news, on the same window 1 as the '[you]' line it
    is usually answering. A failure printed only to the stt pane is a failure
    nobody standing at the tube can see."""
    _log_thought("[!]", text, log_path, timestamp)


def _contains_phrase(words, phrase):
    """Whole-word containment check: `phrase` (space-separated) must appear
    as a contiguous run of whole words in `words`, not as a bare substring
    -- else a fixup fragment like "slide" would false-positive inside an
    unrelated word like "landslide".

    Delegates to bin/crt_wake_gate.py since 2026-07-25: crt-book-answer-
    listen.py has to ask this same question about the same stt.log lines,
    and a second copy of the wake-word rule living in the Book Game is
    exactly the drift the find_playbook() reuse was meant to avoid. Kept as
    a name here because classify_wake_match() and the tests use it."""
    return wake_gate.contains_phrase(words, phrase)


def addressed_to_console(text, wake_word=WAKE_WORD, fixups=None):
    """True if `text` was actually addressed to the console: the wake word
    appears as a whole word, or a stt-fixups.json fragment whose learned
    intent IS the wake word appears (e.g. "slide" -> confirmed mishear of
    "claude", see stt-fixups.json) -- makes that fixup entry load-bearing
    for the gate, not just a documentation note for a human reader.
    Whisper output rarely carries reliable punctuation, but a stray comma
    ("hey claude, run the tests") shouldn't defeat the match -- tokenize on
    word characters only rather than plain str.split().

    `fixups=None` means the live file (FIXUPS_FILE.current(), re-read when
    stt-fixups.json changes on disk); an explicit dict still wins, for
    tests and for any caller holding a deliberate snapshot.

    The matching itself moved to bin/crt_wake_gate.py (2026-07-25) so the
    Book Game's grader can ask this exact question about the exact same
    utterance -- see that module's header. The live-file default stays
    HERE, because FIXUPS_FILE is more than a read: it reports what changed
    on window 1, and only the engine has a screen to report to."""
    if fixups is None:
        fixups = FIXUPS_FILE.current()
    return wake_gate.addressed_to_console(text, wake_word, fixups)


def classify_wake_match(text, wake_word=WAKE_WORD, fixups=None):
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
    see FOCUS.md. Same `fixups=None` -> live file convention as
    addressed_to_console, so the arm window can never disagree with the
    gate that just opened for it."""
    if fixups is None:
        fixups = FIXUPS_FILE.current()
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


# --- Capture backpressure (2026-07-25) --------------------------------------
#
# transcribe() runs INSIDE this capture loop: for however long whisper takes,
# nobody is reading arecord's stdout. The only thing holding the audio that
#   [rest: vault:crt/header-archaeology-20260817.md]
CAPTURE_PIPE_BYTES = int(os.environ.get("CRT_CAPTURE_PIPE_BYTES", str(256 * 1024)))

# A bigger pipe trades dropped audio for STALE audio: whatever queued up gets
# transcribed and answered later, at its own pace, while the room has moved
# on. So after each transcription anything older than this is discarded --
# and said out loud, because silently dropping audio is the failure mode this
#   [rest: vault:crt/header-archaeology-20260817.md]
BACKLOG_MAX_SECS = float(os.environ.get("CRT_CAPTURE_BACKLOG_MAX_SECS", "3.0"))

PIPE_MAX_SIZE_PATH = "/proc/sys/fs/pipe-max-size"
F_SETPIPE_SZ = getattr(fcntl, "F_SETPIPE_SZ", 1031)
F_GETPIPE_SZ = getattr(fcntl, "F_GETPIPE_SZ", 1032)


def audio_seconds(nbytes):
    """Bytes of S16_LE mono at RATE -> seconds. The one place this ratio is
    written down; every message about buffer depth goes through it."""
    return nbytes / 2.0 / RATE


def widen_capture_pipe(fd, want=None):
    """Grow the capture pipe to `want` bytes and return its real capacity.

    Returns None if the kernel won't tell us the size at all (non-Linux, odd
    fd) -- the caller reports that rather than assuming it worked. An
    unprivileged process cannot exceed /proc/sys/fs/pipe-max-size, so the
    request is clamped to it first: asking for more is EPERM, which would
    lose the widening entirely instead of taking what was available."""
    want = CAPTURE_PIPE_BYTES if want is None else want
    try:
        current = fcntl.fcntl(fd, F_GETPIPE_SZ)
    except (OSError, ValueError):
        return None
    try:
        with open(PIPE_MAX_SIZE_PATH) as f:
            want = min(want, int(f.read().strip()))
    except (OSError, ValueError):
        pass
    if want <= current:
        return current
    try:
        fcntl.fcntl(fd, F_SETPIPE_SZ, want)
    except OSError:
        return current
    try:
        return fcntl.fcntl(fd, F_GETPIPE_SZ)
    except (OSError, ValueError):
        return current


def capture_pipe_report(capacity):
    """The startup line about how much audio can queue while whisper runs.
    Pure string builder, like capture_death_report()."""
    if capacity is None:
        return ("[crt-stt] capture buffer: unknown size -- audio arriving during "
                "a transcription may be dropped without warning.")
    secs = audio_seconds(capacity)
    line = "[crt-stt] capture buffer %.1fs (%d B) holds audio while whisper runs" % (
        secs, capacity)
    if secs < 4.0:
        line += ("\n[crt-stt] that is less than a slow transcription takes -- "
                 "raise CRT_CAPTURE_PIPE_BYTES or expect dropped follow-ups.")
    return line


def pending_bytes(fd):
    """How much audio is queued in the capture pipe right now. None if the
    kernel won't say."""
    buf = array.array('i', [0])
    try:
        fcntl.ioctl(fd, termios.FIONREAD, buf, True)
    except OSError:
        return None
    return buf[0]


def backlog_drop_bytes(pending, keep_bytes, chunk_bytes):
    """Pure: how many of `pending` bytes to discard so no more than
    `keep_bytes` remain, rounded DOWN to a whole analysis chunk so the
    reader stays frame-aligned. The newest audio is what survives -- it is
    the half most likely to still be someone talking."""
    if keep_bytes <= 0 or pending is None or pending <= keep_bytes:
        return 0
    return ((pending - keep_bytes) // chunk_bytes) * chunk_bytes


def backlog_drop_report(dropped):
    return ("[crt-stt] dropped %.1fs of backlogged audio -- it queued up while "
            "whisper was running and is too old to answer now." % audio_seconds(dropped))


def drain_capture_backlog(f, keep_bytes, chunk_bytes=None):
    """Discard everything but the newest `keep_bytes` of queued capture.
    Returns the number of bytes dropped (0 if nothing needed dropping).

    Only safe to call BETWEEN utterances -- mid-utterance this would excise
    the middle of what someone is saying. The one call site is right after
    transcribe() returns, which is exactly that moment."""
    chunk_bytes = NBYTES if chunk_bytes is None else chunk_bytes
    try:
        fd = f.fileno()
    except (OSError, ValueError):
        return 0
    drop = backlog_drop_bytes(pending_bytes(fd), keep_bytes, chunk_bytes)
    dropped = 0
    while dropped < drop:
        chunk = f.read(min(chunk_bytes, drop - dropped))
        if not chunk:
            break
        dropped += len(chunk)
    return dropped


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
    """POST the WAV to the whisper server and return its text.

    Returns None when we could not get an answer out of the server at all
    (unreachable, timeout, HTTP error, unparseable body, no "text" key) and
    "" only when the server genuinely transcribed the clip as nothing.
    Until 2026-07-25 this returned "" for both, which made an unreachable
    server indistinguishable from a silent room -- the console just stopped
    responding, with no line anywhere saying why (FOCUS.md 2026-07-23 00:40).
    A FORM, not a raw body: whisper.cpp answers "Invalid request" to the
    shape mandark's dead service took. Measured against the container.

    Still never blocks or raises: a flaky network call must not take the
    capture loop down with it, only stop lying about what happened."""
    import json
    try:
        with open(wav_path, "rb") as f:
            wav = f.read()
        edge = "----crt-stt-%d" % os.getpid()
        data = b""
        for name, value in (("response_format", "json"), ("language", "en")):
            data += ('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n'
                     % (edge, name, value)).encode()
        data += ('--%s\r\nContent-Disposition: form-data; name="file"; '
                 'filename="utterance.wav"\r\nContent-Type: audio/wav\r\n\r\n'
                 % edge).encode() + wav + b"\r\n"
        data += ("--%s--\r\n" % edge).encode()
        req = urllib.request.Request(
            WHISPER_SERVER, data=data,
            headers={"Content-Type": "multipart/form-data; boundary=%s" % edge})
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


def local_whisper_available():  # checked live, not cached, so tests can swap WBIN/MODEL
    return os.access(WBIN, os.X_OK) and os.path.isfile(MODEL)


def transcribe_local(feed):  # same None/""/text contract as transcribe_remote()
    try:
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
            text = transcribe_remote(feed)
            if text is None and WHISPER_LOCAL_FALLBACK and local_whisper_available():
                return transcribe_local(feed)  # crt#132
            return text
        return transcribe_local(feed)
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


def emit(text, peak=1.0, heard_at=None):
    """`heard_at`, when given, is when the speaker actually stopped talking
    (captured before transcribe() ran) -- see the caller's own note. It is
    the clock the arm window measures against, NOT the moment this function
    happens to run, which can trail the real utterance by however long
    whisper/the network took. Defaults to None (falls through to real
    time.time() inside crt-wake-arm.py, the old behavior) so callers that
    don't care about arm-window precision are unaffected."""
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
        overridden = key in PERSONA_CONTROL_OVERRIDES and PERSONA_CONTROL_OVERRIDES[key]()
        is_control = " " not in text and key in CONTROL and not overridden

        # Arm-window follow-up check (opt-in, WAKE_ARM_ENABLED, see
        # bin/crt-wake-arm.py) -- MUST run before the normal gate below,
        # since its entire point is letting a follow-up through WITHOUT
        # repeating the wake word. When disarmed/expired/disabled this is
        #   [rest: vault:crt/header-archaeology-20260817.md]
        arm_match = None
        if WAKE_ARM_ENABLED and not is_control and ARM_STATE.armed:
            arm_match = classify_wake_match(text)

        if WAKE_ARM_ENABLED and not is_control and \
                wake_arm.consume_arm_with_followup(ARM_STATE, text,
                                                   wake_match=arm_match,
                                                   now=heard_at):
            # Before the dispatch, not after: this utterance is already in
            # stt.log (written at the top of emit), and the window that
            # matters to the reader is the one this consume just slid, re-armed
            # or closed.
            publish_arm_window()
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
        # ...and not when the keystroke has nowhere to land (2026-07-25). An
        # earcon is this console's way of saying "done"; saying it for a key
        # that reached a screensaver is the same confidently-wrong report
        # send_to_claude() just stopped making, in the one channel the person
        # is actually listening to. Silence here is not silence overall:
        # send_to_claude() prints every one and puts the reason on window 1.
        if EARCON_ON_CONTROL and is_control and not PANE_IS_IDLE_FACE:
            play_earcon("control")
        elif EARCON_ON_ADDRESSED and not is_control:
            play_earcon("addressed")
        if WAKE_ARM_ENABLED and not is_control:
            kind, source, word = (arm_match if arm_match is not None
                                  else classify_wake_match(text))
            if kind:
                ARM_STATE.arm(text, kind, source, word, now=heard_at)
                publish_arm_window()
        label = "(key %s)" % CONTROL[key] if is_control else "->"
        if STT_DEBUG_PERSIST:
            print("%s  %s %s" % (ts, label, text))
        # Window 1 ("mono") previously only ever showed Claude's own
        # replies (crt-claude-bridge.py tailing its transcript) -- flagged
        # repeatedly in HANDOFF.md/crt-console.sh as the missing other half
        # of the conversation. Free-text utterances that actually got past
        #   [rest: vault:crt/header-archaeology-20260817.md]
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
    # bufsize=0: the kernel pipe must be the ONLY place queued audio lives.
    # A BufferedReader in front of it would hold bytes that FIONREAD cannot
    # see and drain_capture_backlog() cannot discard, so the backlog
    # measurement would quietly be wrong by up to its buffer size.
    # read_exact() already loops over short reads, which is the only
    # difference an unbuffered fd makes here.
    proc = subprocess.Popen(
        ["arecord", "-D", DEV, "-f", "S16_LE", "-c", "1", "-r", str(RATE), "-t", "raw"],
        stdout=subprocess.PIPE, stderr=err_f, bufsize=0)
    print("[crt-stt] sole reader on %s  model=%s  thr=%.1f%% (peak)"
          % (DEV, os.path.basename(MODEL), THRESH * 100))
    print(capture_pipe_report(widen_capture_pipe(proc.stdout.fileno())))
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

            # Anything handed to crt-secretary.py that has since exited badly.
            # Before the ring branch's `continue`, so a dispatch that died
            # while the phone was ringing is still reported.
            reap_dispatches()

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
                                ring_proc = start_ring_tone()
                                if ring_proc is None:
                                    # Do NOT enter the ring state machine: it
                                    # would run its phases in silence and then
                                    # print "no answer", blaming the person for
                                    # a phone that never rang.
                                    ring_state, ring_remaining = None, 0
                                    continue
                                ring_state, ring_remaining = "tone", n
                                ring_phase_until = now + RING_ON_SECS
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
                # A burst that died on its own, before we stopped it: the
                # earpiece stayed quiet. Checked every iteration (~100ms)
                # rather than at the end of the phase, so the report arrives
                # while the person is still in front of the tube.
                ring_fault = ring_proc.failure() if ring_proc else None
                if ring_fault:
                    hud, line = ring_unplayable_report(ring_fault)
                    print("\n" + line)
                    set_hud(hud)
                    ring_state, ring_proc, ring_remaining = None, None, 0
                    continue
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
                            ring_proc = start_ring_tone()
                            if ring_proc is None:
                                ring_state, ring_remaining = None, 0
                                continue
                            ring_state = "tone"
                            ring_phase_until = now + RING_ON_SECS
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
            if WAKE_ARM_ENABLED and wake_arm.check_arm_timeout(ARM_STATE, now):
                # Only on an actual transition. This tick runs every pass of
                # the capture loop; republishing an unchanged deadline here
                # would put a small write in the sole mic reader's hot path
                # for no one's benefit.
                publish_arm_window()

            if not in_utt:
                # Ducked audio does not go in the pre-roll either (2026-07-25).
                # The deque's whole job is to prepend the moments before onset,
                # since the attack of a first word sits under the threshold --
                # so anything in it is handed to whisper as the opening of the
                #   [rest: vault:crt/header-archaeology-20260817.md]
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
                    # Captured here, before transcribe() -- not after it
                    # returns -- so the arm-window clock (see emit()'s
                    # heard_at) measures from when the person actually
                    # stopped talking, not from whenever whisper/the network
                    # got around to finishing. See CRT_WAKE_ARM_SECS's own
                    # note in bin/crt-wake-arm.py for why this matters.
                    utt_end_ts = time.time()
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
                            emit(text, utt_peak, heard_at=utt_end_ts)
                        set_sideband_state("listening")
                        # Nobody read the mic for as long as that took. Keep
                        # the newest few seconds of what queued up (a
                        # follow-up utterance lands exactly there) and throw
                        # the rest away rather than answering it late.
                        dropped = drain_capture_backlog(
                            proc.stdout, int(BACKLOG_MAX_SECS * RATE * 2))
                        if dropped:
                            report_line(backlog_drop_report(dropped))
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
        #   [rest: vault:crt/header-archaeology-20260817.md]
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
