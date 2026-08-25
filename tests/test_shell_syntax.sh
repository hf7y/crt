#!/usr/bin/env bash
# Cheapest possible regression guard: every .sh in bin/ must at least parse
# (bash -n). Catches the class of bug a hardware-verified-later script can
# ship with by accident -- a typo'd quote, an unclosed case -- without
# needing anything but bash itself.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fail=0
# provision/dexter/zaxon/ too: the scripts that run zaxon on dexter had NO
# syntax coverage at all, and they are the ones nobody runs by hand before a
# timer fires them.
for f in "$ROOT"/bin/*.sh "$ROOT"/provision/dexter/zaxon/*.sh; do
  [ -f "$f" ] || continue
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
