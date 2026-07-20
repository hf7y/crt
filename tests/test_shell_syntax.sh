#!/usr/bin/env bash
# Cheapest possible regression guard: every .sh in bin/ must at least parse
# (bash -n). Catches the class of bug a hardware-verified-later script can
# ship with by accident -- a typo'd quote, an unclosed case -- without
# needing anything but bash itself.
set -uo pipefail
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)"
fail=0
for f in "$BIN_DIR"/*.sh; do
  if bash -n "$f" 2>/tmp/crt-syntax-err.$$; then
    echo "ok - $(basename "$f") parses"
  else
    echo "FAIL - $(basename "$f"):"
    sed 's/^/    /' /tmp/crt-syntax-err.$$
    fail=1
  fi
  rm -f /tmp/crt-syntax-err.$$
done
exit "$fail"
