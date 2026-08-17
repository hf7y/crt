#!/usr/bin/env bash
# Syncs bibliothecaire's published quotes.txt from its Samba share into a
# LOCAL cache potato's idle-bait can read with zero network calls at
# render time (2026-07-28, Zach-directed: "idlebait also show page92
# excerpts via \\192.168.0.27\bibquotes").
#   [rest: vault:crt/header-archaeology-20260817.md]
set -uo pipefail

SHARE="${CRT_BIBQUOTES_SHARE:-//192.168.0.27/bibquotes}"
REMOTE_FILE="${CRT_BIBQUOTES_REMOTE_FILE:-quotes.txt}"
LOCAL_PATH="$(eval echo "${CRT_BIBQUOTES_PATH:-~/.crt/bibquotes.txt}")"
SYNC_SECS="${CRT_BIBQUOTES_SYNC_SECS:-3600}"
LOG="$(dirname "$LOCAL_PATH")/bibquotes-sync.log"

log() { printf '%s  %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$LOG" >&2; }

sync_once() {
  mkdir -p "$(dirname "$LOCAL_PATH")"
  local tmp
  tmp="$(mktemp)"
  # Fetch into a temp file first, atomic rename on success -- a failed
  # mid-transfer fetch (share down, network hiccup) must never leave a
  # truncated/partial quotes.txt as the "current" cache; idle-bait keeps
  # serving the last good copy instead.
  if smbclient "$SHARE" -N -c "get $REMOTE_FILE $tmp" >/tmp/crt-bibquotes-smbclient.out 2>&1; then
    mv "$tmp" "$LOCAL_PATH"
    log "synced $(wc -l < "$LOCAL_PATH") line(s) from $SHARE/$REMOTE_FILE"
  else
    rm -f "$tmp"
    log "FAILED to sync from $SHARE/$REMOTE_FILE -- keeping last good cache. smbclient said:"
    tail -5 /tmp/crt-bibquotes-smbclient.out | while IFS= read -r line; do log "  $line"; done
  fi
}

if [ "${1:-}" = "--daemon" ]; then
  log "bibquotes sync daemon start (interval=${SYNC_SECS}s share=$SHARE)"
  while true; do
    sync_once
    sleep "$SYNC_SECS"
  done
else
  sync_once
fi
