#!/usr/bin/env bash
# Durable, auditable record of what state a freshly-spawned Claude instance
# in this project will actually see -- and a checksum so drift (like the
# CRT_AUDIO_DEV / stale-bash_profile bug found 2026-07-21) is DETECTABLE
# instead of silently assumed. Appends one timestamped block to
# .claude/AUDIT-LOG.md (durable, synced like any other repo file via
# bin/crt-sync-vm.sh) -- never overwrites, so the log itself is a history.
#
# Usage: bin/crt-session-audit.sh          # append a record, print summary
#        bin/crt-session-audit.sh verify   # recompute hashes, diff against
#                                           # the last recorded block, exit
#                                           # nonzero + list mismatches if
#                                           # anything drifted since then
set -euo pipefail
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$BIN_DIR/.." && pwd)"
AUDIT_LOG="$REPO_DIR/.claude/AUDIT-LOG.md"

# Every file a fresh Claude instance's behavior actually depends on, in the
# order it's effectively "read" (auto-discovery, then explicit pointers).
FILES=(
  "$REPO_DIR/CLAUDE.md"
  "$REPO_DIR/.claude/SESSION-STATE.md"
  "$REPO_DIR/HANDOFF.md"
  "$HOME/.claude/settings.json"
  "$HOME/.bash_profile"
  "$REPO_DIR/bin/crt-console.sh"
  "$REPO_DIR/bin/crt-vm-watchdog.sh"
  "$REPO_DIR/bin/crt-stt-solo.py"
  "$REPO_DIR/bin/crt-monologue.py"
)

hash_file() {
  if [ -f "$1" ]; then sha256sum "$1" | cut -d' ' -f1; else echo "MISSING"; fi
}

cmd="${1:-record}"

if [ "$cmd" = "verify" ]; then
  if [ ! -f "$AUDIT_LOG" ]; then
    echo "no audit log yet -- nothing to verify against (run without 'verify' first)"
    exit 1
  fi
  drift=0
  for f in "${FILES[@]}"; do
    rel="${f/#"$HOME"/\~}"
    now=$(hash_file "$f")
    # last recorded hash for this exact path, most recent block wins (tac)
    last=$(tac "$AUDIT_LOG" | grep -m1 "^- \`$rel\` " | sed -E 's/.*`([a-f0-9]{8,64}|MISSING)`$/\1/')
    if [ -z "$last" ]; then
      echo "? $rel -- never recorded before"
      continue
    fi
    if [ "$now" != "$last" ]; then
      echo "DRIFT $rel -- was $last, now $now"
      drift=1
    fi
  done
  [ "$drift" = 0 ] && echo "no drift since last recorded audit"
  exit "$drift"
fi

mkdir -p "$REPO_DIR/.claude"
ts="$(date '+%Y-%m-%d %H:%M:%S %Z')"
{
  echo ""
  echo "## $ts"
  echo ""
  echo "Boot-read chain a fresh Claude instance actually follows:"
  echo "1. \`CLAUDE.md\` -- auto-loaded every session (Claude Code's own CLAUDE.md discovery)."
  echo "2. \`.claude/SESSION-STATE.md\` -- CLAUDE.md's own instruction says read this FIRST, before STT-MECHANISM.md."
  echo "3. \`HANDOFF.md\` -- pointed to by SESSION-STATE.md for the live-state pick-up-here summary."
  echo ""
  echo "File hashes at record time (sha256, first 12 chars shown, full below):"
  for f in "${FILES[@]}"; do
    rel="${f/#"$HOME"/\~}"
    h="$(hash_file "$f")"
    echo "- \`$rel\` \`${h:0:12}...\` \`$h\`"
  done
} >> "$AUDIT_LOG"

echo "recorded audit block at $ts -> $AUDIT_LOG"
