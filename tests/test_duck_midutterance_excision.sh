#!/usr/bin/env bash
# Offline end-to-end test: a capture duck that arrives WHILE an utterance is
# already in progress must not end up inside that utterance's audio.
#
# The bug (Zach's note on the 2026-07-25 report): crt-stt-solo.py's VAD checked
#   [rest: vault:crt/header-archaeology-20260817.md]
set -uo pipefail
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)"
fail=0

FAKE_BIN="$(mktemp -d)"
WORK="$(mktemp -d)"
trap 'rm -rf "$FAKE_BIN" "$WORK"' EXIT

# A capture device that speaks, is interrupted by handset playback mid-sentence,
# and keeps speaking. Paced in real time (0.1s per 100ms chunk) so the CTL line
# and the audio it refers to stay in step, the way they do with real arecord.
cat > "$FAKE_BIN/arecord" <<'EOF'
#!/usr/bin/env python3
import array, math, os, sys, time

if "-l" in sys.argv:
    print("**** List of CAPTURE Hardware Devices ****")
    sys.exit(0)

RATE, CHUNK = 16000, 1600
CTL = os.environ["CRT_CTL_FILE"]


def ctl(line):
    with open(CTL, "a") as f:
        f.write(line + "\n")
        f.flush()


def emit(seconds, amp):
    for _ in range(int(seconds / 0.1)):
        a = array.array('h', (int(amp * 32767 * math.sin(2 * math.pi * 440 * i / RATE))
                              for i in range(CHUNK)))
        sys.stdout.buffer.write(a.tobytes())
        sys.stdout.buffer.flush()
        time.sleep(0.1)


emit(0.5, 0.0)      # room tone, fills the preroll deque
emit(1.0, 0.5)      # speaker starts
ctl("mute 1")       # handset playback begins mid-sentence
emit(1.0, 0.5)      # our own playback, bleeding into the mic
ctl("mute 0")
emit(1.0, 0.5)      # speaker still going
emit(1.5, 0.0)      # trailing silence ends the utterance (CRT_VAD_TRAIL=0.8)
emit(1.0, 0.0)      # a beat, so the emit above happens before EOF
EOF
chmod +x "$FAKE_BIN/arecord"

# Stands in for whisper-cli: reports the DURATION of the WAV it was handed.
# "dur" keeps it past emit()'s hallucination filter (needs >=2 letters).
cat > "$FAKE_BIN/fake-whisper" <<'EOF'
#!/usr/bin/env python3
import sys, wave
path = sys.argv[sys.argv.index("-f") + 1]
with wave.open(path) as w:
    print("dur %d" % round(w.getnframes() / float(w.getframerate()) * 100))
EOF
chmod +x "$FAKE_BIN/fake-whisper"

: > "$WORK/ctl"
CRT_STT_SINK=stdout \
CRT_AUDIO_DEV=plughw:9,9 \
CRT_CTL_FILE="$WORK/ctl" \
CRT_STT_LOG="$WORK/stt.log" \
CRT_WHISPER_BIN="$FAKE_BIN/fake-whisper" \
CRT_VAD_THRESHOLD=0.10 \
CRT_NORMALIZE=0 \
CRT_SIDEBAND=0 \
PATH="$FAKE_BIN:$PATH" \
  timeout 40 python3 "$BIN_DIR/crt-stt-solo.py" >"$WORK/out" 2>"$WORK/err"

cs="$(sed -n 's/.*dur \([0-9][0-9]*\).*/\1/p' "$WORK/stt.log" 2>/dev/null | head -1)"

if [ -z "$cs" ]; then
  echo "FAIL - no utterance reached the STT log at all (harness broken?)"
  sed -n 1,20p "$WORK/out" "$WORK/err"
  exit 1
fi

echo "ok - one utterance transcribed, ${cs} centiseconds of audio"

if [ "$cs" -lt 240 ]; then
  echo "FAIL - utterance truncated at the duck (${cs}cs); it should freeze and resume, not end"
  fail=1
elif [ "$cs" -gt 360 ]; then
  echo "FAIL - ducked playback was buffered into the utterance (${cs}cs, expected ~300cs)"
  fail=1
else
  echo "ok - the ducked second was excised (${cs}cs, expected ~300cs)"
fi

# The duck must also not have left the counter unbalanced on the way out.
net="$(awk '/^mute 1/{n++} /^mute 0/{n--} END{print n+0}' "$WORK/ctl")"
if [ "$net" -ne 0 ]; then
  echo "FAIL - CTL mute balance is $net, not 0"
  fail=1
else
  echo "ok - CTL mute balance back to 0"
fi

exit "$fail"
