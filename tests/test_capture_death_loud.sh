#!/usr/bin/env bash
# Offline test: when capture dies, crt-stt-solo.py must say so and exit
# NONZERO -- it must not quietly return 0 and leave a console that looks
# alive but hears nothing.
#
# This is the still-open half of the 2026-07-23 07:10 finding. That note has
# two parts: the capture device was resolved by a hardcoded card index (fixed
# 2026-07-24 by resolve_capture_device_by_name), AND "the process restarted
# silently exits (no error, no capture) rather than failing loudly" -- which
# was never actually closed. Name resolution removes one cause of a dead
# device; it does nothing about the next one (USB replug mid-session, the
# device grabbed by a second reader, an ALSA config change). The observable
# contract tested here is what makes any of those debuggable: a real message
# on the pane, arecord's own stderr quoted, and an exit code a supervisor or
# a human reading `echo $?` can actually see.
set -uo pipefail
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)"
fail=0

FAKE_BIN="$(mktemp -d)"
WORK="$(mktemp -d)"
trap 'rm -rf "$FAKE_BIN" "$WORK"' EXIT

# An arecord that fails exactly the way a nonexistent capture device does.
cat > "$FAKE_BIN/arecord" <<'EOF'
#!/usr/bin/env bash
if [ "${1:-}" = "-l" ]; then
  echo "**** List of CAPTURE Hardware Devices ****"
  exit 0
fi
echo "arecord: main:830: audio open error: No such file or directory" >&2
exit 1
EOF
chmod +x "$FAKE_BIN/arecord"

CRT_STT_SINK=stdout CRT_AUDIO_DEV=plughw:9,9 PATH="$FAKE_BIN:$PATH" \
  timeout 30 python3 "$BIN_DIR/crt-stt-solo.py" >"$WORK/out" 2>"$WORK/err"
rc=$?

if [ "$rc" -eq 0 ]; then
  echo "FAIL - crt-stt-solo.py exited 0 with dead capture (the original silent-exit bug)"
  fail=1
elif [ "$rc" -eq 124 ]; then
  echo "FAIL - crt-stt-solo.py hung instead of reporting dead capture"
  fail=1
else
  echo "ok - crt-stt-solo.py exited nonzero ($rc) when capture died"
fi

out="$(cat "$WORK/out" "$WORK/err" 2>/dev/null)"
for needle in "CAPTURE DIED" "plughw:9,9" "audio open error" "CRT_AUDIO_DEV"; do
  case "$out" in
    *"$needle"*) echo "ok - death report mentions '$needle'" ;;
    *) echo "FAIL - death report never mentions '$needle'"; fail=1 ;;
  esac
done

exit "$fail"
