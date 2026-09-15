#!/usr/bin/env bash
# Syncs bibliothecaire's published quotes.txt from its Samba share into a
# LOCAL cache potato's idle-bait can read with zero network calls at
# render time (2026-07-28, Zach-directed: "idlebait also show page92
# excerpts via \\192.168.0.27\bibquotes").
#
# NON-API-BY-DESIGN, preserved: keeps the local copy fresh SEPARATELY from
# crt-book-idle-bait.py's render path. See tests/test_bibquotes.py.
set -uo pipefail

SHARE="${CRT_BIBQUOTES_SHARE:-//192.168.0.27/bibquotes}"
REMOTE_FILE="${CRT_BIBQUOTES_REMOTE_FILE:-quotes.txt}"
LOCAL_PATH="$(eval echo "${CRT_BIBQUOTES_PATH:-~/.crt/bibquotes.txt}")"
SYNC_SECS="${CRT_BIBQUOTES_SYNC_SECS:-3600}"
LOG="$(dirname "$LOCAL_PATH")/bibquotes-sync.log"

log() { printf '%s  %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$LOG" >&2; }

sync_once() {
  mkdir -p "$(dirname "$LOCAL_PATH")"
  local tmp smbclient_log
  tmp="$(mktemp)"
  # Fetch into a temp file first, atomic rename on success -- see
  # tests/test_bibquotes.py::TestBibquotesSyncScript for the
  # failure-leaves-last-good-copy cases this guards against.
  #
  # Both temp files come from mktemp, not a fixed /tmp/... name: a shared
  # host can have another tenant's process already own a fixed path, which
  # turns a transient smbclient hiccup into a permission-denied crash here
  # instead (scheduler#576).
  smbclient_log="$(mktemp)"
  if smbclient "$SHARE" -N -c "get $REMOTE_FILE $tmp" >"$smbclient_log" 2>&1; then
    mv "$tmp" "$LOCAL_PATH"
    log "synced $(wc -l < "$LOCAL_PATH") line(s) from $SHARE/$REMOTE_FILE"
  else
    rm -f "$tmp"
    log "FAILED to sync from $SHARE/$REMOTE_FILE -- keeping last good cache. smbclient said:"
    tail -5 "$smbclient_log" | while IFS= read -r line; do log "  $line"; done
  fi
  rm -f "$smbclient_log"
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
