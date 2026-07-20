#!/usr/bin/env bash
# Displays the crt inner-monologue log live on screen, word-wrapped to the
# CRT's width. This is meant to be the thing actually showing on the CRT --
# point a tmux window at this to "hijack" the display for the roleplay/status
# stream (see bin/crt-think.sh, which appends the lines this tails).
set -uo pipefail
LOG="${CRT_THOUGHT_LOG:-$HOME/.crt/thoughts.log}"
DISPLAY_CONF="${CRT_DISPLAY_CONF:-$HOME/.crt/display.conf}"
# CRT_PAGER_WIDTH wins if set; otherwise the real terminal width (same
# auto-detect reasoning as crt-pager.py, 2026-07-19 -- a hardcoded 40 here
# silently misrenders on a resized VM window or a different machine's
# terminal); 40 only as a last-resort fallback if tput itself fails
# (e.g. no tty).
RAW_WIDTH="${CRT_PAGER_WIDTH:-$(tput cols 2>/dev/null || echo 40)}"

# Overscan safe margin (2026-07-20, DISPLAY-CALIBRATION.md): shrink by the
# left+right margin bin/crt-calibrate-display.py wrote, same conf format
# crt-pager.py reads. Missing file/keys = 0 margin = no-op, so this is
# silent until the calibration game has actually been run once.
margin_left=0
margin_right=0
if [ -f "$DISPLAY_CONF" ]; then
  margin_left=$(awk -F= '$1=="left"{print $2+0}' "$DISPLAY_CONF" 2>/dev/null)
  margin_right=$(awk -F= '$1=="right"{print $2+0}' "$DISPLAY_CONF" 2>/dev/null)
  [ -z "$margin_left" ] && margin_left=0
  [ -z "$margin_right" ] && margin_right=0
fi
WIDTH=$(( RAW_WIDTH - margin_left - margin_right ))
[ "$WIDTH" -lt 1 ] && WIDTH=1

mkdir -p "$(dirname "$LOG")"
touch "$LOG"
tail -n 20 -f "$LOG" | fold -s -w "$WIDTH"
