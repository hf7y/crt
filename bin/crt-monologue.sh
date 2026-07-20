#!/usr/bin/env bash
# Displays the crt inner-monologue log live on screen, word-wrapped to the
# CRT's width. This is meant to be the thing actually showing on the CRT --
# point a tmux window at this to "hijack" the display for the roleplay/status
# stream (see bin/crt-think.sh, which appends the lines this tails).
set -uo pipefail
LOG="${CRT_THOUGHT_LOG:-$HOME/.crt/thoughts.log}"
# CRT_PAGER_WIDTH wins if set; otherwise the real terminal width (same
# auto-detect reasoning as crt-pager.py, 2026-07-19 -- a hardcoded 40 here
# silently misrenders on a resized VM window or a different machine's
# terminal); 40 only as a last-resort fallback if tput itself fails
# (e.g. no tty).
WIDTH="${CRT_PAGER_WIDTH:-$(tput cols 2>/dev/null || echo 40)}"
mkdir -p "$(dirname "$LOG")"
touch "$LOG"
tail -n 20 -f "$LOG" | fold -s -w "$WIDTH"
