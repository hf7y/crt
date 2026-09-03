#!/usr/bin/env bash
# crt-console-selfcheck.sh -- can this console still transcribe? Say so once.
#
# The console was mute for a month and told nobody: its server had been
# retired, every utterance died at step 4, and the only evidence was a
# `TRANSCRIPTION FAILED` line on a tube in an empty room (crt#132).
#
# Probes CAPABILITY, never activity. ~/.crt/stt.log only moves when someone
# speaks, so staleness would cry wolf over a quiet week and stay silent
# through a broken one. Asked instead: is the reader running, and does the
# server IT points at -- read from the live process, not a config file --
# answer in the shape the console needs. Speaks only on TRANSITION, through
# Zaxon: a sensor that repeats itself is one you learn to ignore.
set -uo pipefail

STATE="${CRT_SELFCHECK_STATE:-$HOME/.crt/selfcheck.state}"
DOOR="${CRT_SELFCHECK_DOOR:-http://100.107.253.56:8643/mcp}"
AGENT="${CRT_SELFCHECK_AGENT:-crt}"
SERVER=""; CHECK_ONLY=0

while [ $# -gt 0 ]; do
  case "$1" in
    --check)  CHECK_ONLY=1 ;;
    --server) SERVER="${2:?--server needs a URL}"; shift ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) printf 'crt-console-selfcheck: unknown argument: %s\n' "$1" >&2; exit 2 ;;
  esac
  shift
done

# --- the probes, in order, stopping at the first that answers ----------------
verdict() {
  local pid
  if [ -z "$SERVER" ]; then
    pid="$(pgrep -f crt-stt-solo.py | head -1)"
    [ -n "$pid" ] || { printf 'RED\tno crt-stt-solo.py is running'; return; }
    # The server the LIVE process holds: a conf file says what the NEXT
    # restart will use, which is not the question.
    SERVER="$(tr '\0' '\n' < "/proc/$pid/environ" 2>/dev/null |
              sed -n 's/^CRT_WHISPER_SERVER=//p' | head -1)"
  fi
  if [ -z "$SERVER" ]; then
    local wbin="${CRT_WHISPER_BIN:-$HOME/whisper.cpp/build/bin/whisper-cli}"
    local model="${CRT_WHISPER_MODEL:-$HOME/whisper.cpp/models/ggml-base.en.bin}"
    # Existence, not a transcription: a real one costs this Pi 15s of CPU a tick.
    [ -x "$wbin" ] && [ -f "$model" ] \
      && printf 'GREEN\ttranscribing on-device with %s' "$(basename "$model")" \
      || printf 'RED\tno server named, and no local whisper at %s' "$wbin"
    return
  fi

  local wav body
  wav="$(mktemp --suffix=.wav)" || { printf 'RED\tno temp file'; return; }
  # A tone transcribes to nothing; that the server ANSWERED in the shape the
  # console parses is the whole question. Posted the way transcribe_remote()
  # posts, which is what catches a server speaking another dialect.
  sox -n -r 16000 -c 1 "$wav" synth 0.5 sine 440 2>/dev/null
  body="$(curl -sf -m 20 -X POST "$SERVER" -F "file=@$wav" \
          -F "response_format=json" -F "language=en" 2>/dev/null)"
  rm -f "$wav"
  if [ -z "$body" ]; then
    printf 'RED\t%s did not answer' "$SERVER"
  elif ! printf '%s' "$body" | grep -q '"text"'; then
    printf 'RED\t%s answered without a transcription: %s' "$SERVER" "$(printf '%s' "$body" | head -c 60)"
  else
    printf 'GREEN\t%s answers' "$SERVER"
  fi
}

# --- saying it --------------------------------------------------------------
# Three POSTs; zaxon-watch.sh does the first of them. initialize mints the
# session id every later call carries.
send_zach() {
  local message="$1" hdr sid payload
  hdr="$(mktemp)"; trap 'rm -f "$hdr"' RETURN
  curl -s -D "$hdr" -o /dev/null -m 15 -X POST "$DOOR" \
    -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"crt-console-selfcheck","version":"1"}}}' \
    2>/dev/null
  sid="$(tr -d '\r' < "$hdr" | awk 'tolower($1)=="mcp-session-id:"{print $2}')"
  [ -n "$sid" ] || { printf 'crt-console-selfcheck: the relay door minted no session; nothing sent\n' >&2; return 1; }
  curl -s -o /dev/null -m 15 -X POST "$DOOR" -H "mcp-session-id: $sid" \
    -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
    -d '{"jsonrpc":"2.0","method":"notifications/initialized"}' 2>/dev/null
  payload="$(printf '%s' "$message" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"
  curl -s -o /dev/null -m 20 -X POST "$DOOR" -H "mcp-session-id: $sid" \
    -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
    -d "{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/call\",\"params\":{\"name\":\"send_zach\",\"arguments\":{\"message\":$payload,\"from_agent\":\"$AGENT\"}}}" 2>/dev/null
}

now="$(verdict)"
state="${now%%$'\t'*}"; why="${now#*$'\t'}"
printf '%s  %s\n' "$state" "$why"
[ "$CHECK_ONLY" = 1 ] && exit 0

was="UNKNOWN"
[ -r "$STATE" ] && was="$(head -1 "$STATE")"
mkdir -p "$(dirname "$STATE")" 2>/dev/null
printf '%s\n' "$state" > "$STATE"
[ "$state" = "$was" ] && exit 0

# send_zach REFUSES over 140 chars, tag included (crt#83): an alarm the relay
# drops is the silence this file exists to break. So the clamp is here.
say() { printf '%s' "$1" | cut -c1-85; }

if [ "$state" = RED ]; then
  send_zach "console cannot transcribe: $(say "$why")" \
    || printf 'crt-console-selfcheck: RED and could not say so\n' >&2
else
  send_zach "console transcribing again: $(say "$why")"
fi
