#!/usr/bin/env bash
# Continuous voice-activity-triggered STT loop.
# Records utterances from the default mic (the TRRS handset), transcribes
# each one locally with whisper.cpp, and types the result into the tmux
# session/pane running Claude Code, followed by Enter.
set -euo pipefail
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SESSION="${CRT_TMUX_SESSION:-claude}"
PANE="${CRT_TMUX_PANE:-0}"
# Opt-in (2026-07-20, default OFF): route each utterance through
# bin/crt-secretary.py's playbook supervisor (SUPERVISOR.md) instead of
# typing it straight into the claude pane. Off by default because nobody
# has watched this run live yet -- see SECRETARY.md's own status note.
# The raw tmux send-keys path below is completely unchanged when this is 0.
USE_SECRETARY="${CRT_SECRETARY:-0}"
# STT gate (opt-in, default OFF, 2026-07-20 FOCUS.md "STT gate" item):
# without this, every utterance that clears VAD becomes a live Claude Code
# turn, including room chatter never addressed to the console. Not
# hardware-verified against real room noise yet -- see CLAUDE.md's
# acceptance-bar note. Shells out to crt-stt-solo.py's addressed_to_console()
# (below) rather than reimplementing the wake-word/stt-fixups.json lookup a
# second time in bash -- one place for that logic, not two that can drift.
USE_GATE="${CRT_STT_GATE:-0}"
GATE_LOG="${CRT_STT_GATE_LOG:-$HOME/.crt/thoughts.log}"

addressed_to_console() {
  BIN_DIR="$BIN_DIR" python3 -c '
import importlib.util, os, sys
spec = importlib.util.spec_from_file_location(
    "crt_stt_solo", os.path.join(os.environ["BIN_DIR"], "crt-stt-solo.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
sys.exit(0 if m.addressed_to_console(sys.argv[1]) else 1)
' "$1"
}
# Where recognized text goes:
#   claude  - type it into the tmux Claude Code pane (+ voice control keystrokes)
#   stdout  - just print timestamped transcriptions (standalone STT view / debug)
SINK="${CRT_STT_SINK:-claude}"
WHISPER_BIN="${CRT_WHISPER_BIN:-$HOME/whisper.cpp/build/bin/whisper-cli}"
WHISPER_MODEL="${CRT_WHISPER_MODEL:-$HOME/whisper.cpp/models/ggml-base.en.bin}"
VAD_THRESHOLD="${CRT_VAD_THRESHOLD:-3}%"
# Capture device. Default to the first ALSA hardware card's analog input
# rather than the ALSA "default" PCM: "default" can be silently re-routed by
# leftover PulseAudio/PipeWire drop-in configs to a server that isn't running,
# yielding zero-signal captures. Targeting the hardware plug device is
# unambiguous. Override with CRT_AUDIO_DEV (e.g. a USB codec: plughw:1,0).
AUDIODEV="${CRT_AUDIO_DEV:-plughw:0,0}"
export AUDIODEV

# Ensure the capture mixer is sane every time we start -- alsactl restore does
# not reliably survive VirtualBox audio-controller changes / reboots, and the
# HDA codec keeps reverting Input Source to "Mic" (silent; VirtualBox delivers
# the host mic to "Line"). Best-effort, guarded for hardware without these
# controls (e.g. a USB codec on bare metal). Set CRT_INPUT_SOURCE to override.
CARD="${CRT_ALSA_CARD:-0}"
INPUT_SOURCE="${CRT_INPUT_SOURCE:-Line}"
if amixer -c "$CARD" sget 'Input Source',0 2>/dev/null | grep -q "'$INPUT_SOURCE'"; then
  amixer -c "$CARD" sset 'Input Source',0 "$INPUT_SOURCE" >/dev/null 2>&1 || true
  amixer -c "$CARD" sset 'Input Source',1 "$INPUT_SOURCE" >/dev/null 2>&1 || true
fi
amixer -c "$CARD" sset 'Capture',0 100% cap >/dev/null 2>&1 || true
amixer -c "$CARD" sset 'Capture',1 100% cap >/dev/null 2>&1 || true

WORKDIR="$(mktemp -d /tmp/crt-stt.XXXXXX)"
trap 'rm -rf "$WORKDIR"' EXIT

# Wait for the target tmux pane to exist before we start feeding it (claude sink
# only; stdout mode is standalone and has nothing to wait for).
if [ "$SINK" = "claude" ]; then
  until tmux has-session -t "$SESSION" 2>/dev/null; do
    sleep 1
  done
  echo "[stt-feed] listening on '$AUDIODEV', feeding tmux session '$SESSION'..."
else
  echo "[stt-feed] listening on '$AUDIODEV' (standalone; printing transcriptions)"
  echo "--------------------------------------------------------------"
fi

i=0
while true; do
  i=$((i + 1))
  wav="$WORKDIR/utt_$i.wav"

  # Capture with `arecord` piped into `sox`, rather than sox opening ALSA itself.
  # Why: the shared `dsnoop` device (so the level meter can read the mic at the
  # same time) is only reliably shared between `arecord` clients -- sox's own
  # ALSA open (whether via `rec` or `-t alsa`) does not coexist with the meter's
  #   [rest: vault:crt/header-archaeology-20260817.md]
  if arecord -D "$AUDIODEV" -f S16_LE -c 1 -r 16000 -t raw 2>/dev/null \
    | sox -q -t raw -r 16000 -e signed -b 16 -c 1 - "$wav" \
        silence 1 0.3 "$VAD_THRESHOLD" 1 1.2 "$VAD_THRESHOLD" trim 0 20 \
        2>/dev/null; then :; fi
  sox_rc=${PIPESTATUS[1]}
  if [ "$sox_rc" -ne 0 ]; then sleep 0.2; continue; fi

  # Skip near-empty clips (mic noise / handset pickup with nothing said).
  dur=$(soxi -D "$wav" 2>/dev/null || echo 0)
  awk -v d="$dur" 'BEGIN{exit !(d<0.4)}' && continue

  # Peak-normalize the utterance before transcription. A quiet/distant mic (or
  # one fighting AC noise) can leave speech at only a few percent of full scale,
  # which whisper transcribes poorly; normalizing to near-0 dBFS gives it a
  # consistent loudness to work with. Set CRT_NORMALIZE=0 to disable.
  feed="$wav"
  if [ "${CRT_NORMALIZE:-1}" != "0" ]; then
    norm="$WORKDIR/norm_$i.wav"
    if sox "$wav" "$norm" gain -n -1 2>/dev/null; then feed="$norm"; fi
  fi

  text=$("$WHISPER_BIN" -m "$WHISPER_MODEL" -f "$feed" -nt -np 2>/dev/null \
    | tr -s ' \n' ' ' | sed 's/^ *//; s/ *$//')

  [ -z "$text" ] && continue

  # Drop whisper's canonical noise/silence hallucinations. On AC/room noise it
  # confidently emits bracketed sound tags or filler words; normalization makes
  # these worse. Don't let them get typed into claude as spurious commands.
  key=$(printf '%s' "$text" | tr 'A-Z' 'a-z' | tr -cd 'a-z')
  case "$key" in
    ''|you|thankyou|thanks|thankyouforwatching|bye\
    |musicplaying|cricketschirping|silence|blankaudio|soundeffects|applause\
    |inaudible|foreignspeech|speaking) continue ;;
  esac
  [ "${#key}" -lt 2 ] && continue

  # Standalone view: just show what was heard, timestamped, and loop. No claude,
  # no control-word keystrokes -- this mode is for watching/​debugging the STT.
  if [ "$SINK" != "claude" ]; then
    printf '%s  %s\n' "$(date +%H:%M:%S)" "$text"
    continue
  fi

  # Voice control of prompts/menus: a *single-word* utterance that is a known
  # control word is sent as the corresponding keystroke instead of being typed.
  # This lets the user answer confirmations ("yes"), submit ("enter"), dismiss
  # ("no"), and move selections ("up"/"down") by voice -- interactive menus that
  # need Enter/arrows are otherwise unusable hands-free. Multi-word phrases fall
  # through and are typed as normal text. (MIDI pads will duplicate these once
  # the controller is passed through -- unambiguous physical buttons.)
  if ! printf '%s' "$text" | grep -q ' '; then
    case "$key" in
      enter|submit|send|return|go|proceed|yes|yeah|yep|confirm|accept|okay|ok)
        echo "[stt-feed] (key) Enter"
        tmux send-keys -t "${SESSION}:${PANE}" Enter; continue ;;
      no|nope|cancel|escape|abort|dismiss|nevermind)
        echo "[stt-feed] (key) Escape"
        tmux send-keys -t "${SESSION}:${PANE}" Escape; continue ;;
      up|previous|back)
        echo "[stt-feed] (key) Up"
        tmux send-keys -t "${SESSION}:${PANE}" Up; continue ;;
      down|next)
        echo "[stt-feed] (key) Down"
        tmux send-keys -t "${SESSION}:${PANE}" Down; continue ;;
      clear|scratch|backspace)
        echo "[stt-feed] (key) clear line"
        tmux send-keys -t "${SESSION}:${PANE}" C-u; continue ;;
    esac
  fi

  if [ "$USE_GATE" != "0" ] && ! addressed_to_console "$text"; then
    echo "[stt-feed] (gated, no wake word) $text"
    mkdir -p "$(dirname "$GATE_LOG")" 2>/dev/null || true
    printf '%s  [stt-gate] dropped (no wake word): %s\n' "$(date +%H:%M:%S)" "$text" >> "$GATE_LOG" 2>/dev/null || true
    continue
  fi

  if [ "$USE_SECRETARY" != "0" ]; then
    echo "[stt-feed] -> (secretary) $text"
    python3 "$BIN_DIR/crt-secretary.py" "$text" || true
    continue
  fi

  echo "[stt-feed] -> $text"
  tmux send-keys -t "${SESSION}:${PANE}" -l "$text"
  tmux send-keys -t "${SESSION}:${PANE}" Enter
done
