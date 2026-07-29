#!/usr/bin/env bash
# The console's config, read from ONE place by everything that needs it.
# Sourced, never executed:  . "$BIN_DIR/crt-conf.sh"
#
# WHY THIS EXISTS (2026-07-29, found live). potato's console identity --
# which wake word it answers to, where earcons play, where whisper lives --
# was defined only as `export` lines in ~/.bash_profile. crt-console.sh is
# exec'd FROM that profile, so it inherited them and everything worked...
# as long as the boot path was the only path.
#
# It isn't. Restarting just the `stt` tmux window over ssh (a non-login
# shell, so no ~/.bash_profile) brought the console back up with
# CRT_EARCON_DEVICE unset -> crt-stt-solo.py's default "handset", and
# CRT_WAKE_WORD unset -> its default "claude". The console looked
# perfectly healthy: mic live, meter moving, log filling. It was beeping
# into an earpiece nobody was holding and listening for the wrong name.
# That is the exact failure shape this project keeps naming -- a silent
# wrong default that presents as working -- and a profile is the wrong
# place to hold state whose loss is invisible.
#
# Worse, found while moving these out: on potato the three exports that
# mattered most (CRT_CLAUDE_ARGS, CRT_WAKE_WORD, CRT_EARCON_DEVICE) sat
# BELOW the `exec crt-console.sh` line in ~/.bash_profile. A tty1
# autologin boot -- the normal way this console starts -- never reached
# them at all. They only ever took effect when someone happened to start
# the console by hand from an ssh login shell. So the profile was not
# merely a fragile place to keep this; for the primary boot path it was
# not working at all, and had not been since it was written.
#
# So: config lives in files under ~/.crt/, and every entry point that
# needs it sources this. A window restarted by hand comes up with the
# same identity as one started at boot, because neither one is where the
# values are written down.
#
# Files read, in order:
#   ~/.crt/console.conf   general console identity (wake word, earcon
#                         sink, whisper server, audio device). New
#                         2026-07-29. Written with ${VAR:-default} form
#                         so an explicit env var still wins over it.
#   ~/.crt/brain.conf     brain routing only (ssh host / legacy port).
#                         Pre-existing, deliberately left as its own file
#                         and read LAST: it is the one Zach flips at
#                         runtime via Brain routing, and it should win.
#   ~/.crt/mandark.conf   legacy, read only if brain.conf is absent, so an
#                         un-migrated box boots as it did rather than
#                         silently changing under someone.
#
# Override any path with CRT_CONSOLE_CONF / CRT_BRAIN_CONF /
# CRT_MANDARK_CONF (used by the tests).

# Executing this instead of sourcing it does nothing useful and would
# fail silently -- the assignments would land in a shell that then exits.
# Say so loudly rather than looking like a successful no-op.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  echo "crt-conf.sh must be SOURCED, not executed: . \$BIN_DIR/crt-conf.sh" >&2
  exit 2
fi

CRT_CONSOLE_CONF="${CRT_CONSOLE_CONF:-$HOME/.crt/console.conf}"
CRT_BRAIN_CONF="${CRT_BRAIN_CONF:-$HOME/.crt/brain.conf}"
CRT_MANDARK_CONF="${CRT_MANDARK_CONF:-$HOME/.crt/mandark.conf}"

if [ -f "$CRT_CONSOLE_CONF" ]; then
  # shellcheck disable=SC1090
  . "$CRT_CONSOLE_CONF"
fi

if [ -f "$CRT_BRAIN_CONF" ]; then
  # shellcheck disable=SC1090
  . "$CRT_BRAIN_CONF"
elif [ -f "$CRT_MANDARK_CONF" ]; then
  # shellcheck disable=SC1090
  . "$CRT_MANDARK_CONF"
fi
