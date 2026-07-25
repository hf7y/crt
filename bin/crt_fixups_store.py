#!/usr/bin/env python3
# One safe way to change stt-fixups.json (2026-07-25, twelfth cycle).
#
# That file is what this console has learned about how this room says its
# wake word, and it has TWO writers and a live reader:
#
#   crt-calibration-game.py    a human confirming a mishear by ear
#   crt-stt-training-merge.py  the `stttrain` window, every 600s unattended
#   crt-stt-solo.py            the wake gate, re-reading on every utterance
#                              since 0ccdf13
#
# Both writers did read-modify-write-whole-file through a temp path named
# `<file>.tmp` -- the SAME temp path, since 24a94ac made them agree on which
# file they were writing. Two failures follow from that:
#
#   TORN FILE. open(tmp, "w") truncates. If the merge loop's 600s tick lands
#   while someone is in the calibration game, one writer truncates the
#   other's half-finished temp and whichever os.replace() runs second (or
#   first) puts the wreckage where the real file was. os.replace protects
#   the READER from seeing a half-written file; it does nothing to protect
#   two writers from each other. What is lost is every hand-authored
#   "confirmed" entry -- the calibration game's own docstring calls those
#   "the strongest evidence this project ever collects", and they cannot be
#   re-derived, only re-earned by someone standing at the mic saying a word
#   until it is misheard the same way twice.
#
#   LOST UPDATE. Even with the tearing gone, each writer computes its new
#   dict from a snapshot read moments earlier and then writes the WHOLE
#   file. The later write silently drops whatever the earlier one added.
#
# update() closes both: the read and the write happen inside one exclusive
# flock, so the mutate callback always sees the file as it is right now, and
# the temp path carries the pid so no two writers can ever share one.
#
# Readers need nothing from this module. os.replace() is atomic, so a reader
# either sees the old file or the new one, never a mix -- which is why
# crt-stt-solo.py's FixupsFile is left alone.
import fcntl
import json
import os


def read(path):
    """The fixups as they are on disk right now. Tolerant: a missing or
    malformed file means "start from empty", never a raise -- the same
    convention crt-stt-solo.py's own loader and crt-stt-training-merge.py's
    load_fixups_file already use. A JSON document that parses but isn't an
    object (a list, a bare string) is treated the same way: it is not a
    fixups file, and refusing to overwrite it would strand the console with
    a gate it can never learn anything new for."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def dumps(data):
    """The one on-disk format. The two writers had drifted to different
    indents (2 and 4), so a human confirming a single word reflowed the
    whole git-tracked file and buried their one real change in the diff.
    Matches what bin/stt-fixups.json is actually committed as."""
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def update(path, mutate):
    """Read-modify-write `path` under an exclusive lock.

    `mutate` is called with the fixups as they are AT THAT MOMENT (read
    inside the lock, not handed in by the caller from a stale snapshot) and
    returns either a new dict to write, or None to write nothing. Returns
    whatever mutate returned, so a caller can tell "wrote it" from "decided
    not to".

    The lock is held across the read, the mutate and the rename, and no
    caller may block inside mutate waiting on a human -- both writers here
    compute in memory, so the file is held for microseconds. The lock lives
    in a sidecar `<file>.lock` rather than on the file itself, because the
    file gets replaced by rename: a lock on the old inode would mean
    nothing to whoever opened the new one."""
    lock_fd = None
    try:
        lock_fd = os.open(path + ".lock", os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
    except OSError:
        # A directory we cannot make a lock file in (read-only mount, odd
        # permissions) must not be the reason a human's confirmed mishear
        # is thrown away. Proceed unlocked -- that is exactly the behaviour
        # both writers had before this module existed, so it is a fallback
        # to the old risk, not a new one.
        if lock_fd is not None:
            os.close(lock_fd)
            lock_fd = None
    try:
        result = mutate(read(path))
        if result is None:
            return None
        # The pid is what makes concurrent writers safe: `<file>.tmp` was
        # one name shared by every process that ever wrote this file.
        tmp_path = "%s.%d.tmp" % (path, os.getpid())
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(dumps(result))
            os.replace(tmp_path, path)
        except OSError:
            # A failed write must not leave a stray temp behind for the next
            # `ls` to puzzle over, and must still reach the caller: for the
            # merge loop that is a LoopGuard report on window 1, for the
            # calibration game a visible error instead of a silent "Saved".
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        return result
    finally:
        if lock_fd is not None:
            os.close(lock_fd)   # releases the flock
