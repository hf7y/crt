#!/usr/bin/env bash
# Offline test for stt-feed.sh's CRT_STT_GATE opt-in gate (FOCUS.md "STT
# gate", 2026-07-20) and its voice_control_keystroke() single-word mapping.
# Can't source the real script (it does unconditional mixer/tmux-wait side
# effects at the top, same reason test_stt_feed_secretary_flag.sh doesn't
# either) -- exercises the real addressed_to_console(),
# is_whisper_noise_hallucination(), and voice_control_keystroke() bash
# functions by extracting them verbatim from the script, and confirms the
# default-off guard line and gate call site are still present, so a refactor
# that silently drops the opt-in default or the gate check gets caught here.
set -uo pipefail
fail=0
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)"

check() {
  local desc="$1" expected="$2" got="$3"
  if [ "$got" = "$expected" ]; then
    echo "ok - $desc"
  else
    echo "FAIL - $desc: expected [$expected], got [$got]"
    fail=1
  fi
}

use_gate() {
  local USE_GATE="${1:-0}"
  if [ "$USE_GATE" != "0" ]; then
    echo "gated"
  else
    echo "raw"
  fi
}

check "unset CRT_STT_GATE defaults to raw (ungated) path" "raw" "$(use_gate)"
check "CRT_STT_GATE=0 explicit stays ungated" "raw" "$(use_gate 0)"
check "CRT_STT_GATE=1 enables the gate" "gated" "$(use_gate 1)"

# Extract addressed_to_console() verbatim from stt-feed.sh and exercise it
# for real, against the real bin/crt-stt-solo.py + bin/stt-fixups.json --
# not a re-derived copy, so this actually catches drift in the shell side.
eval "$(sed -n '/^addressed_to_console() {/,/^}/p' "$BIN_DIR/stt-feed.sh")"

if addressed_to_console "claude what time is it"; then
  echo "ok - wake word 'claude' is addressed to console"
else
  echo "FAIL - wake word 'claude' should be addressed to console"; fail=1
fi

if addressed_to_console "slide over here"; then
  echo "ok - known mishear 'slide' is addressed to console"
else
  echo "FAIL - known mishear 'slide' should be addressed to console"; fail=1
fi

if addressed_to_console "just some room chatter"; then
  echo "FAIL - room chatter should NOT be addressed to console"; fail=1
else
  echo "ok - room chatter without a wake word is not addressed to console"
fi

if grep -q 'USE_GATE="\${CRT_STT_GATE:-0}"' "$BIN_DIR/stt-feed.sh"; then
  echo "ok - stt-feed.sh still defaults CRT_STT_GATE to 0"
else
  echo "FAIL - stt-feed.sh's CRT_STT_GATE default guard is missing/changed"
  fail=1
fi

if grep -q 'USE_GATE.*!= "0".*&&.*! addressed_to_console' "$BIN_DIR/stt-feed.sh"; then
  echo "ok - gate check still guards the escalation path"
else
  echo "FAIL - stt-feed.sh's gate check site is missing/changed"
  fail=1
fi

# is_whisper_noise_hallucination() -- the canonical-noise-token drop list
# (AC/room noise whisper confidently mishears as bracketed sound tags or
# filler words), extracted verbatim same as addressed_to_console() above.
eval "$(sed -n '/^is_whisper_noise_hallucination() {/,/^}/p' "$BIN_DIR/stt-feed.sh")"

drops() {
  local text="$1"
  if is_whisper_noise_hallucination "$text"; then echo "dropped"; else echo "kept"; fi
}

check "a bare 'thank you' is dropped" "dropped" "$(drops "thank you")"
check "the full 'thank you for watching' hallucination is dropped" "dropped" "$(drops "Thank you for watching!")"
check "a bracketed sound tag normalizes and is dropped" "dropped" "$(drops "[Music playing]")"
check "empty text is dropped" "dropped" "$(drops "")"
check "a single letter is dropped by the length guard" "dropped" "$(drops "a")"
check "real speech addressed to the console is kept" "kept" "$(drops "claude what time is it")"
check "a short but real two-letter word is kept" "kept" "$(drops "ok")"

# voice_control_keystroke() -- single-word "yes"/"no"/"up"/"down"/"clear" ->
# tmux keystroke mapping, extracted verbatim same as the two functions above.
# This one used to read a bare $key that nothing in its scope set (a `local
# key` inside is_whisper_noise_hallucination, out of scope by the time this
# code ran) -- harmless under normal bash, but fatal under stt-feed.sh's own
# `set -u`: the first single-word utterance ("yes", "no", ...) threw "unbound
# variable" and killed the whole capture loop. Run under `set -u` here too,
# not just checked for the right match, so a regression back to a free
# variable fails this test the same way it used to fail the live script.
eval "$(sed -n '/^voice_control_keystroke() {/,/^}/p' "$BIN_DIR/stt-feed.sh")"

keystroke_for() {
  set -u
  voice_control_keystroke "$1" 2>/dev/null || echo "(no match)"
}

check "'yes' maps to Enter" "Enter" "$(keystroke_for "yes")"
check "'Yes!' (mixed case, punctuation) still maps to Enter" "Enter" "$(keystroke_for "Yes!")"
check "'no' maps to Escape" "Escape" "$(keystroke_for "no")"
check "'up' maps to Up" "Up" "$(keystroke_for "up")"
check "'down' maps to Down" "Down" "$(keystroke_for "down")"
check "'clear' maps to C-u" "C-u" "$(keystroke_for "clear")"
check "an unrecognized single word matches nothing" "(no match)" "$(keystroke_for "banana")"

if (set -u; voice_control_keystroke "yes" >/dev/null); then
  echo "ok - voice_control_keystroke runs clean under set -u (was: unbound variable)"
else
  echo "FAIL - voice_control_keystroke still errors under set -u"
  fail=1
fi

if grep -q 'voice_control_keystroke "\$text"' "$BIN_DIR/stt-feed.sh"; then
  echo "ok - stt-feed.sh's main loop calls voice_control_keystroke with \$text"
else
  echo "FAIL - stt-feed.sh's main loop no longer calls voice_control_keystroke"
  fail=1
fi

# Capture-pipe SIGPIPE handling (found 2026-07-20, crt#48): arecord piped into
# sox died of SIGPIPE once sox's VAD closed stdin, and pipefail failed the
# whole pipeline even though sox had already written a valid file --
# silently dropped utterances until this was caught. Extracts the real
# capture/sox_rc construct verbatim, same technique as the functions above,
# and runs it under a stubbed arecord/sox pair.
CAPTURE_FAKE_BIN="$(mktemp -d)"
CAPTURE_WORK="$(mktemp -d)"
trap 'rm -rf "$CAPTURE_FAKE_BIN" "$CAPTURE_WORK"' EXIT

cat > "$CAPTURE_FAKE_BIN/arecord" <<'EOF'
#!/usr/bin/env bash
# Bounded, not `while true`: SIGPIPE delivery on a closed pipe is prompt on
# a bare Linux box but was observed NOT to be prompt on a GitHub-hosted
# runner (crt#48, PR #300 hung ~7min waiting on this loop, orphaned bash
# left running past job cancellation). 20000 iterations is 20MB, far more
# than sox's 1000-byte read needs, so the real SIGPIPE-death path is still
# exercised wherever it fires promptly -- but the loop now also ends on its
# own if it never does, instead of hanging the harness (and CI) forever.
i=0
while [ "$i" -lt 20000 ]; do printf '%01000d' 0; i=$((i + 1)); done
EOF
chmod +x "$CAPTURE_FAKE_BIN/arecord"

cat > "$CAPTURE_FAKE_BIN/sox" <<'EOF'
#!/usr/bin/env bash
out=""
prev=""
for a in "$@"; do
  if [ "$prev" = "-" ]; then out="$a"; fi
  prev="$a"
done
read -r -N 1000 _ || true
echo fake-wav-data > "$out"
exit 0
EOF
chmod +x "$CAPTURE_FAKE_BIN/sox"

capture_snippet="$(sed -n '/^  # Capture with `arecord`/,/^    && sox_rc=\${PIPESTATUS\[1\]} || sox_rc=\${PIPESTATUS\[1\]}/p' "$BIN_DIR/stt-feed.sh")"

if [ -z "$capture_snippet" ]; then
  echo "FAIL - could not extract the capture/sox_rc construct from stt-feed.sh (markers may have drifted)"
  fail=1
else
  cat > "$CAPTURE_WORK/harness.sh" <<EOF
set -euo pipefail
AUDIODEV=irrelevant
VAD_THRESHOLD=3%
wav="$CAPTURE_WORK/utt.wav"
$capture_snippet
echo "REACHED_AFTER sox_rc=\$sox_rc"
EOF

  capture_out="$(PATH="$CAPTURE_FAKE_BIN:$PATH" timeout 10 bash "$CAPTURE_WORK/harness.sh" 2>"$CAPTURE_WORK/err")"
  capture_rc=$?

  if [ "$capture_rc" -eq 0 ] && printf '%s\n' "$capture_out" | grep -q '^REACHED_AFTER'; then
    echo "ok - set -e does not abort on arecord's SIGPIPE death"
  elif [ "$capture_rc" -eq 124 ]; then
    echo "FAIL - harness timed out after 10s (fake arecord never terminated -- see its own bounded-loop comment)"
    fail=1
  else
    echo "FAIL - harness aborted before sox_rc was even read (rc=$capture_rc)"
    sed 's/^/       /' "$CAPTURE_WORK/err"
    fail=1
  fi

  check "sox_rc reflects sox's own exit (0), not arecord's SIGPIPE death" \
    "0" "$(printf '%s\n' "$capture_out" | sed -n 's/^REACHED_AFTER sox_rc=//p')"

  if [ -s "$CAPTURE_WORK/utt.wav" ]; then
    echo "ok - sox's output file survives even though arecord died mid-write"
  else
    echo "FAIL - no output file written; sox's success didn't produce a usable file"
    fail=1
  fi

  # Regression case for the bug the SIGPIPE-hang chase above turned up: a
  # fake arecord that traps SIGPIPE and exits 0 on its own once its bounded
  # loop ends, so the pipeline succeeds OUTRIGHT instead of failing. The old
  # `if pipeline; then :; fi` form ran `:` as a simple command in that
  # branch, which clobbers PIPESTATUS down to one element -- crashing
  # `sox_rc=${PIPESTATUS[1]}` as an unbound variable under `set -u`. That's
  # exactly what PR #300 hit live in CI (a runner where SIGPIPE wasn't
  # delivered promptly), not a timing fluke of the test harness.
  cat > "$CAPTURE_FAKE_BIN/arecord" <<'EOF'
#!/usr/bin/env bash
trap '' PIPE
i=0
while [ "$i" -lt 20000 ]; do printf '%01000d' 0; i=$((i + 1)); done
EOF
  chmod +x "$CAPTURE_FAKE_BIN/arecord"

  clean_out="$(PATH="$CAPTURE_FAKE_BIN:$PATH" timeout 10 bash "$CAPTURE_WORK/harness.sh" 2>"$CAPTURE_WORK/err2")"
  clean_rc=$?

  if [ "$clean_rc" -eq 0 ] && printf '%s\n' "$clean_out" | grep -q '^REACHED_AFTER'; then
    echo "ok - sox_rc is still readable when the pipeline succeeds outright (arecord exits 0, not SIGPIPE)"
  else
    echo "FAIL - PIPESTATUS[1] unbound (or harness aborted) when arecord exits cleanly (rc=$clean_rc)"
    sed 's/^/       /' "$CAPTURE_WORK/err2"
    fail=1
  fi

  check "sox_rc is 0 when both arecord and sox succeed outright" \
    "0" "$(printf '%s\n' "$clean_out" | sed -n 's/^REACHED_AFTER sox_rc=//p')"
fi

exit "$fail"
