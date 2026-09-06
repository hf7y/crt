#!/usr/bin/env bash
# Transcribe the audio that lands on this box, without having to pick it out.
# Phone audio arrives via KDE Connect into ~/Downloads mixed with everything
# else, so "which ones still need transcribing" is the actual work -- this
# answers it from the transcript directory, not from a list anyone maintains.
#
#   crt-stt-inbox.sh              every inbox audio with no transcript yet
#   crt-stt-inbox.sh <file>...    exactly these, wherever they are
#
# Transcripts land ONE per source in $CRT_STT_OUT, named after it. They do not
# land beside the audio: the inbox being cluttered is the problem, not the fix.
set -uo pipefail

INBOX="${CRT_STT_INBOX:-$HOME/Downloads}"
OUT="${CRT_STT_OUT:-$HOME/Transcripts}"
SERVER="${CRT_WHISPER_SERVER:-http://100.107.253.56:8090/inference}"
SETTLE="${CRT_STT_SETTLE:-15}"
NOSPEECH=.no-speech                # where a music-only "transcript" goes     # seconds a file must have been still
EXTS='wav mp3 m4a ogg opus aac amr flac mp4 mov'

mkdir -p "$OUT" || exit 1

transcribe() {  # <audio> -- 0 transcribed, 1 failed, 2 already done
  local src="$1" name txt tmp
  name="$(basename -- "$src")"; txt="$OUT/$name.txt"
  if [ -s "$txt" ] || [ -s "$OUT/$NOSPEECH/$name.txt" ]; then return 2; fi
  tmp="$(mktemp -d)" || return 1
  # RESAMPLED FIRST, ALWAYS: the server takes wav and mp3 as they are, but
  # rejects m4a outright -- and a phone voice memo is m4a or opus.
  # -nostdin IS LOAD-BEARING: without it ffmpeg eats the rest of the NUL-separated
  # file list off stdin, and the loop skips or mangles every file after the first.
  if ! ffmpeg -nostdin -y -loglevel error -i "$src" -ar 16000 -ac 1 -c:a pcm_s16le "$tmp/a.wav" 2>"$tmp/err"; then
    printf 'crt-stt-inbox: ffmpeg could not read %s: %s\n' "$name" "$(tail -1 "$tmp/err")" >&2
    rm -rf "$tmp"; return 1
  fi
  if ! curl -sf --max-time 300 -F "file=@$tmp/a.wav" -F 'response_format=json' "$SERVER" \
     | python3 -c 'import sys,json; print(json.load(sys.stdin)["text"].strip())' > "$tmp/t"; then
    printf 'crt-stt-inbox: %s did not answer for %s\n' "$SERVER" "$name" >&2
    rm -rf "$tmp"; return 1
  fi
  # Written only once it is whole: a half-written transcript is indistinguishable
  # from a short one, and this file is also the "already done" marker.
  # A track with no speech transcribes as "(upbeat music)" and nothing else.
  # That is not a transcript, and 8 of the first 29 files here were exactly it --
  # keeping them in $OUT rebuilds the pile the inbox already was. It still has
  # to mark the file as done, so it moves aside instead of being discarded.
  # Strip every (parenthesised) and [bracketed] annotation and all whitespace:
  # what is left is speech, or there was none. A character class cannot express
  # this without ']' closing it early, which is how the first version silently
  # never matched.
  if [ -z "$(sed -e 's/([^)]*)//g' -e 's/\[[^]]*\]//g' -e 's/[[:space:]]//g' "$tmp/t")" ]; then
    mkdir -p "$OUT/$NOSPEECH"; mv "$tmp/t" "$OUT/$NOSPEECH/$name.txt"; rm -rf "$tmp"
    return 3
  fi
  mv "$tmp/t" "$txt"; rm -rf "$tmp"
  return 0
}

collect() {  # the inbox's untranscribed audio, newest first, NUL-separated
  local find_args=() e
  for e in $EXTS; do find_args+=(-iname "*.$e" -o); done
  unset 'find_args[${#find_args[@]}-1]'
  # -mmin: a file KDE Connect is still writing decodes as truncated or not at
  # all, and the watcher fires on the first byte. Let it land, then take it.
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
      3) ;;   # no speech in it: marked done, counted as nothing, notifies nobody
    esac
  done
}

# Process substitution, NOT a pipe: `collect | run` puts run in a subshell and
# every count it makes is discarded at the `done`, so a failed file exits 0.
if [ $# -gt 0 ]; then run < <(printf '%s\0' "$@"); else run < <(collect); fi

[ "$done_n" = 0 ] && [ "$fail_n" = 0 ] && exit 0

msg="$done_n transcribed"
[ "$fail_n" -gt 0 ] && msg="$msg, $fail_n failed"
[ -n "$last" ] && msg="$msg -- $(head -c 160 "$OUT/$last.txt")"
printf 'crt-stt-inbox: %s\n' "$msg"
# The notification is the whole point on the desktop: the transcript arrives
# without anyone going to look for it. Absent notify-send, the line above is it.
# Only a transcript notifies. A file that is not decodable audio is retried on
# every run and would otherwise cry wolf forever from the desktop; it stays in
# the exit code and the journal, where a retry loop belongs.
[ "$done_n" -gt 0 ] && command -v notify-send >/dev/null &&
  notify-send -a crt-stt "STT: $done_n transcribed" "$msg"

[ "$fail_n" -gt 0 ] && exit 1
exit 0
