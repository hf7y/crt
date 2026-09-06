#!/usr/bin/env bash
# Offline test for bin/crt-stt-inbox.sh -- no whisper server, no real audio.
# ffmpeg and curl are stubbed on PATH, and the ffmpeg stub DRAINS STDIN unless
# it is passed -nostdin, because that is the bug this file exists to hold shut:
# the real ffmpeg ate the NUL-separated file list off stdin and every file
# after the first was silently skipped.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$DIR/../bin/crt-stt-inbox.sh"
fail=0

check() {
  local desc="$1" got="$2" want="$3"
  if [ "$got" = "$want" ]; then echo "PASS: $desc"
  else echo "FAIL: $desc (got '$got', want '$want')"; fail=1; fi
}

T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
mkdir -p "$T/bin" "$T/inbox" "$T/out"

cat > "$T/bin/ffmpeg" <<'STUB'
#!/usr/bin/env bash
[ "${1:-}" = "-nostdin" ] || cat > /dev/null    # the bug, faithfully
for a in "$@"; do case "$a" in *broken*) exit 1 ;; esac; done
printf 'wav' > "${@: -1}"
STUB
cat > "$T/bin/curl" <<'STUB'
#!/usr/bin/env bash
printf '{"text":" a transcript "}'
STUB
chmod +x "$T/bin/ffmpeg" "$T/bin/curl"

export PATH="$T/bin:$PATH"
export CRT_STT_INBOX="$T/inbox" CRT_STT_OUT="$T/out" CRT_STT_SETTLE=0
export CRT_WHISPER_SERVER=http://stub/inference

: > "$T/inbox/one.wav"; : > "$T/inbox/two.m4a"; : > "$T/inbox/three ipa.ogg"
: > "$T/inbox/notes.txt"

out="$("$SCRIPT" 2>&1)"; rc=$?
check "every audio file is transcribed, not just the first" \
  "$(ls "$T/out" | wc -l)" "3"
check "a name with a space survives the list" \
  "$([ -s "$T/out/three ipa.ogg.txt" ] && echo yes)" "yes"
check "the transcript is the server's text" "$(cat "$T/out/one.wav.txt")" "a transcript"
check "a non-audio file is left alone" \
  "$([ -e "$T/out/notes.txt.txt" ] && echo yes || echo no)" "no"
check "nothing is written beside the audio" \
  "$(ls "$T/inbox" | wc -l)" "4"
check "a clean run exits 0" "$rc" "0"

out="$("$SCRIPT" 2>&1)"
check "a second run re-transcribes nothing" "$out" ""

# A music-only result is whisper's non-speech annotation, not a transcript.
cat > "$T/bin/curl" <<'STUB'
#!/usr/bin/env bash
printf '{"text":" (upbeat music)\\n (jazz music) "}'
STUB
chmod +x "$T/bin/curl"
: > "$T/inbox/a track.mp3"
"$SCRIPT" >/dev/null 2>&1
check "a music-only result is kept out of the transcript directory" \
  "$([ -e "$T/out/a track.mp3.txt" ] && echo yes || echo no)" "no"
check "...but is still recorded, so it is not transcribed again every run" \
  "$([ -s "$T/out/.no-speech/a track.mp3.txt" ] && echo yes || echo no)" "yes"
check "the transcript directory holds only real transcripts" \
  "$(ls "$T/out" | wc -l)" "3"

: > "$T/inbox/broken.mp3"
"$SCRIPT" >/dev/null 2>&1
check "a file that cannot be decoded exits 1, not 0" "$?" "1"

: > "$T/inbox/still-landing.wav"
CRT_STT_SETTLE=3600 "$SCRIPT" >/dev/null 2>&1
check "a file still arriving is skipped, not transcribed truncated" \
  "$([ -e "$T/out/still-landing.wav.txt" ] && echo yes || echo no)" "no"

exit "$fail"
