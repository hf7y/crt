#!/usr/bin/env bash
# Append one line to the crt "inner monologue" / thought log. Two purposes at
# once: (1) a durable append-only log of what's actually happening, for later
# context if a session gets summarized/lost; (2) fed live to
# crt-monologue.sh, which tails it on-screen in first person -- the CRT
# narrating itself ("i'm a crt, i have a handset...").
#
# Usage: crt-think.sh "text"
set -euo pipefail
LOG="${CRT_THOUGHT_LOG:-$HOME/.crt/thoughts.log}"
mkdir -p "$(dirname "$LOG")"
# Hex seconds-since-midnight -- shorter than HH:MM:SS, still a rough clock.
secs_since_midnight=$(( $(date +%s) - $(date -d "$(date +%Y-%m-%d)" +%s) ))
printf '%05x  %s\n' "$secs_since_midnight" "$*" >> "$LOG"
