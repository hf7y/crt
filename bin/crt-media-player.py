#!/usr/bin/env python3
# Voice-driven local media playback -- PARKING-LOT.md's second "primary
# product surface" job (alongside morning reports): "play the thing",
# "next", "pause" via handset voice, no Claude call for the common case
# (same "90% offline supervisor" spirit as SUPERVISOR.md).
#
# v1 scope, deliberately: command PARSING and a pluggable Backend
# interface, not a real media library search or a tuned VLC/mpv
# integration -- neither is buildable/testable without real audio
# hardware and an actual media collection, which this account's sandbox
# has neither of. FakeBackend below proves the dispatch logic end to
# end; VlcBackend is a real (untested-live) implementation using `cvlc`
# subprocess control, the same class of tool PARKING-LOT.md names.
#
# NOT an AI call anywhere in this file -- pure string parsing + shelling
# out to a media player, same as every other locally-answered
# crt-secretary.py playbook.
#
# STATUS: NOT hardware-verified. parse_media_command()/handle_media_command()
# are pure functions (given an injected backend) covered by
# tests/test_media_player.py. VlcBackend has never been run against a
# real cvlc/mpv install or real media files.
#
# KNOWN CONFLICT, narrowed and pragmatically mitigated 2026-07-21 --
# still flagged for a human, not silently closed: crt-stt-solo.py's
# CONTROL dict already claims bare "next" -> Down arrow, and
# is_control's own check (`" " not in text and key in CONTROL`) only
# ever fires for a SINGLE-WORD utterance with no space -- so the actual
# collision is narrower than first flagged: only the bare word "next"
# is contested (CONTROL has no "pause"/"resume"/"stop" entries at all,
# and every multi-word phrasing here, e.g. "next song"/"next track",
# fails is_control's space check and reaches this playbook fine either
# way). Rather than leave bare "next" permanently unreachable as a media
# command, _NEXT_TRIGGERS below drops it and relies on "skip" (never
# claimed by CONTROL) plus the multi-word phrasings instead -- a narrow,
# reversible mitigation of the CONCRETE bug (a word that could never be
# routed here), not an answer to the broader question PERSONA-CHANNEL.md
# raises (should "next" ever mean "skip the song" depending on active
# mode/persona) -- that design decision is still open for Zach, and
# reverting this one-line trigger change is easy if he'd rather resolve
# it differently (e.g. changing CONTROL instead).
#
# Usage (library use, not really a standalone CLI):
#   from crt-media-player import parse_media_command, handle_media_command, VlcBackend
import os
import re
import subprocess

MEDIA_LIBRARY_DIR = os.path.expanduser(os.environ.get("CRT_MEDIA_LIBRARY_DIR", "~/Music"))

# Ordered so longer/more specific phrasings match before a generic
# "play" fragment could steal them -- e.g. "play the next one" should
# resolve as "next", not "play" with query "the next one".
_NEXT_TRIGGERS = ("skip", "play the next one", "next track", "next song")
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
        return f"playing {query}."
    if action == "pause":
        backend.pause()
        return "paused."
    if action == "resume":
        backend.resume()
        return "resuming."
    if action == "next":
        backend.next()
        return "skipping to the next one."
    if action == "stop":
        backend.stop()
        return "stopped."
    return None
