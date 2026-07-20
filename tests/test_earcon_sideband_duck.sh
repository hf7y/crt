#!/usr/bin/env bash
# Offline test: crt-earcon.sh must have the sideband mute flag present
# during playback and gone afterward -- verified via a fake `aplay` on
# PATH that records whether the mute file existed at the moment it ran.
set -uo pipefail
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)"
fail=0

command -v sox >/dev/null 2>&1 || { echo "skip - sox not installed"; exit 0; }

FAKE_BIN="$(mktemp -d)"
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$FAKE_BIN" "$TMPDIR"' EXIT

MUTE_FILE="$TMPDIR/sideband.mute"
OBSERVED="$TMPDIR/observed"

cat > "$FAKE_BIN/aplay" <<EOF
#!/usr/bin/env bash
if [ -f "$MUTE_FILE" ]; then
  echo "muted" > "$OBSERVED"
else
  echo "NOT muted" > "$OBSERVED"
fi
exit 0
EOF
chmod +x "$FAKE_BIN/aplay"

PATH="$FAKE_BIN:$PATH" CRT_SIDEBAND_MUTE_FILE="$MUTE_FILE" \
  bash "$BIN_DIR/crt-earcon.sh" ack >/dev/null 2>&1

if [ "$(cat "$OBSERVED" 2>/dev/null)" = "muted" ]; then
  echo "ok - mute flag present during earcon playback"
else
  echo "FAIL - mute flag was not present during playback (got: $(cat "$OBSERVED" 2>/dev/null))"
  fail=1
fi

if [ -f "$MUTE_FILE" ]; then
  echo "FAIL - mute flag left behind after earcon finished"
  fail=1
else
  echo "ok - mute flag removed after earcon finished"
fi

exit "$fail"
