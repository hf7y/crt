#!/usr/bin/env bash
# Displays the crt inner-monologue log live on screen, word-wrapped to the
# CRT's width. This is meant to be the thing actually showing on the CRT --
# point a tmux window at this to "hijack" the display for the roleplay/status
# stream (see bin/crt-think.sh, which appends the lines this tails).
set -uo pipefail
LOG="${CRT_THOUGHT_LOG:-$HOME/.crt/thoughts.log}"
WIDTH="${CRT_PAGER_WIDTH:-40}"
mkdir -p "$(dirname "$LOG")"
touch "$LOG"
tail -n 20 -f "$LOG" | fold -s -w "$WIDTH"
