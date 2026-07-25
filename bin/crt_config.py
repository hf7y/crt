#!/usr/bin/env python3
# One place to resolve a config value that more than one script needs.
#
# WHY THIS FILE EXISTS: REFACTOR-ASSESSMENT.md / ranked-backlog item 1
# ("introduce one config source ... for the port 8993, whisper URL, and
# ALSA device now retyped across many files") names exactly this, and the
# same defect keeps arriving one value at a time. This is the landing spot
# for that work, opened with the instance found on 2026-07-25 rather than
# left as a plan.
#
# THE INSTANCE: bin/stt-fixups.json -- what this console has learned about
# how this room says its wake word -- is read/written by three scripts, and
# they did not agree on the env var that moves it:
#
#   bin/crt-stt-solo.py          CRT_STT_FIXUPS       (reader: the wake gate)
#   bin/crt-calibration-game.py  CRT_STT_FIXUPS       (writer: a human's ear)
#   bin/crt-stt-training-merge.py  CRT_STT_FIXUPS_PATH  (writer: unattended)
#
# They agree on the DEFAULT, so nothing is broken with neither set -- which
# is why it has gone unnoticed. Set one of them alone and the writers and
# the reader are pointed at different files, with no error anywhere: the
# calibration game says `Saved`, the merge loop says `auto-merged`, and the
# word still does not wake it. That is the same silent shape 0ccdf13 just
# fixed one layer up, and worth closing before someone actually sets it.
#
# CANONICAL NAME: CRT_STT_FIXUPS (two of the three, plus
# tests/test_fixups_reload.py). CRT_STT_FIXUPS_PATH stays honoured rather
# than retired, because retiring it would break any live shell/tmux env on
# potato that already sets it, and this tier cannot see potato to check.
import os

BIN_DIR = os.path.dirname(os.path.abspath(__file__))

FIXUPS_DEFAULT = os.path.join(BIN_DIR, "stt-fixups.json")
FIXUPS_ENV = "CRT_STT_FIXUPS"
FIXUPS_ENV_LEGACY = "CRT_STT_FIXUPS_PATH"


def fixups_conflict_report(canonical, legacy):
    """Pure string builder. Names both values, because the whole failure is
    that two halves of the learning loop are pointed at different files and
    each one looks fine from where it stands."""
    return ("[!] %s=%s and %s=%s disagree -- using %s; the other half of "
            "the fixups loop is writing somewhere this will never read"
            % (FIXUPS_ENV, canonical, FIXUPS_ENV_LEGACY, legacy, canonical))


def fixups_path(env=None, warn=None):
    """The one answer to 'where is stt-fixups.json'. Honours both spellings,
    prefers the canonical one, and does not raise: this is called at import
    by crt-stt-solo.py, and a config-shaped complaint must never be the
    reason the STT engine fails to start. A genuine disagreement is
    reported through `warn` (default: print to the caller's own pane)."""
    env = os.environ if env is None else env
    canonical = env.get(FIXUPS_ENV)
    legacy = env.get(FIXUPS_ENV_LEGACY)
    if canonical and legacy and canonical != legacy:
        (warn or print)(fixups_conflict_report(canonical, legacy))
    return canonical or legacy or FIXUPS_DEFAULT
