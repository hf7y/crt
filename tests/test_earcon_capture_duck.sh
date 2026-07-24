#!/usr/bin/env bash
# Offline test: crt-earcon.sh's handset path must write "mute 1" then
# "mute 0" to the CTL file around playback -- the code-fix half of the
# stability-bar handset play-while-capture item (crt-earcon-loopback-test.py
# measured the handset output as the same USB adapter as the live capture
# device; this can't fix the missing signal, but keeps a played tone from
# being misread as speech by crt-stt-solo.py's VAD while the adapter can't
# hear the room anyway). tv/default playback must NOT touch the CTL file at
# all -- only the handset device shares hardware with capture.
set -uo pipefail
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)"
fail=0

command -v sox >/dev/null 2>&1 || { echo "skip - sox not installed"; exit 0; }

FAKE_BIN="$(mktemp -d)"
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$FAKE_BIN" "$TMPDIR"' EXIT

CTL_FILE="$TMPDIR/ctl"
cat > "$FAKE_BIN/aplay" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
chmod +x "$FAKE_BIN/aplay"

PATH="$FAKE_BIN:$PATH" CRT_CTL_FILE="$CTL_FILE" \
  bash "$BIN_DIR/crt-earcon.sh" ack --device handset >/dev/null 2>&1

if [ -f "$CTL_FILE" ] && grep -qx "mute 1" "$CTL_FILE" && grep -qx "mute 0" "$CTL_FILE" \
   && [ "$(grep -n "mute 1" "$CTL_FILE" | head -1 | cut -d: -f1)" -lt "$(grep -n "mute 0" "$CTL_FILE" | tail -1 | cut -d: -f1)" ]; then
  echo "ok - handset earcon wrote mute 1 then mute 0 to the CTL file"
else
  echo "FAIL - handset earcon did not duck capture correctly (CTL contents: $(cat "$CTL_FILE" 2>/dev/null))"
  fail=1
fi

rm -f "$CTL_FILE"
PATH="$FAKE_BIN:$PATH" CRT_CTL_FILE="$CTL_FILE" \
  bash "$BIN_DIR/crt-earcon.sh" ack --device tv >/dev/null 2>&1

if [ -f "$CTL_FILE" ]; then
  echo "FAIL - tv earcon touched the capture CTL file (should be untouched)"
  fail=1
else
  echo "ok - tv earcon left the capture CTL file untouched"
fi

exit "$fail"
