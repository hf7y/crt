#!/usr/bin/env bash
# Offline test: crt-earcon.sh must have the sideband mute flag present
# during playback and gone afterward -- verified via a fake `aplay` on
# PATH that records whether the mute file existed at the moment it ran.
set -uo pipefail
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)"
fail=0

FAKE_BIN="$(mktemp -d)"
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$FAKE_BIN" "$TMPDIR"' EXIT

# sox faked rather than required -- what is under test is the mute FLAG FILE's
# lifetime around playback, not the synth. This file used to skip itself
# wholesale on a runner without sox, which is every runner this batch tier has
# (2026-07-25).
cat > "$FAKE_BIN/sox" <<'EOF'
#!/usr/bin/env bash
for a in "$@"; do
  case "$a" in *.wav) : > "$a" ;; esac
done
exit 0
EOF
chmod +x "$FAKE_BIN/sox"

MUTE_FILE="$TMPDIR/sideband.mute"
OBSERVED="$TMPDIR/observed"

# crt-earcon.sh's capture duck appends to CRT_CTL_FILE, which defaults to the
# REAL ~/.crt/ctl -- the channel a running crt-stt-solo.py reads live
# (2026-07-25). This test carefully sandboxed the mute file it knew about and
# let the duck write to the live box. tests/run_tests.sh pins this for the
# whole suite; this covers running this file on its own.
export CRT_CTL_FILE="${CRT_CTL_FILE:-$TMPDIR/ctl}"

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
