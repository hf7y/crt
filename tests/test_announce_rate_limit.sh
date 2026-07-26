#!/usr/bin/env bash
# crt-announce.sh -- the TV-facing voice and, more importantly, the writer
# of the rate-limit window that crt-idle-teaser.sh's chime() shares with it
# (IDLE-BAIT.md's single-rate-limit rule: a chime and an announcement must
# never stack).
#
# It had no test at all until 2026-07-25, which is how it kept a defect
# nobody would call subtle: it stamped the shared window, then `exec`d into
# crt-tts.py and could not know whether anything was said. A TV device that
# is missing, busy or misnamed therefore bought fifteen minutes of silence
# on BOTH channels -- the announcement nobody heard, and the earpiece
# chimes that rate-limit against the same file. A broken speaker silencing
# a working one is a fault spreading, not a rate limit.
#
# crt-tts.py is faked via a `python3` first on PATH: what is under test is
# the lock protocol, and the real one needs piper/espeak plus a sound card.
set -uo pipefail
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)"
fail=0

check() {
  local desc="$1" expected="$2" got="$3"
  if [ "$got" = "$expected" ]; then
    echo "ok - $desc"
  else
    echo "FAIL - $desc: expected [$expected], got [$got]"
    fail=1
  fi
}

TMPDIR="$(mktemp -d)"
FAKE_BIN="$(mktemp -d)"
trap 'rm -rf "$TMPDIR" "$FAKE_BIN"' EXIT

LOCK="$TMPDIR/announce.lastrun"
SPOKE="$TMPDIR/spoke.log"

# Records every invocation, exits with whatever FAKE_TTS_STATUS says. Real
# python3 is still reachable by absolute path if anything else needs it.
cat > "$FAKE_BIN/python3" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE_TTS_LOG"
exit "${FAKE_TTS_STATUS:-0}"
EOF
chmod +x "$FAKE_BIN/python3"

announce() {  # $1 = tts exit status, rest = message
  local status="$1"; shift
  PATH="$FAKE_BIN:$PATH" FAKE_TTS_LOG="$SPOKE" FAKE_TTS_STATUS="$status" \
    CRT_ANNOUNCE_LOCK="$LOCK" CRT_ANNOUNCE_MIN_GAP=900 \
    CRT_THOUGHT_LOG="$TMPDIR/thoughts.log" \
    bash "$BIN_DIR/crt-announce.sh" "$@" 2>>"$TMPDIR/stderr.log"
}

# --- an empty message is a usage error, not a silent no-op ----------------
PATH="$FAKE_BIN:$PATH" FAKE_TTS_LOG="$SPOKE" CRT_ANNOUNCE_LOCK="$LOCK" \
  bash "$BIN_DIR/crt-announce.sh" >/dev/null 2>&1
check "no message -> usage exit 2" "2" "$?"
check "no message -> no lock written" "absent" \
  "$([ -e "$LOCK" ] && echo present || echo absent)"

# --- the happy path speaks and claims the window -------------------------
announce 0 "the batch job needs your input"
check "a successful announcement exits 0" "0" "$?"
check "it actually called crt-tts.py once" "1" "$(wc -l < "$SPOKE")"
case "$(cat "$SPOKE")" in
  *crt-tts.py*--device*"the batch job needs your input"*)
    echo "ok - the message and the tv device reached crt-tts.py" ;;
  *)
    echo "FAIL - crt-tts.py called with unexpected args: [$(cat "$SPOKE")]"
    fail=1 ;;
esac
stamp="$(cat "$LOCK")"
if printf '%s' "$stamp" | grep -qE '^[0-9]+$'; then
  echo "ok - a spoken announcement stamps the shared window"
else
  echo "FAIL - no epoch stamp after a successful announcement: [$stamp]"
  fail=1
fi

# --- ...and the window then holds, which is the whole point --------------
: > "$SPOKE"
announce 0 "a second one, straight away"
check "a second announcement inside the gap is refused (exit 1)" "1" "$?"
check "the refused announcement never reached crt-tts.py" "0" "$(wc -l < "$SPOKE")"
check "the refusal left the original stamp alone" "$stamp" "$(cat "$LOCK")"

# --- a FAILED announcement must give the window back ---------------------
# This is the regression the file exists for. Wind the stamp back past the
# gap so a new attempt is allowed, then have crt-tts.py fail.
old_stamp=$(( $(date +%s) - 1000 ))
echo "$old_stamp" > "$LOCK"
: > "$SPOKE"
announce 3 "nobody is going to hear this"
check "a failed announcement reports crt-tts.py's own exit status" "3" "$?"
check "it did try" "1" "$(wc -l < "$SPOKE")"
check "a failed announcement restores the previous stamp" "$old_stamp" "$(cat "$LOCK")"

# ...and having given the window back, the next attempt is allowed through
# rather than blocked by a silence that never happened.
: > "$SPOKE"
announce 0 "this one works"
check "the next announcement is not blocked by the failed one" "0" "$?"
check "the retry reached crt-tts.py" "1" "$(wc -l < "$SPOKE")"

# --- a failure with NO prior lock must not invent one --------------------
rm -f "$LOCK"
announce 1 "still nothing" >/dev/null 2>&1
check "a failure with no prior stamp leaves no stamp behind" "absent" \
  "$([ -e "$LOCK" ] && echo present || echo absent)"

# --- and it must say so, in both places ----------------------------------
if grep -q "NOT SPOKEN" "$TMPDIR/stderr.log" 2>/dev/null; then
  echo "ok - a failed announcement says so on stderr"
else
  echo "FAIL - a failed announcement was silent on stderr"
  fail=1
fi
if grep -q "tv stayed quiet" "$TMPDIR/thoughts.log" 2>/dev/null; then
  echo "ok - a failed announcement reaches window 1 too"
else
  echo "FAIL - nothing about the failed announcement reached the thought log"
  fail=1
fi

exit "$fail"
