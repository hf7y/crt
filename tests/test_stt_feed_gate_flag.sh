#!/usr/bin/env bash
# Offline test for stt-feed.sh's CRT_STT_GATE opt-in gate (FOCUS.md "STT
# gate", 2026-07-20). Can't source the real script (it does unconditional
# mixer/tmux-wait side effects at the top, same reason
# test_stt_feed_secretary_flag.sh doesn't either) -- exercises the real
#   [rest: vault:crt/header-archaeology-20260817.md]
set -uo pipefail
fail=0
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)"

check() {
  local desc="$1" expected="$2" got="$3"
  if [ "$got" = "$expected" ]; then
    echo "ok - $desc"
  else
    echo "FAIL - $desc: expected [$expected], got [$got]"
    fail=1
  fi
}

use_gate() {
  local USE_GATE="${1:-0}"
  if [ "$USE_GATE" != "0" ]; then
    echo "gated"
  else
    echo "raw"
  fi
}

check "unset CRT_STT_GATE defaults to raw (ungated) path" "raw" "$(use_gate)"
check "CRT_STT_GATE=0 explicit stays ungated" "raw" "$(use_gate 0)"
check "CRT_STT_GATE=1 enables the gate" "gated" "$(use_gate 1)"

# Extract addressed_to_console() verbatim from stt-feed.sh and exercise it
# for real, against the real bin/crt-stt-solo.py + bin/stt-fixups.json --
# not a re-derived copy, so this actually catches drift in the shell side.
eval "$(sed -n '/^addressed_to_console() {/,/^}/p' "$BIN_DIR/stt-feed.sh")"

if addressed_to_console "claude what time is it"; then
  echo "ok - wake word 'claude' is addressed to console"
else
  echo "FAIL - wake word 'claude' should be addressed to console"; fail=1
fi

if addressed_to_console "slide over here"; then
  echo "ok - known mishear 'slide' is addressed to console"
else
  echo "FAIL - known mishear 'slide' should be addressed to console"; fail=1
fi

if addressed_to_console "just some room chatter"; then
  echo "FAIL - room chatter should NOT be addressed to console"; fail=1
else
  echo "ok - room chatter without a wake word is not addressed to console"
fi

if grep -q 'USE_GATE="\${CRT_STT_GATE:-0}"' "$BIN_DIR/stt-feed.sh"; then
  echo "ok - stt-feed.sh still defaults CRT_STT_GATE to 0"
else
  echo "FAIL - stt-feed.sh's CRT_STT_GATE default guard is missing/changed"
  fail=1
fi

if grep -q 'USE_GATE.*!= "0".*&&.*! addressed_to_console' "$BIN_DIR/stt-feed.sh"; then
  echo "ok - gate check still guards the escalation path"
else
  echo "FAIL - stt-feed.sh's gate check site is missing/changed"
  fail=1
fi

exit "$fail"
