#!/usr/bin/env bash
# Offline test: crt-earcon.sh's handset path must write "mute 1" then
# "mute 0" to the CTL file around playback -- the code-fix half of the
# stability-bar handset play-while-capture item (crt-earcon-loopback-test.py
# measured the handset output as the same USB adapter as the live capture
#   [rest: vault:crt/header-archaeology-20260817.md]
set -uo pipefail
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)"
fail=0

FAKE_BIN="$(mktemp -d)"
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$FAKE_BIN" "$TMPDIR"' EXIT

CTL_FILE="$TMPDIR/ctl"
cat > "$FAKE_BIN/aplay" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
chmod +x "$FAKE_BIN/aplay"

# What is under test here is the CTL-file duck, not the synth math, so sox is
# faked rather than required. It used to be `command -v sox || skip`, which
# meant this whole file silently did nothing on any runner without sox
# installed -- including this one (2026-07-25).
cat > "$FAKE_BIN/sox" <<'EOF'
#!/usr/bin/env bash
for a in "$@"; do
  case "$a" in *.wav) : > "$a" ;; esac
done
exit 0
EOF
chmod +x "$FAKE_BIN/sox"

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

# 2026-07-25: the duck was keyed on the literal word "handset", so naming the
# same hardware by its ALSA device -- or naming no device at all, which is
# what crt-idle-teaser.sh's chime() and crt-secretary.py's play_earcon()
# actually do -- played into the live mic without ducking it. Both now duck.
ducks() {   # $1 = human label, rest = args to crt-earcon.sh
  local label="$1"; shift
  rm -f "$CTL_FILE"
  PATH="$FAKE_BIN:$PATH" CRT_CTL_FILE="$CTL_FILE" \
    bash "$BIN_DIR/crt-earcon.sh" "$@" >/dev/null 2>&1
  if [ -f "$CTL_FILE" ] && grep -qx "mute 1" "$CTL_FILE" && grep -qx "mute 0" "$CTL_FILE"; then
    echo "ok - $label ducked capture"
  else
    echo "FAIL - $label did not duck capture (CTL: $(cat "$CTL_FILE" 2>/dev/null | tr '\n' '/'))"
    fail=1
  fi
}

ducks "earcon on the handset's own ALSA device" ack --device "${CRT_EARCON_HANDSET_DEVICE:-plughw:1,0}"
ducks "earcon with no --device at all (idle-teaser/secretary's call shape)" ack

rm -f "$CTL_FILE"
PATH="$FAKE_BIN:$PATH" CRT_CTL_FILE="$CTL_FILE" \
  bash "$BIN_DIR/crt-earcon.sh" ack --device "${CRT_EARCON_TV_DEVICE:-plughw:2,0}" >/dev/null 2>&1
if [ -f "$CTL_FILE" ]; then
  echo "FAIL - an explicitly named non-capture device ducked anyway (over-ducking)"
  fail=1
else
  echo "ok - an explicitly named non-capture device did not duck"
fi

exit "$fail"
