#!/usr/bin/env bash
set -uo pipefail

INBOX="${CRT_STT_INBOX:-$HOME/Downloads}"
OUT="${CRT_STT_OUT:-$HOME/Transcripts}"
SERVER="${CRT_WHISPER_SERVER:-http://100.107.253.56:8090/inference}"
SETTLE="${CRT_STT_SETTLE:-15}"
NOSPEECH=.no-speech
EXTS='wav mp3 m4a ogg opus aac amr flac mp4 mov'

mkdir -p "$OUT" || exit 1

transcribe() {  # <audio> -- 0 transcribed, 1 failed, 2 already done, 3 no speech
  local src="$1" name txt tmp
  name="$(basename -- "$src")"; txt="$OUT/$name.txt"
  if [ -s "$txt" ] || [ -s "$OUT/$NOSPEECH/$name.txt" ]; then return 2; fi
  tmp="$(mktemp -d)" || return 1
  if ! ffmpeg -nostdin -y -loglevel error -i "$src" -ar 16000 -ac 1 -c:a pcm_s16le "$tmp/a.wav" 2>"$tmp/err"; then
    printf 'crt-stt-inbox: ffmpeg could not read %s: %s\n' "$name" "$(tail -1 "$tmp/err")" >&2
    rm -rf "$tmp"; return 1
  fi
  if ! curl -sf --max-time 300 -F "file=@$tmp/a.wav" -F 'response_format=json' "$SERVER" \
     | python3 -c 'import sys,json; print(json.load(sys.stdin)["text"].strip())' > "$tmp/t"; then
    printf 'crt-stt-inbox: %s did not answer for %s\n' "$SERVER" "$name" >&2
    rm -rf "$tmp"; return 1
  fi
  if [ -z "$(sed -e 's/([^)]*)//g' -e 's/\[[^]]*\]//g' -e 's/[[:space:]]//g' "$tmp/t")" ]; then
    mkdir -p "$OUT/$NOSPEECH"; mv "$tmp/t" "$OUT/$NOSPEECH/$name.txt"; rm -rf "$tmp"
    return 3
  fi
  mv "$tmp/t" "$txt"; rm -rf "$tmp"
  return 0
}

collect() {  # untranscribed inbox audio that has stopped growing, newest first
  local find_args=() e
  for e in $EXTS; do find_args+=(-iname "*.$e" -o); done
  unset 'find_args[${#find_args[@]}-1]'
  find "$INBOX" -maxdepth 1 -type f ! -newermt "-${SETTLE} seconds" \
    \( "${find_args[@]}" \) -printf '%T@\t%p\0' 2>/dev/null \
    | sort -zrn | cut -z -f2-
}

done_n=0; fail_n=0; last=''
run() {
  local f rc
  while IFS= read -r -d '' f; do
    transcribe "$f"; rc=$?
    case $rc in
      0) done_n=$((done_n + 1)); last="$(basename -- "$f")" ;;
      1) fail_n=$((fail_n + 1)) ;;
    esac
  done
}

if [ $# -gt 0 ]; then run < <(printf '%s\0' "$@"); else run < <(collect); fi

[ "$done_n" = 0 ] && [ "$fail_n" = 0 ] && exit 0

msg="$done_n transcribed"
[ "$fail_n" -gt 0 ] && msg="$msg, $fail_n failed"
[ -n "$last" ] && msg="$msg -- $(head -c 160 "$OUT/$last.txt")"
printf 'crt-stt-inbox: %s\n' "$msg"
[ "$done_n" -gt 0 ] && command -v notify-send >/dev/null &&
  notify-send -a crt-stt "STT: $done_n transcribed" "$msg"

[ "$fail_n" -gt 0 ] && exit 1
exit 0
