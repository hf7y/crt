#!/usr/bin/env bash
# Re-run the potato<->Zach voice calibration loop mechanically, with as
# little AI in the loop as possible.
#
# WHY (Zach, 2026-07-29, going afk): "make it use mechanical script calls
#   [rest: vault:crt/header-archaeology-20260817.md]
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"

POTATO="${CRT_POTATO_HOST:-potato}"
POTATO_BIN="${CRT_POTATO_BIN:-/home/vkv/crt/bin}"
POTATO_CRT="${CRT_POTATO_STATE:-/home/vkv/.crt}"
PRIMER="${CRT_VOICE_PRIMER:-$REPO/voice-priming-prompt.md}"

# Asked, never retyped -- same reason crt-brain-session.sh asks: two
# spellings of the session name is a healthy-looking brain nobody is
# talking to.
SESSION="$("$HERE/crt-brain-shell.py" --print-session 2>/dev/null || true)"

pass=0; failn=0
ok()   { printf '  ok   %s\n' "$*"; pass=$((pass+1)); }
bad()  { printf '  FAIL %s\n' "$*" >&2; failn=$((failn+1)); }
head_() { printf '\n== %s ==\n' "$*"; }

ssh_potato() { timeout "${CRT_SSH_TIMEOUT:-25}" ssh "$POTATO" "$@"; }

# ---------------------------------------------------------------- checks
# Each check is a question with a witness, not a green tick. If a hop
# cannot be observed it is a FAIL, not a skip -- "we could not tell" and
# "it works" have been the same output too many times in this project.

check_brain() {
  head_ "1. brain session on this host"
  local out
  out="$("$HERE/crt-brain-session.sh" status 2>&1)"
  if [ $? -eq 0 ]; then ok "$out"; else bad "$out"; fi
}

check_ssh_path() {
  head_ "2. potato -> brain over ssh (the real forced-command path)"
  local out
  out="$(ssh_potato "echo CAPTURE | ssh ${CRT_BRAIN_SSH_HOST:-dexter}" 2>&1 | tail -3)"
  if [ -n "${out//[[:space:]]/}" ]; then
    ok "CAPTURE returned live pane text (last line: $(printf '%s' "$out" | tail -1 | cut -c1-48))"
  else
    bad "CAPTURE from potato returned nothing -- the brain is unreachable FROM POTATO, \
which is the only direction that matters. Check ~/.ssh/authorized_keys' forced command."
  fi
}

check_capture_env() {
  head_ "3. potato's live capture process is configured, not just its files"
  # The 2026-07-29 bug in one check: brain.conf said dexter, the RUNNING
  # process still said port 8993, and nothing compared them. Config on
  # disk is not config in force.
  local env
  env="$(ssh_potato 'pid=$(pgrep -f crt-stt-solo.py | head -1); [ -n "$pid" ] && tr "\0" "\n" < /proc/$pid/environ | grep "^CRT_"' 2>&1)"
  if [ -z "${env//[[:space:]]/}" ]; then
    bad "no crt-stt-solo.py running on $POTATO -- the console is deaf"
    return
  fi
  local want
  for want in CRT_WAKE_WORD=potato CRT_EARCON_DEVICE=tv CRT_CLAUDE_SSH_HOST=dexter; do
    if printf '%s\n' "$env" | grep -qx "$want"; then
      ok "live process has $want"
    else
      bad "live process is MISSING $want (has: $(printf '%s' "$env" | grep "${want%%=*}=" || echo '<nothing>')) \
-- it will look healthy and behave wrong"
    fi
  done
  if printf '%s\n' "$env" | grep -q "CRT_CLAUDE_REMOTE_PORT=8993"; then
    bad "live process still points at the RETIRED mandark bridge (port 8993)"
  fi
}

check_delivery() {
  head_ "4. recent deliveries actually landed"
  local last
  last="$(ssh_potato "tail -1 $POTATO_CRT/brain-unreachable.log 2>/dev/null" 2>&1)"
  case "$last" in
    *"NOT DELIVERED"*|*"UNOBSERVED"*)
      printf '  note last failure: %s\n' "$(printf '%s' "$last" | cut -c1-72)"
      ok "log readable (check the timestamp above -- stale is fine, recent is not)" ;;
    "") ok "no delivery failures ever logged" ;;
    *)  ok "last entry is not a failure" ;;
  esac
}

check_window_one() {
  head_ "5. window 1 (mono) is the thing showing replies"
  local procs
  procs="$(ssh_potato 'pgrep -af crt-monologue.py | head -2' 2>&1)"
  if printf '%s' "$procs" | grep -q crt-monologue; then
    ok "crt-monologue.py is running"
  else
    bad "crt-monologue.py is NOT running -- window 1 will stay dark whatever the brain says"
  fi
  local active
  active="$(ssh_potato 'tmux display-message -p "#{window_index}:#{window_name}"' 2>&1)"
  printf '  note tube is currently showing %s\n' "$active"
}

check_marker_filter() {
  head_ "6. the '>>' marker filter -- KNOWN BROKEN, see the crt issue backlog"
  # Deliberately a check and not a fix: the fix is a design decision
  # (where does the filter live now that the brain is on another host)
  # that Zach has not made yet. Failing loudly every run is the point.
  local recent
  recent="$(ssh_potato "tail -20 $POTATO_CRT/thoughts.log 2>/dev/null | grep -c 'PostToolUse\|Do you want to proceed'" 2>&1)"
  if [ "${recent:-0}" -gt 0 ] 2>/dev/null; then
    bad "window 1 is receiving raw tool output ($recent lines of it in the last 20). \
The brain marks its user-facing lines with a leading guillemet; nothing on potato \
filters for that anymore, because crt-claude-bridge.py still watches window 0's \
local pane and the brain moved to another host."
  else
    ok "no raw tool output in the last 20 thoughts.log lines"
  fi
}

check_margins() {
  head_ "7. margins / pretty-print config"
  if ssh_potato "test -f $POTATO_CRT/display.conf" 2>/dev/null; then
    ok "display.conf exists"
  else
    bad "$POTATO_CRT/display.conf does not exist -- every consumer \
(crt-monologue.py, crt-book-console.py, crt-screensaver.py) silently degrades to \
ZERO margin. Text runs to the tube edge. Create it with: crt-calibrate-display.py"
  fi
}

# ----------------------------------------------------------- prompt inject
# The "prompt injection" half of what Zach asked for: the brain's standing
# brief is a FILE, pushed into the session mechanically, not something a
# model reconstructs from conversation each time. Re-running a calibration
# pass should not require re-explaining the task.
inject_primer() {
  head_ "priming the brain"
  if [ ! -f "$PRIMER" ]; then
    bad "no priming prompt at $PRIMER"
    return 1
  fi
  if [ -z "$SESSION" ]; then
    bad "could not resolve the brain session name from crt-brain-shell.py"
    return 1
  fi
  # Send as ONE literal chunk then Enter, the same two-step
  # crt-secretary.py uses -- send-keys with embedded newlines would
  # submit the prompt line by line, and the first line alone is not the
  # brief.
  local text
  text="$(tr '\n' ' ' < "$PRIMER")"
  if ! tmux send-keys -t "$SESSION" -l "$text" 2>/dev/null; then
    bad "tmux send-keys failed -- is $SESSION up?"
    return 1
  fi
  tmux send-keys -t "$SESSION" Enter
  sleep 3
  local pane
  pane="$(tmux capture-pane -t "$SESSION" -p -S -20 2>/dev/null)"
  if printf '%s' "$pane" | grep -qi "calibration\|earcon\|margin"; then
    ok "primer accepted (brain pane references the brief)"
  else
    bad "primer sent but the pane does not reflect it -- check: tmux attach -t $SESSION"
  fi
}

# ------------------------------------------------------------------- verbs
case "${1:-check}" in
  check)
    check_brain; check_ssh_path; check_capture_env; check_delivery
    check_window_one; check_marker_filter; check_margins
    printf '\n== %d ok, %d FAILED ==\n' "$pass" "$failn"
    [ "$failn" -eq 0 ] || exit 1
    ;;

  stage)
    head_ "0. ensuring the brain is up (with permissions bypassed)"
    "$HERE/crt-brain-session.sh" ensure || { echo "crt-voice-calibration: brain would not start" >&2; exit 1; }
    inject_primer
    check_brain; check_ssh_path; check_capture_env; check_delivery
    check_window_one; check_marker_filter; check_margins
    printf '\n== staged: %d ok, %d FAILED ==\n' "$pass" "$failn"
    printf 'Next: talk to the handset, or script it:\n  %s say "potato, make the bait earcon more curious"\n' "$0"
    [ "$failn" -eq 0 ] || exit 1
    ;;

  say)
    shift
    [ "$#" -gt 0 ] || { echo "usage: $0 say TEXT" >&2; exit 2; }
    # Injected at the SECRETARY, not the brain: this is the same entry
    # point crt-stt-solo.py uses once whisper has a transcript, so it
    # exercises the wake gate, the escalation, the reply capture and the
    # window-1 render -- everything except the microphone. That is the
    # part worth re-running, and the part a person cannot repeat exactly.
    head_ "injecting utterance (bypassing the mic, not the pipeline)"
    printf '  > %s\n' "$*"
    # Source the console's config FIRST. crt-secretary.py is Python and
    # cannot read a shell conf itself -- it takes CRT_CLAUDE_SSH_HOST
    # from its environment, which crt-console.sh supplies at boot. An ssh
    # command shell has none of it, so an unsourced invocation here picks
    #   [rest: vault:crt/header-archaeology-20260817.md]
    CRT_SSH_TIMEOUT="${CRT_SAY_TIMEOUT:-180}" \
      ssh_potato "cd $POTATO_BIN && . ./crt-conf.sh && python3 ./crt-secretary.py $(printf '%q' "$*")"
    rc=$?
    printf '\n  secretary exited %d\n' "$rc"
    printf '  window 1 now:\n'
    ssh_potato 'tmux capture-pane -p -t claude:1' | grep . | sed 's/^/    /'
    exit "$rc"
    ;;

  watch)
    exec ssh "$POTATO" "tail -n0 -F $POTATO_CRT/gate.log $POTATO_CRT/brain-unreachable.log $POTATO_CRT/thoughts.log"
    ;;

  *)
    echo "usage: $0 [stage|check|say TEXT|watch]" >&2
    exit 2
    ;;
esac
