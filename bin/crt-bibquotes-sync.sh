#!/usr/bin/env bash
# Syncs bibliothecaire's published quotes.txt from its Samba share into a
# LOCAL cache potato's idle-bait can read with zero network calls at
# render time (2026-07-28, Zach-directed: "idlebait also show page92
# excerpts via \\192.168.0.27\bibquotes").
#
# NON-API-BY-DESIGN, preserved: bin/crt-book-idle-bait.py's own header
# rule is that neither register it draws from ever hits the network at
# idle-bait time. This script is the thing that keeps the local copy
# fresh SEPARATELY -- run it by hand, from cron, or in a loop (see
# --daemon below), never from inside the idle-bait render path itself.
#
# The share (mandark, Samba, anonymous read-only, confirmed live
# 2026-07-28 via `smbclient -L //192.168.0.27 -N`): quotes.txt is the
# ONE file this script needs -- "already filtered; consumers need no
# policy logic" per that share's own README.txt. The *-p92.txt/.png/
# manifest.json files are the raw scan corpus bibliothecaire itself
# works from; deliberately NOT synced here, this console only wants the
# curated output.
#
# Usage:
#   crt-bibquotes-sync.sh              # one fetch, then exit
#   crt-bibquotes-sync.sh --daemon      # loop, re-fetch every
#                                        CRT_BIBQUOTES_SYNC_SECS
# Env:
#   CRT_BIBQUOTES_SHARE (default //192.168.0.27/bibquotes)
#   CRT_BIBQUOTES_REMOTE_FILE (default quotes.txt)
#   CRT_BIBQUOTES_PATH (default ~/.crt/bibquotes.txt) -- same var
#     bin/crt-book-game.py's BIBQUOTES_LOCAL_PATH reads
#   CRT_BIBQUOTES_SYNC_SECS (default 3600) -- --daemon re-fetch interval
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
