#!/usr/bin/env bash
# crt-console-selfcheck.sh -- can this console still transcribe? Say so once.
#
# The console was mute for a month and told nobody: its server had been
# retired, every utterance died at step 4, and the only evidence was a
# `TRANSCRIPTION FAILED` line on a tube in an empty room (crt#132).
#
# Probes CAPABILITY, never activity, and speaks only on TRANSITION, through
# Zaxon. Witnessed by tests/test_console_selfcheck.sh: GREEN/RED capability
# probing, and the say-it-once-per-transition cases.
set -uo pipefail

DOOR="${CRT_SELFCHECK_DOOR:-http://100.107.253.56:8643/mcp}"
AGENT="${CRT_SELFCHECK_AGENT:-crt}"
SERVER=""; CHECK_ONLY=0
# The brain leg (crt#353). Its host is the same knob the console itself uses --
# ~/.crt/brain.conf's CRT_CLAUDE_SSH_HOST -- read from the environment the
# caller already sources, so this file cannot disagree with what a wake
# actually dials. Empty = no brain configured, which is a SKIP, not a RED.
BRAIN_HOST="${CRT_CLAUDE_SSH_HOST:-}"
# Per-leg predicate lines. NOT a state file: Zach, 2026-09-18, on being shown
# the two-legs-two-files design -- "I'm really skeptical about a 'state file'
# at all ... Can this just be a predicate reported somewhere? or a log?" The
# log IS the state. A transition is "this line differs from the previous one
# in field X", read when needed rather than remembered somewhere that can go
# stale. No latch, so a second leg failing while the first is already RED is
# still news; a third leg is a field, not a file; and "when did the brain go
# down" becomes grep, which the old shape could not answer at all.
LEGLOG="${CRT_SELFCHECK_LEGLOG:-$HOME/.crt/selfcheck-legs.log}"

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
  # Posted the way transcribe_remote() posts, which is what catches a server
  # speaking another dialect. GREEN/RED-on-shape witnessed by
  # tests/test_console_selfcheck.sh.
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

# The brain leg. Same two-verb protocol a wake uses (POTATO.md), so this
# probes the path that actually carries speech rather than a proxy for it.
#
# The sign-out case is why this is not just "did it answer": on 2026-09-18 the
# brain ran for hours replying "Login expired" to every utterance while the
# session existed, the pane painted and CAPTURE returned a full healthy body.
# Every layer above reported fine. Phrasings kept deliberately in step with
# crt-secretary.py's brain_signed_out() (crt#352) so the sensor and the room
# agree on what "signed out" means.
brain_verdict() {
  local pane
  [ -z "$BRAIN_HOST" ] && { printf 'SKIP\tno brain host configured'; return; }
  pane="$(echo CAPTURE | timeout "${CRT_BRAIN_PROBE_TIMEOUT:-20}" \
          ssh -o BatchMode=yes -o ConnectTimeout=10 "$BRAIN_HOST" 2>/dev/null)"
  if [ -z "$pane" ]; then
    printf 'RED\t%s did not answer CAPTURE' "$BRAIN_HOST"
  elif printf '%s' "$pane" | grep -qiE 'login expired|please run /login|invalid api key|credit balance is too low|authentication_error'; then
    printf 'RED\tthe brain is signed out -- run /login on %s' "$BRAIN_HOST"
  else
    printf 'GREEN\t%s answers CAPTURE' "$BRAIN_HOST"
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
brain_now="$(brain_verdict)"
brain_state="${brain_now%%$'\t'*}"; brain_why="${brain_now#*$'\t'}"

# stdout keeps its shape on purpose: crt-potato-status.sh parses this exact
# line (its own header says so) and the transcription verdict is still the
# headline. A RED brain does not make the console unable to transcribe.
printf '%s  %s\n' "$state" "$why"
printf 'brain %s  %s\n' "$brain_state" "$brain_why"
[ "$CHECK_ONLY" = 1 ] && exit 0

# One line, every predicate, appended. Read back for the PREVIOUS values
# before writing this tick's, so each leg's transition is its own.
prev_stt="UNKNOWN"; prev_brain="UNKNOWN"
if [ -r "$LEGLOG" ]; then
  prev_line="$(tail -n 1 "$LEGLOG")"
  for field in $prev_line; do
    case "$field" in
      stt=*)   prev_stt="${field#stt=}" ;;
      brain=*) prev_brain="${field#brain=}" ;;
    esac
  done
fi
mkdir -p "$(dirname "$LEGLOG")" 2>/dev/null
printf '%s  stt=%s brain=%s\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$state" "$brain_state" >> "$LEGLOG"

# A first tick has nothing to have changed FROM: being installed is not news.
announce() {  # leg, was, is, why, red-words, green-words
  [ "$3" = "$2" ] && return 0
  [ "$3" = SKIP ] && return 0
  [ "$2" = UNKNOWN ] && [ "$3" = GREEN ] && return 0
  if [ "$3" = RED ]; then
    send_zach "$5: $(say "$4")" || printf 'crt-console-selfcheck: %s RED and could not say so\n' "$1" >&2
  else
    send_zach "$6: $(say "$4")"
  fi
}

# send_zach REFUSES over 140 chars, tag included (crt#83): an alarm the relay
# drops is the silence this file exists to break. So the clamp is here.
say() { printf '%s' "$1" | cut -c1-85; }

announce stt   "$prev_stt"   "$state"       "$why" \
  "console cannot transcribe" "console transcribing again"
announce brain "$prev_brain" "$brain_state" "$brain_why" \
  "console cannot reach its brain" "console reaching its brain again"
