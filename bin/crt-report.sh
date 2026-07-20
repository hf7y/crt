#!/usr/bin/env bash
# Stopgap job-report writer for THIS interactive console, matching the
# scheduler's own ~/reports/<project>/LATEST.md convention (see
# `Project Archive/scheduler/bin/morning-report.sh`) so idle-bait
# (IDLE-BAIT.md) has real content even before crt's nightly Tier 2 batch
# is unblocked (HANDOFF.md: registered, not yet actually producing
# reports). Appends one dated entry per call; never overwrites history.
#
# Usage:
#   crt-report.sh "shipped: fixed crt-announce.sh device routing"
#   crt-report.sh --blocker "sidetone needs guest-vs-host handset answer"
#   crt-report.sh --question "idle-bait quiet hours?"
#
# --blocker / --question entries also get earcon-worthy per IDLE-BAIT.md's
# rule (only genuine judgment calls get audio) -- this script doesn't play
# the earcon itself (call site's job, so it can respect the shared
# rate-limit lock), it just tags the entry so a watcher can tell.
set -euo pipefail
REPORTS_DIR="${CRT_REPORTS_DIR:-$HOME/reports/crt}"
mkdir -p "$REPORTS_DIR"

kind="note"
case "${1:-}" in
  --blocker) kind="blocker"; shift ;;
  --question) kind="question"; shift ;;
esac

msg="${*:-}"
if [ -z "$msg" ]; then
  echo "usage: crt-report.sh [--blocker|--question] <one-line summary>" >&2
  exit 2
fi

today="$REPORTS_DIR/$(date +%Y-%m-%d).md"
latest="$REPORTS_DIR/LATEST.md"
ts="$(date '+%H:%M')"

if [ ! -f "$today" ]; then
  echo "# crt session reports — $(date +%Y-%m-%d)" > "$today"
  echo "" >> "$today"
  echo "Interactive-session entries (crt-report.sh), not a nightly-batch run." >> "$today"
  echo "" >> "$today"
fi

label="note"
[ "$kind" = "blocker" ] && label="BLOCKER"
[ "$kind" = "question" ] && label="QUESTION"

echo "- **${ts} (${label}):** ${msg}" >> "$today"

cp "$today" "$latest"
echo "[crt-report] logged to $today" >&2
