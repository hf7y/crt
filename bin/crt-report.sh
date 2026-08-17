#!/usr/bin/env bash
# Stopgap job-report writer for THIS interactive console, matching the
# scheduler's own ~/reports/<project>/LATEST.md convention (see
# `Project Archive/scheduler/bin/morning-report.sh`) so idle-bait
# (IDLE-BAIT.md) has real content even before crt's nightly Tier 2 batch
#   [rest: vault:crt/header-archaeology-20260817.md]
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
