#!/usr/bin/env bash
# Offline test for stt-feed.sh's CRT_SECRETARY opt-in gate. Can't source the
# real script (it does unconditional mixer/tmux-wait side effects at the
# top) so this re-derives the exact guard expression -- kept in sync by
# hand with stt-feed.sh; if that expression changes, update this too.
set -uo pipefail
fail=0

check() {
  local desc="$1" expected="$2" got="$3"
  if [ "$got" = "$expected" ]; then
    echo "ok - $desc"
  else
    echo "FAIL - $desc: expected [$expected], got [$got]"
    fail=1
  fi
}

use_secretary() {
  local USE_SECRETARY="${1:-0}"
  if [ "$USE_SECRETARY" != "0" ]; then
    echo "secretary"
  else
    echo "raw"
  fi
}

check "unset CRT_SECRETARY defaults to raw send-keys path" "raw" "$(use_secretary)"
check "CRT_SECRETARY=0 explicit stays on raw path" "raw" "$(use_secretary 0)"
check "CRT_SECRETARY=1 routes through the secretary" "secretary" "$(use_secretary 1)"

# The actual guard line in stt-feed.sh -- confirm it exists verbatim, so a
# refactor that silently drops the opt-in default gets caught here even
# though this test can't exercise the live script directly.
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)"
if grep -q 'USE_SECRETARY="\${CRT_SECRETARY:-0}"' "$BIN_DIR/stt-feed.sh"; then
  echo "ok - stt-feed.sh still defaults CRT_SECRETARY to 0"
else
  echo "FAIL - stt-feed.sh's CRT_SECRETARY default guard is missing/changed"
  fail=1
fi

exit "$fail"
