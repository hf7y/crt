#!/usr/bin/env bash
# Nightly autonomous self-repair/self-tuning pass. potato-only for now --
# see SELF-REPAIR.md for the full scoping and what's deliberately NOT
# built yet (off-box surfacing, push access, actual VAD tuning numbers).
#
#   [rest: vault:crt/header-archaeology-20260817.md]
set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT_DIR="$HOME/reports/crt-self-repair"
STAMP="$(date +%Y-%m-%d_%H%M%S)"
LOG="$REPORT_DIR/$STAMP.log"
mkdir -p "$REPORT_DIR"

cd "$PROJECT_DIR"

git add -A
git commit -q -m "self-repair: pre-run snapshot $STAMP" || true

PROMPT='You are running as potato'"'"'s unattended nightly self-repair pass
(see SELF-REPAIR.md for full scope -- read it first).

Scope, in order of priority:
1. Review this run'"'"'s own STT-relevant logs (~/.crt/stt.log,
   ~/.crt/thoughts.log, ~/reports/crt-self-repair/*.log from prior
   nights) for recurring mis-hears, crashes, or environment-fit problems
   (VAD too twitchy/too sluggish for this room, gate too strict/loose).
2. You are explicitly licensed to tune aggressively -- CRT_VAD_THRESHOLD,
   CRT_VAD_START_CHUNKS, CRT_VAD_TRAIL, CRT_VAD_MAX/MIN, CRT_VAD_PREROLL,
   the STT_GATE wake-word/fixups behavior, and beyond if you find a real
   problem outside audio -- Zach'"'"'s own instruction was "maximally
   aggressive as long as it uses git right." The "git right" half is
   handled for you by the wrapper script that invoked you; your job is
   just to make real, justified changes, not to hedge.
3. Do NOT touch anything requiring physical/live-VM verification you
   cannot actually perform from here (see CLAUDE.md'"'"'s own
   "what an unattended run may do on real hardware" rule -- same logic).
4. Commit your own work in logical chunks as you go (do not rely solely
   on the wrapper'"'"'s pre/post commits -- those are a safety net, not a
   substitute for you describing WHY each change was made in its own
   commit message).
5. Write a short summary of what you changed and why to
   ~/reports/crt-self-repair/'"$STAMP"'-summary.md.

Do not ask for confirmation -- this is bypassPermissions, unattended, by
design. If you find nothing worth changing, say so in the summary rather
than inventing busywork.'

claude -p "$PROMPT" --permission-mode bypassPermissions >> "$LOG" 2>&1

cd "$PROJECT_DIR"
git add -A
git commit -q -m "self-repair: post-run snapshot $STAMP" || echo "self-repair: nothing changed this run" >> "$LOG"
