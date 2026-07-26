#!/usr/bin/env bash
# Offline test for bin/crt-lib-audio-device.sh -- pure string parsing of
# `arecord -l` text, no hardware needed. Bash equivalent of
# test_capture_device.py's coverage for crt-stt-solo.py's Python resolver;
# this covers the bash tools (crt-audio-doctor.sh, crt-capture-watchdog.sh)
# that used to hardcode plughw:0,0 / card 0 regardless of which box ran them
# -- the "audio tests are outputting to mandark card, not pi" bug
# (FOCUS.md, 2026-07-24 16:12).
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../bin/crt-lib-audio-device.sh
source "$DIR/../bin/crt-lib-audio-device.sh"
fail=0

POTATO_ARECORD_L='**** List of CAPTURE Hardware Devices ****
card 1: Audio [KT USB Audio], device 0: USB Audio [USB Audio]
  Subdevices: 1/1
  Subdevice #0: subdevice #0'

RENUMBERED_ARECORD_L='**** List of CAPTURE Hardware Devices ****
card 2: Audio [KT USB Audio], device 0: USB Audio [USB Audio]
  Subdevices: 1/1
  Subdevice #0: subdevice #0'

MULTI_CARD_ARECORD_L='**** List of CAPTURE Hardware Devices ****
card 0: PCH [HDA Intel PCH], device 0: ALC3271 Analog [ALC3271 Analog]
  Subdevices: 1/1
  Subdevice #0: subdevice #0
card 1: Audio [KT USB Audio], device 0: USB Audio [USB Audio]
  Subdevices: 1/1
  Subdevice #0: subdevice #0'

check() {
  local desc="$1" got="$2" want="$3"
  if [ "$got" = "$want" ]; then
    echo "PASS: $desc"
  else
    echo "FAIL: $desc (got '$got', want '$want')"
    fail=1
  fi
}

# The exact bug: mandark's own onboard card (0, "PCH") must NOT win just
# because it's card 0 -- only the USB mic should match.
check "picks the USB card among several, not card 0" \
  "$(crt_resolve_capture_device_by_name "$MULTI_CARD_ARECORD_L")" "plughw:1,0"

check "single-card potato output resolves" \
  "$(crt_resolve_capture_device_by_name "$POTATO_ARECORD_L")" "plughw:1,0"

check "follows card renumbering (USB replug)" \
  "$(crt_resolve_capture_device_by_name "$RENUMBERED_ARECORD_L")" "plughw:2,0"

check "empty arecord -l output falls back to plughw:0,0" \
  "$(crt_resolve_capture_device_by_name "" 2>/dev/null)" "plughw:0,0"

# A name miss must land on a card that EXISTS in the capture listing, not on
# the hardcoded index (2026-07-25). This port used to answer plughw:0,0 here
# while its Python original answered the first listed card -- and on potato
# card 0 is the onboard playback-only device, absent from a CAPTURE listing
# entirely, so arecord on it produces nothing at all. That reads to
# crt-capture-watchdog.sh as a dead mic, whose recover() pkills the console's
# real arecord, on a loop. Same input, same answer, both ports.
check "no matching card guesses a real capture card, not the hardcoded index" \
  "$(crt_resolve_capture_device_by_name "$MULTI_CARD_ARECORD_L" "Nonexistent Device" 2>/dev/null)" "plughw:0,0"

check "no matching card in a listing that has no card 0" \
  "$(crt_resolve_capture_device_by_name "$RENUMBERED_ARECORD_L" "Nonexistent Device" 2>/dev/null)" "plughw:2,0"

# ...and never silently. A guessed device with no warning is the silent-fail
# class this whole resolver exists to end.
check "a name miss warns on stderr and names what it saw" \
  "$(crt_resolve_capture_device_by_name "$RENUMBERED_ARECORD_L" "Nonexistent Device" 2>&1 >/dev/null \
     | grep -c "KT USB Audio")" "1"

check "a matched card says nothing on stderr" \
  "$(crt_resolve_capture_device_by_name "$POTATO_ARECORD_L" 2>&1 >/dev/null)" ""

check "an empty listing warns too" \
  "$(crt_resolve_capture_device_by_name "" 2>&1 >/dev/null | grep -c "NO capture cards")" "1"

# The warning must never reach stdout -- every caller reads this with $(...)
# and would use the warning text as a device name.
check "the warning stays off stdout" \
  "$(crt_resolve_capture_device_by_name "$RENUMBERED_ARECORD_L" "Nonexistent Device" 2>/dev/null)" "plughw:2,0"

check "card-number variant survives a warning on the same stream" \
  "$(crt_resolve_capture_card_by_name "$RENUMBERED_ARECORD_L" "Nonexistent Device" 2>/dev/null)" "2"

check "case-insensitive name match" \
  "$(crt_resolve_capture_device_by_name "$MULTI_CARD_ARECORD_L" "usb audio")" "plughw:1,0"

check "card-number-only variant matches the same card" \
  "$(crt_resolve_capture_card_by_name "$MULTI_CARD_ARECORD_L")" "1"

# Manual override must still win outright, no arecord parsing involved.
check "explicit override wins over name resolution" \
  "$(crt_detect_capture_device "plughw:9,9")" "plughw:9,9"

if [ "$fail" -eq 0 ]; then
  echo "test_audio_device_lib.sh: ALL GREEN"
else
  echo "test_audio_device_lib.sh: SOMETHING FAILED"
fi
exit "$fail"
