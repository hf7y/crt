#!/usr/bin/env bash
# Offline test for bin/crt-console.sh: the Book Game funnel windows (book,
# bookidle, bookanswer, windowswitch) plus mono/bridge/stt must compose
# identically regardless of CRT_NO_IDLE_CLAUDE (FOCUS.md stability-bar item
# 4 -- "Book Game funnel re-verified... post VM->potato move"). Reading the
# script shows these windows are created unconditionally -- CRT_NO_IDLE_CLAUDE
# only swaps window 0 (screensaver vs resident claude) and the boot-selected
# window -- this test makes that claim mechanically checked instead of just
# read-and-assumed.
#
# No real tmux session is ever created: a fake `tmux` shim on PATH logs every
# invocation instead of executing it, so this is pure argv-shape checking, the
# same offline-safe bar as every other test here.
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
echo "$@" >> "$TMUX_LOG"
case "$1" in
  has-session) exit 1 ;;   # never a pre-existing session
  attach) exit 0 ;;
  *) exit 0 ;;
esac
EOF
chmod +x "$FAKEBIN/tmux"

run_layout() {
  local no_idle="$1"
  : > "$LOG"
  TMUX_LOG="$LOG" PATH="$FAKEBIN:$PATH" \
    CRT_NO_IDLE_CLAUDE="$no_idle" \
    CRT_IP_FLASH_SECS=0 \
    CRT_MANDARK_CONF="$TMP/no-such-mandark.conf" \
    CRT_TMUX_SESSION="testsess-$no_idle" \
    bash "$SCRIPT" >/dev/null 2>&1
}

check_windows_present() {
  local no_idle="$1"
  for w in mono bridge stt book bookidle bookanswer windowswitch; do
    if grep -q -- "-n $w " "$LOG"; then
      echo "PASS: CRT_NO_IDLE_CLAUDE=$no_idle creates '$w' window"
    else
      echo "FAIL: CRT_NO_IDLE_CLAUDE=$no_idle missing '$w' window"; fail=1
    fi
  done
}

run_layout 0
check_windows_present 0
if grep -q "select-window -t testsess-0:book" "$LOG"; then
  echo "PASS: CRT_NO_IDLE_CLAUDE=0 selects 'book' as boot-default"
else
  echo "FAIL: CRT_NO_IDLE_CLAUDE=0 did not select 'book'"; fail=1
fi

run_layout 1
check_windows_present 1
if grep -q "select-window -t testsess-1:0" "$LOG"; then
  echo "PASS: CRT_NO_IDLE_CLAUDE=1 selects window 0 (screensaver) as boot-default"
else
  echo "FAIL: CRT_NO_IDLE_CLAUDE=1 did not select window 0"; fail=1
fi
if grep -q "crt-screensaver.py" "$LOG"; then
  echo "PASS: CRT_NO_IDLE_CLAUDE=1 puts the screensaver on window 0"
else
  echo "FAIL: CRT_NO_IDLE_CLAUDE=1 did not launch the screensaver"; fail=1
fi

exit "$fail"
