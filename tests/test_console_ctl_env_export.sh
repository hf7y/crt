#!/usr/bin/env bash
# Offline test for bin/crt-console.sh: CRT_CTL_FILE must be exported before
# any tmux window is created, so crt-stt-solo.py (which only reads its own
# CTL file when CRT_CTL_FILE is non-empty) actually picks it up. Found
# 2026-07-24: this was never exported anywhere in the script, so the whole
#   [rest: vault:crt/header-archaeology-20260817.md]
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$DIR/../bin/crt-console.sh"
fail=0

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

FAKEBIN="$TMP/fakebin"
mkdir -p "$FAKEBIN"
LOG="$TMP/tmux.log"
cat > "$FAKEBIN/tmux" <<'EOF'
#!/usr/bin/env bash
echo "CRT_CTL_FILE=${CRT_CTL_FILE:-<unset>}" >> "$TMUX_LOG"
case "$1" in
  has-session) exit 1 ;;   # never a pre-existing session
  attach) exit 0 ;;
  *) exit 0 ;;
esac
EOF
chmod +x "$FAKEBIN/tmux"

: > "$LOG"
env -u CRT_CTL_FILE \
  TMUX_LOG="$LOG" PATH="$FAKEBIN:$PATH" \
  CRT_IP_FLASH_SECS=0 \
  CRT_MANDARK_CONF="$TMP/no-such-mandark.conf" \
  CRT_TMUX_SESSION="testsess-ctl" \
  bash "$SCRIPT" >/dev/null 2>&1

if grep -q "CRT_CTL_FILE=<unset>" "$LOG"; then
  echo "FAIL: CRT_CTL_FILE was never exported to spawned tmux windows"
  fail=1
else
  echo "PASS: CRT_CTL_FILE is exported (defaults to ~/.crt/ctl) before any window is created"
fi

# An explicit caller-provided value must win, same override contract as
# every other CRT_* knob in this script (CRT_AUDIO_DEV, CRT_WHISPER_SERVER).
: > "$LOG"
CUSTOM="$TMP/custom-ctl"
TMUX_LOG="$LOG" PATH="$FAKEBIN:$PATH" \
  CRT_CTL_FILE="$CUSTOM" \
  CRT_IP_FLASH_SECS=0 \
  CRT_MANDARK_CONF="$TMP/no-such-mandark.conf" \
  CRT_TMUX_SESSION="testsess-ctl2" \
  bash "$SCRIPT" >/dev/null 2>&1

if grep -q "CRT_CTL_FILE=$CUSTOM" "$LOG"; then
  echo "PASS: an explicit CRT_CTL_FILE override is preserved, not clobbered"
else
  echo "FAIL: explicit CRT_CTL_FILE override was not preserved"
  fail=1
fi

exit "$fail"
