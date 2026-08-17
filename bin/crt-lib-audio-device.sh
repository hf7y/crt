# Shared by-name capture-device resolution for bash audio tools. Bash port
# of crt-stt-solo.py's resolve_capture_device_by_name()/_detect_capture_device()
# (commit 3b87b14, 2026-07-24) -- a hardcoded ALSA card index (plughw:0,0)
# means something different on every box a script happens to run on: potato's
#   [rest: vault:crt/header-archaeology-20260817.md]

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
