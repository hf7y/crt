#!/usr/bin/env bash
# Offline end-to-end test: audio captured DURING a capture duck must not reach
# whisper via the pre-roll deque either.
#
# f13c7a4 closed the mid-utterance half of this (a duck arriving while `in_utt`
# is true now freezes and excises), and the VAD's start gate has always refused
# to BEGIN an utterance while muted. Between those two there was still a hole:
# `pre.append(data)` ran unconditionally, ducked or not. So the pre-roll deque
# -- whose entire job is to prepend the moments just before onset, because the
# attack of a first word sits below the VAD threshold -- happily filled up with
# our own handset playback, and handed it to whisper as the opening of the
# speaker's next utterance.
#
# Reachable on the live default path: `addressed` (CRT_EARCON_ON_ADDRESSED,
# default ON) fires immediately after emit(), which is exactly when a speaker
# carries on into a follow-up utterance -- the sticky-wake-window case.
#
# Measurement is the PEAK AMPLITUDE OF THE FIRST 100ms of the WAV handed to
# whisper, not its duration: playback is emitted at 0.9 and speech at 0.3, so
# "did our own noise open this utterance" is a 3x separation, not a
# chunk-counting argument that timing jitter could flip.
#
# CRT_VAD_PREROLL is raised to 8 deliberately. At the default of 3 the same
# leak is there but only for a speaker whose onset lands within ~100ms of the
# duck lifting -- a real window, and a much narrower one to measure without
# racing the CTL line against the audio it refers to. Turning the knob up
# widens the window well past a one-chunk race, so this test pins the
# MECHANISM unambiguously rather than a lucky sample.
set -uo pipefail
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)"
fail=0

FAKE_BIN="$(mktemp -d)"
WORK="$(mktemp -d)"
trap 'rm -rf "$FAKE_BIN" "$WORK"' EXIT

# A capture device that hears loud handset playback, then the speaker starting
# up right behind it. Paced in real time (0.1s per 100ms chunk) so the CTL line
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


emit(0.8, 0.0)      # room tone, fills the preroll deque with quiet
ctl("mute 1")       # handset playback begins
emit(1.0, 0.9)      # our own playback, loud, bleeding into the mic
ctl("mute 0")
emit(0.2, 0.0)      # the beat between playback ending and the speaker starting
emit(1.2, 0.3)      # speaker -- quieter than our own playback, still over VAD
emit(1.5, 0.0)      # trailing silence ends the utterance (CRT_VAD_TRAIL=0.8)
emit(1.0, 0.0)      # a beat, so the emit above happens before EOF
EOF
chmod +x "$FAKE_BIN/arecord"

# Stands in for whisper-cli: reports the peak amplitude of the FIRST 100ms of
# the WAV it was handed. "lead" keeps it past emit()'s hallucination filter
# (needs >=2 letters).
cat > "$FAKE_BIN/fake-whisper" <<'EOF'
#!/usr/bin/env python3
import array, sys, wave
path = sys.argv[sys.argv.index("-f") + 1]
with wave.open(path) as w:
    frames = w.readframes(min(1600, w.getnframes()))
a = array.array('h')
a.frombytes(frames)
print("lead %d" % (max(abs(s) for s in a) if a else 0))
EOF
chmod +x "$FAKE_BIN/fake-whisper"

: > "$WORK/ctl"
CRT_STT_SINK=stdout \
CRT_AUDIO_DEV=plughw:9,9 \
CRT_CTL_FILE="$WORK/ctl" \
CRT_STT_LOG="$WORK/stt.log" \
CRT_WHISPER_BIN="$FAKE_BIN/fake-whisper" \
CRT_VAD_THRESHOLD=0.10 \
CRT_VAD_PREROLL=8 \
CRT_NORMALIZE=0 \
CRT_SIDEBAND=0 \
PATH="$FAKE_BIN:$PATH" \
  timeout 40 python3 "$BIN_DIR/crt-stt-solo.py" >"$WORK/out" 2>"$WORK/err"

lead="$(sed -n 's/.*lead \([0-9][0-9]*\).*/\1/p' "$WORK/stt.log" 2>/dev/null | head -1)"

if [ -z "$lead" ]; then
  echo "FAIL - no utterance reached the STT log at all (harness broken?)"
  sed -n 1,20p "$WORK/out" "$WORK/err"
  exit 1
fi

echo "ok - one utterance transcribed, leading 100ms peaks at ${lead}/32767"

# Playback is 0.9 (~29490), speech is 0.3 (~9830). Anything at or above the
# midpoint means our own playback opened the utterance.
if [ "$lead" -ge 15000 ]; then
  echo "FAIL - ducked playback led the utterance (${lead}, playback level); the preroll buffered it"
  fail=1
else
  echo "ok - the utterance opens on room tone/speech, not on playback (${lead})"
fi

net="$(awk '/^mute 1/{n++} /^mute 0/{n--} END{print n+0}' "$WORK/ctl")"
if [ "$net" -ne 0 ]; then
  echo "FAIL - CTL mute balance is $net, not 0"
  fail=1
else
  echo "ok - CTL mute balance back to 0"
fi

exit "$fail"
