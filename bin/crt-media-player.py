#!/usr/bin/env python3
# Voice-driven local media playback -- PARKING-LOT.md's second "primary
# product surface" job (alongside morning reports): "play the thing",
# "next", "pause" via handset voice, no Claude call for the common case
# (same "90% offline supervisor" spirit as SUPERVISOR.md).
#   [rest: vault:crt/header-archaeology-20260817.md]
import os
import re
import subprocess

MEDIA_LIBRARY_DIR = os.path.expanduser(os.environ.get("CRT_MEDIA_LIBRARY_DIR", "~/Music"))

# crt#34: read by crt-stt-solo.py to decide if bare "next" is a keystroke or
# a skip; a file because both processes are fresh-per-utterance.
MEDIA_STATE_FILE = os.path.expanduser(os.environ.get("CRT_MEDIA_STATE_FILE", "~/.crt/media-state"))

# Ordered so longer/more specific phrasings match before a generic
# "play" fragment could steal them -- e.g. "play the next one" should
# resolve as "next", not "play" with query "the next one". Bare "next" is
# back (crt#34) now that is_media_active() resolves its CONTROL collision.
_NEXT_TRIGGERS = ("next", "skip", "play the next one", "next track", "next song")
_PAUSE_TRIGGERS = ("pause", "hold on", "wait a second")
_RESUME_TRIGGERS = ("resume", "unpause", "keep going", "continue playing")
_STOP_TRIGGERS = ("stop", "stop the music", "stop playing", "turn it off")
_PLAY_PREFIXES = ("play the ", "play ", "put on ", "listen to ")


def parse_media_command(text):
    """Pure function: maps a natural-language utterance to
    {"action": "play"|"pause"|"resume"|"next"|"stop", "query": str|None},
    or None if it doesn't look like a media command at all (caller
    should leave it alone, not treat non-media speech as noise). Checked
    in a fixed order (control words before the "play <query>" prefix
    match) so a control phrase can never get misparsed as a play query."""
    low = text.lower().strip()
    if not low:
        return None
    if low in _NEXT_TRIGGERS:
        return {"action": "next", "query": None}
    if low in _PAUSE_TRIGGERS:
        return {"action": "pause", "query": None}
    if low in _RESUME_TRIGGERS:
        return {"action": "resume", "query": None}
    if low in _STOP_TRIGGERS:
        return {"action": "stop", "query": None}
    for prefix in _PLAY_PREFIXES:
        if low.startswith(prefix):
            query = low[len(prefix):].strip()
            return {"action": "play", "query": query} if query else None
    return None


class FakeBackend:
    """In-memory backend for tests -- records every call instead of
    touching a real media player, so parse+dispatch logic is fully
    testable without audio hardware."""
    def __init__(self):
        self.calls = []
        self.state = "stopped"

    def play(self, query):
        self.calls.append(("play", query))
        self.state = "playing:%s" % query

    def pause(self):
        self.calls.append(("pause", None))
        self.state = "paused"

    def resume(self):
        self.calls.append(("resume", None))
        self.state = "playing"

    def next(self):
        self.calls.append(("next", None))

    def stop(self):
        self.calls.append(("stop", None))
        self.state = "stopped"


class VlcBackend:
    """Real (never live-tested) backend: shells out to `cvlc` for a one-
    shot play, and to a VLC RC-interface socket for pause/resume/next/
    stop -- sketched per PARKING-LOT.md's own naming of VLC/ffmpeg-class
    tooling, not a finished integration. Every method swallows OSError
    (missing binary, no real media library mounted) rather than raising,
    since this account's sandbox can never actually exercise it -- a
    live crt-vm session with a real cvlc install and music library needs
    to validate and very likely revise this."""
    def __init__(self, library_dir=None):
        self.library_dir = library_dir or MEDIA_LIBRARY_DIR

    def _run(self, cmd):
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except OSError:
            return False

    def play(self, query):
        # Naive: search the library dir for a filename containing the
        # query, case-insensitive -- a real implementation likely wants
        # fuzzy matching and a proper media index, not a directory walk
        # per request. Fine for v1/untested.
        match = self._find_file(query)
        if match is None:
            return False
        return self._run(["cvlc", "--play-and-exit", match])

    def _find_file(self, query):
        if not os.path.isdir(self.library_dir):
            return None
        q = query.lower()
        for root, _, files in os.walk(self.library_dir):
            for name in files:
                if q in name.lower():
                    return os.path.join(root, name)
        return None

    def pause(self):
        return self._run(["cvlc-control", "pause"])

    def resume(self):
        return self._run(["cvlc-control", "resume"])

    def next(self):
        return self._run(["cvlc-control", "next"])

    def stop(self):
        return self._run(["cvlc-control", "stop"])


def write_media_state(state):
    """Best-effort: a persona check that can't write is no worse than one
    that was never active -- never raises into the calling playbook."""
    try:
        os.makedirs(os.path.dirname(MEDIA_STATE_FILE), exist_ok=True)
        with open(MEDIA_STATE_FILE, "w") as f:
            f.write(state)
    except OSError:
        pass


def read_media_state():
    try:
        with open(MEDIA_STATE_FILE) as f:
            return f.read().strip()
    except OSError:
        return "stopped"


def is_media_active():
    """Playing or paused counts -- there's something to skip/resume/stop.
    Only "stopped" (or never having played anything) releases "next" back
    to CONTROL's Down-arrow meaning."""
    return read_media_state() in ("playing", "paused")


def handle_media_command(text, backend):
    """Parses `text` and dispatches to `backend`, returning a spoken
    confirmation string, or None if this wasn't a media command at all
    (caller -- e.g. crt-secretary.py's playbook matcher -- should fall
    through to whatever's next, not treat None as an error)."""
    cmd = parse_media_command(text)
    if cmd is None:
        return None
    action, query = cmd["action"], cmd["query"]
    if action == "play":
        backend.play(query)
        write_media_state("playing")
        return f"playing {query}."
    if action == "pause":
        backend.pause()
        write_media_state("paused")
        return "paused."
    if action == "resume":
        backend.resume()
        write_media_state("playing")
        return "resuming."
    if action == "next":
        backend.next()
        return "skipping to the next one."
    if action == "stop":
        backend.stop()
        write_media_state("stopped")
        return "stopped."
    return None
