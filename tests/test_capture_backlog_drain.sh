#!/usr/bin/env bash
# Offline end-to-end test: the capture backlog that piles up during a slow
# transcription is bounded, said out loud, and never eats a real utterance.
#
# The unit half lives in tests/test_capture_backpressure.py (real pipes, real
#   [rest: vault:crt/header-archaeology-20260817.md]
set -uo pipefail
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)"
fail=0

FAKE_BIN="$(mktemp -d)"
WORK="$(mktemp -d)"
trap 'rm -rf "$FAKE_BIN" "$WORK"' EXIT

cat > "$FAKE_BIN/arecord" <<'EOF'
#!/usr/bin/env python3
import array, math, sys, time

if "-l" in sys.argv:
    print("**** List of CAPTURE Hardware Devices ****")
    sys.exit(0)

RATE, CHUNK = 16000, 1600


def emit(seconds, amp):
    for _ in range(int(seconds / 0.1)):
        a = array.array('h', (int(amp * 32767 * math.sin(2 * math.pi * 440 * i / RATE))
                              for i in range(CHUNK)))
        sys.stdout.buffer.write(a.tobytes())
        sys.stdout.buffer.flush()
        time.sleep(0.1)


emit(0.5, 0.0)      # room tone, fills the preroll deque
emit(1.0, 0.5)      # first utterance
emit(1.5, 0.0)      # trailing silence ends it (CRT_VAD_TRAIL=0.8)
emit(6.0, 0.0)      # room tone piling up while whisper takes its time
emit(1.0, 0.5)      # second utterance, spoken after the console caught up
emit(1.5, 0.0)      # and its trailing silence
emit(1.0, 0.0)      # a beat, so the emit above happens before EOF
EOF
chmod +x "$FAKE_BIN/arecord"

# A whisper that is SLOW -- the whole point. 5s of not reading the mic.
cat > "$FAKE_BIN/slow-whisper" <<'EOF'
#!/usr/bin/env python3
import sys, time, wave
time.sleep(5)
path = sys.argv[sys.argv.index("-f") + 1]
with wave.open(path) as w:
    print("dur %d" % round(w.getnframes() / float(w.getframerate()) * 100))
EOF
chmod +x "$FAKE_BIN/slow-whisper"

: > "$WORK/ctl"
CRT_STT_SINK=stdout \
CRT_AUDIO_DEV=plughw:9,9 \
CRT_CTL_FILE="$WORK/ctl" \
CRT_STT_LOG="$WORK/stt.log" \
CRT_WHISPER_BIN="$FAKE_BIN/slow-whisper" \
CRT_VAD_THRESHOLD=0.10 \
CRT_NORMALIZE=0 \
CRT_SIDEBAND=0 \
PATH="$FAKE_BIN:$PATH" \
  timeout 60 python3 "$BIN_DIR/crt-stt-solo.py" >"$WORK/out" 2>"$WORK/err"

utterances="$(grep -c 'dur ' "$WORK/stt.log" 2>/dev/null || true)"
: "${utterances:=0}"

if grep -q 'capture buffer' "$WORK/out"; then
  echo "ok - startup says how much audio can queue while whisper runs"
else
  echo "FAIL - no capture-buffer depth reported at startup"
  fail=1
fi

if grep -q 'dropped .* of backlogged audio' "$WORK/err"; then
  secs="$(sed -n 's/.*dropped \([0-9.]*\)s of backlogged audio.*/\1/p' "$WORK/err" | head -1)"
  echo "ok - the loop said it dropped backlogged audio (${secs}s)"
  # It must drop SOME of a ~5s backlog and keep ~3s of it; a drain that
  # discarded everything queued would be the old silent-loss bug with a
  # print statement bolted on.
  if awk "BEGIN{exit !($secs > 0 && $secs < 5.0)}"; then
    echo "ok - dropped ${secs}s, bounded by CRT_CAPTURE_BACKLOG_MAX_SECS"
  else
    echo "FAIL - dropped ${secs}s, which is not a bounded trim of the backlog"
    fail=1
  fi
else
  echo "FAIL - a 5s transcription stall left no trace; backlogged audio went"
  echo "       stale or was lost silently (this is the pre-fix behaviour)"
  fail=1
fi

# The drain runs BETWEEN utterances. If it ever ran during one, or trimmed
# too aggressively, this is where it would show.
if [ "$utterances" -ge 2 ]; then
  echo "ok - both utterances still reached the STT log ($utterances)"
else
  echo "FAIL - only $utterances utterance(s) transcribed; the drain ate live speech"
  sed -n 1,20p "$WORK/stt.log" "$WORK/err"
  fail=1
fi

exit "$fail"
