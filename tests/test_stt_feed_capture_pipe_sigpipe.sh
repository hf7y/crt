#!/usr/bin/env bash
set -uo pipefail
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)"
fail=0

FAKE_BIN="$(mktemp -d)"
WORK="$(mktemp -d)"
trap 'rm -rf "$FAKE_BIN" "$WORK"' EXIT

cat > "$FAKE_BIN/arecord" <<'EOF'
#!/usr/bin/env bash
while true; do printf '%01000d' 0; done
EOF
chmod +x "$FAKE_BIN/arecord"

cat > "$FAKE_BIN/sox" <<'EOF'
#!/usr/bin/env bash
out=""
prev=""
for a in "$@"; do
  if [ "$prev" = "-" ]; then out="$a"; fi
  prev="$a"
done
read -r -N 1000 _ || true
echo fake-wav-data > "$out"
exit 0
EOF
chmod +x "$FAKE_BIN/sox"

snippet="$(sed -n '/^  # Capture with `arecord`/,/^  sox_rc=\${PIPESTATUS\[1\]}/p' \
  "$BIN_DIR/stt-feed.sh")"

if [ -z "$snippet" ]; then
  echo "FAIL - could not extract the capture/sox_rc construct from stt-feed.sh"
  echo "       (markers may have drifted -- see this test's sed pattern)"
  exit 1
fi

cat > "$WORK/harness.sh" <<EOF
set -euo pipefail
AUDIODEV=irrelevant
VAD_THRESHOLD=3%
wav="$WORK/utt.wav"
$snippet
echo "REACHED_AFTER sox_rc=\$sox_rc"
EOF

out="$(PATH="$FAKE_BIN:$PATH" bash "$WORK/harness.sh" 2>"$WORK/err")"
harness_rc=$?

if [ "$harness_rc" -eq 0 ] && printf '%s\n' "$out" | grep -q '^REACHED_AFTER'; then
  echo "ok - set -e does not abort on arecord's SIGPIPE death (if-wrapped pipeline)"
else
  echo "FAIL - harness aborted before sox_rc was even read (rc=$harness_rc)"
  echo "       stderr:"; sed 's/^/       /' "$WORK/err"
  fail=1
fi

got_sox_rc="$(printf '%s\n' "$out" | sed -n 's/^REACHED_AFTER sox_rc=//p')"
if [ "$got_sox_rc" = "0" ]; then
  echo "ok - sox_rc reflects sox's own exit (0), not arecord's SIGPIPE death"
else
  echo "FAIL - sox_rc was [$got_sox_rc], expected 0 (PIPESTATUS[1] not read correctly)"
  fail=1
fi

if [ -s "$WORK/utt.wav" ]; then
  echo "ok - sox's output file survives even though arecord died mid-write"
else
  echo "FAIL - no output file written; sox's success didn't produce a usable file"
  fail=1
fi

exit "$fail"
