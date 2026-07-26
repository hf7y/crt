# Shared by-name capture-device resolution for bash audio tools. Bash port
# of crt-stt-solo.py's resolve_capture_device_by_name()/_detect_capture_device()
# (commit 3b87b14, 2026-07-24) -- a hardcoded ALSA card index (plughw:0,0)
# means something different on every box a script happens to run on: potato's
# onboard vs. USB mic, or mandark's own HDA card. That's the exact bug behind
# the 2026-07-24 16:12 FOCUS.md note "batch run audio tests are outputting to
# mandark card, not pi" -- crt-audio-doctor.sh/crt-capture-watchdog.sh used to
# default straight to card 0 regardless of which box ran them.
#
# Source this file, then:
#   crt_resolve_capture_device_by_name "$arecord_l_text" [name_pattern]
#     Pure string parse (no subprocess) -- "plughw:<card>,<device>" for the
#     first CAPTURE card whose bracketed name contains name_pattern
#     (case-insensitive, default $CRT_AUDIO_DEV_NAME or "USB Audio"). If no
#     NAME matches but the listing does name capture cards, the first LISTED
#     card, with a warning on stderr. "plughw:0,0" only when the listing
#     names no cards at all, also warned.
#
# 2026-07-25: those last two cases used to be one, and it was plughw:0,0.
# This port fell back to a hardcoded index on a name miss while its Python
# original (crt-stt-solo.py) deliberately did not -- and card 0 is precisely
# the device that broke live on potato, where it is the onboard playback-only
# card, absent from a CAPTURE listing entirely: arecord on it exits instantly
# having produced nothing. crt-capture-watchdog.sh reads that as a dead mic,
# runs recover() -- which pkills the console's real arecord -- and does it
# again every cooldown. A name miss is a guess either way; it should at least
# be a guess at a card that exists, and it should say so out loud. Warnings
# go to stderr because every caller here reads stdout with $(...).
#   crt_resolve_capture_card_by_name "$arecord_l_text" [name_pattern]
#     Same match, but prints just the card number (for `amixer -c`).
#   crt_detect_capture_device "$explicit" [name_pattern]
#     $explicit (usually "$CRT_AUDIO_DEV" et al) wins outright if non-empty
#     -- name resolution never runs, same manual-override posture as the
#     Python version. Otherwise runs `arecord -l` itself and resolves by name.

crt_resolve_capture_device_by_name() {
  local arecord_text="${1:-}"
  local pattern="${2:-${CRT_AUDIO_DEV_NAME:-USB Audio}}"
  local needle line card name dev lname first="" seen=""
  needle=$(printf '%s' "$pattern" | tr '[:upper:]' '[:lower:]')
  while IFS= read -r line; do
    if [[ "$line" =~ ^card\ ([0-9]+):.*\[(.*)\],\ device\ ([0-9]+): ]]; then
      card="${BASH_REMATCH[1]}"; name="${BASH_REMATCH[2]}"; dev="${BASH_REMATCH[3]}"
      lname=$(printf '%s' "$name" | tr '[:upper:]' '[:lower:]')
      if [ -n "$needle" ] && [[ "$lname" == *"$needle"* ]]; then
        printf 'plughw:%s,%s\n' "$card" "$dev"
        return 0
      fi
      [ -z "$first" ] && first="plughw:${card},${dev}"
      seen="${seen:+$seen, }'${name}'"
    fi
  done <<< "$arecord_text"
  # Nothing matched by NAME. Guess, but never silently -- see the header.
  if [ -n "$first" ]; then
    printf '[crt-audio] WARNING: no capture card NAMED %s in `arecord -l`; guessing %s, the first one listed. Cards seen: %s. Set CRT_AUDIO_DEV_NAME to match this box'"'"'s adapter.\n' \
      "'$pattern'" "$first" "$seen" >&2
    printf '%s\n' "$first"
    return 0
  fi
  printf '[crt-audio] WARNING: `arecord -l` listed NO capture cards at all; falling back to plughw:0,0, which may not be a capture device on this box.\n' >&2
  printf 'plughw:0,0\n'
}

crt_resolve_capture_card_by_name() {
  crt_resolve_capture_device_by_name "$@" | sed -n 's/^plughw:\([0-9]*\),.*/\1/p'
}

crt_detect_capture_device() {
  local explicit="${1:-}"
  local pattern="${2:-}"
  if [ -n "$explicit" ]; then
    printf '%s\n' "$explicit"
    return 0
  fi
  crt_resolve_capture_device_by_name "$(arecord -l 2>/dev/null)" "$pattern"
}
