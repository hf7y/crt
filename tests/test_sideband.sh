#!/usr/bin/env bash
# Offline tests for crt-sideband.sh's pure state->tone mapping and the
# tone-cache generation, plus crt-sideband-set.sh's state file write. No
# real playback -- sox rendering is checked (file gets created, right
# shape) but never played to a device.
set -uo pipefail
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)"
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

get_spec() {
  CRT_SIDEBAND_TEST_MODE=1 bash -c '
    source "'"$BIN_DIR"'/crt-sideband.sh"
    select_state_spec "'"$1"'"
  '
}

check "idle is silent"      "silent"        "$(get_spec idle)"
check "speaking is silent"  "silent"        "$(get_spec speaking)"
check "listening has a spec" "180 0 0.03"   "$(get_spec listening)"
check "thinking has a spec"  "180 0.5 0.05" "$(get_spec thinking)"
check "unknown state defaults silent" "silent" "$(get_spec bogus-state)"

if command -v sox >/dev/null 2>&1; then
  TMPDIR="$(mktemp -d)"
  trap 'rm -rf "$TMPDIR"' EXIT
  out=$(CRT_SIDEBAND_TEST_MODE=1 CRT_SIDEBAND_CACHE_DIR="$TMPDIR" bash -c '
    source "'"$BIN_DIR"'/crt-sideband.sh"
    ensure_tone_wav listening "180 0 0.03"
  ')
  if [ -f "$out" ]; then
    echo "ok - ensure_tone_wav generates a real cached file"
  else
    echo "FAIL - ensure_tone_wav did not produce a file at [$out]"
    fail=1
  fi
  # second call should reuse the cache, not error, and return the same path
  out2=$(CRT_SIDEBAND_TEST_MODE=1 CRT_SIDEBAND_CACHE_DIR="$TMPDIR" bash -c '
    source "'"$BIN_DIR"'/crt-sideband.sh"
    ensure_tone_wav listening "180 0 0.03"
  ')
  check "second call reuses the same cached path" "$out" "$out2"
else
  echo "skip - sox not installed, skipping tone-generation checks"
fi

TMPDIR2="$(mktemp -d)"
CRT_SIDEBAND_STATE_FILE="$TMPDIR2/state" bash "$BIN_DIR/crt-sideband-set.sh" thinking
check "crt-sideband-set.sh writes the requested state" "thinking" "$(cat "$TMPDIR2/state")"
rm -rf "$TMPDIR2"

exit "$fail"
