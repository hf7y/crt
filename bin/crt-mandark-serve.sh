#!/usr/bin/env bash
# MANDARK-SIDE on/off/status for the whole remote-brain path that lets
# potato run with no Claude of its own. Run this ON MANDARK (needs sudo
# only for the systemd-managed pieces -- that's why it's a script for you,
# not something the console runs itself). Three components:
#
#   whisper  -- bin/mandark-whisper-server.py, LAN STT on :8991
#   bridge   -- bin/crt-remote-claude-bridge.py, 127.0.0.1:8993 -> tmux
#               session `potato-claude` (the actual Claude brain)
#   tunnel   -- the reverse tunnel you're calling the "reverse proxy":
#               `ssh -N -R 8993:localhost:8993 potato`, so potato reaches
#               the bridge over ITS OWN localhost (mandark dials OUT; potato
#               never gets a path into mandark -- see
#               bin/crt-remote-claude-bridge.py's threat-model header).
#
# Each component is handled by whichever mechanism is present: if a systemd
# unit is installed (via setup-mandark-*-persistence.sh) it's used
# (`sudo systemctl`); otherwise an ad-hoc background process is started
# (survives this shell via nohup+disown, but NOT a reboot -- install the
# units for that). Idempotent: a component already up is left alone.
#
# RELATED KNOBS (don't confuse them):
#   bin/crt-mandark.sh              -- POTATO side: routes the console's
#                                      brain to mandark (on) or local (off).
#   setup-mandark-whisper-persistence.sh
#   setup-mandark-remote-claude-persistence.sh
#                                   -- one-time systemd installers (reboot
#                                      persistence). This script is the
#                                      day-to-day on/off.
#
# Usage: crt-mandark-serve.sh {on|off|status}
set -uo pipefail

BRIDGE_PORT="${CRT_REMOTE_BRIDGE_PORT:-8993}"
WHISPER_PORT="${CRT_WHISPER_PORT:-8991}"
POTATO_HOST="${CRT_POTATO_HOST:-potato}"
BRIDGE_SESSION="${CRT_REMOTE_BRIDGE_SESSION:-potato-claude}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WHISPER_PY="${CRT_WHISPER_PY:-$HOME/.venvs/crt-whisper-server/bin/python}"
LOGDIR="$HOME/.crt/mandark-serve"
mkdir -p "$LOGDIR"

# component -> systemd unit name
unit_of() { case "$1" in
  whisper) echo "crt-whisper-server.service" ;;
  bridge)  echo "crt-remote-claude-bridge.service" ;;
  tunnel)  echo "crt-potato-tunnel.service" ;;
esac; }

# component -> pgrep pattern for the ad-hoc process
pat_of() { case "$1" in
  whisper) echo "mandark-whisper-server.py" ;;
  bridge)  echo "crt-remote-claude-bridge.py" ;;
  tunnel)  echo "ssh -N -R ${BRIDGE_PORT}:localhost:${BRIDGE_PORT}" ;;
esac; }

unit_installed() { systemctl list-unit-files "$1" --no-legend 2>/dev/null | grep -q .; }
unit_active()    { systemctl is-active --quiet "$1" 2>/dev/null; }
adhoc_pid()      { pgrep -f "$(pat_of "$1")" | head -1; }

# component -> the ad-hoc launch command (as a string eval'd under nohup)
adhoc_cmd() { case "$1" in
  whisper) echo "'$WHISPER_PY' '$REPO/bin/mandark-whisper-server.py'" ;;
  bridge)  echo "python3 '$REPO/bin/crt-remote-claude-bridge.py' --port $BRIDGE_PORT --session '$BRIDGE_SESSION'" ;;
  tunnel)  echo "ssh -N -R ${BRIDGE_PORT}:localhost:${BRIDGE_PORT} -o ServerAliveInterval=15 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes '$POTATO_HOST'" ;;
esac; }

is_up() {
  local c="$1" u; u="$(unit_of "$c")"
  if unit_installed "$u"; then unit_active "$u"; else [ -n "$(adhoc_pid "$c")" ]; fi
}

start_one() {
  local c="$1" u; u="$(unit_of "$c")"
  if is_up "$c"; then echo "  $c: already up, leaving it"; return 0; fi
  if unit_installed "$u"; then
    echo "  $c: starting via systemd (sudo)"; sudo systemctl start "$u"
  else
    echo "  $c: starting ad-hoc (no reboot persistence -- install the unit for that)"
    # exec so bash is replaced by the target -- no lingering wrapper process
    # for stop_one to have to find and kill separately.
    nohup bash -c "exec $(adhoc_cmd "$c")" >"$LOGDIR/$c.log" 2>&1 & disown
  fi
}

stop_one() {
  local c="$1" u pid; u="$(unit_of "$c")"
  if unit_installed "$u" && unit_active "$u"; then
    echo "  $c: stopping via systemd (sudo)"; sudo systemctl stop "$u"; return 0
  fi
  local pids; pids="$(pgrep -f "$(pat_of "$c")")"
  if [ -n "$pids" ]; then
    echo "  $c: killing ad-hoc pid(s) $(echo "$pids" | tr '\n' ' ')"
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
  else echo "  $c: already down"; fi
}

probe_bridge() {
  python3 - "$BRIDGE_PORT" <<'PY'
import socket, sys
try:
    with socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=3) as s:
        s.sendall(b"CAPTURE\n"); s.shutdown(socket.SHUT_WR)
        print("responds" if s.recv(4096).strip() else "silent")
except OSError: print("unreachable")
PY
}

case "${1:-status}" in
  on)
    echo "bringing the mandark remote-brain path UP:"
    # order matters: bridge must bind before the tunnel forwards to it.
    if ! tmux has-session -t "$BRIDGE_SESSION" 2>/dev/null; then
      echo "  WARNING: tmux session '$BRIDGE_SESSION' is missing -- the bridge"
      echo "           forwards to it, so escalations will capture an empty pane."
      echo "           Start the brain there first (claude in the sshfs mount)."
    fi
    start_one whisper; start_one bridge; sleep 1; start_one tunnel
    echo "done. 'crt-mandark-serve.sh status' to verify."
    ;;
  off)
    echo "taking the mandark remote-brain path DOWN:"
    stop_one tunnel; stop_one bridge; stop_one whisper
    echo "done."
    ;;
  status|"")
    for c in whisper bridge tunnel; do
      u="$(unit_of "$c")"
      if unit_installed "$u"; then mech="systemd ($(systemctl is-active "$u" 2>/dev/null))"
      elif [ -n "$(adhoc_pid "$c")" ]; then mech="ad-hoc pid $(adhoc_pid "$c")"
      else mech="DOWN"; fi
      printf "  %-8s %s\n" "$c:" "$mech"
    done
    echo "  ports:   $(ss -tlnp 2>/dev/null | grep -oE "(127.0.0.1|0.0.0.0):(${WHISPER_PORT}|${BRIDGE_PORT})" | tr '\n' ' ')"
    echo "  session: $(tmux has-session -t "$BRIDGE_SESSION" 2>/dev/null && echo "$BRIDGE_SESSION present" || echo "$BRIDGE_SESSION MISSING")"
    echo "  bridge:  $(probe_bridge)"
    ;;
  *) echo "usage: crt-mandark-serve.sh {on|off|status}" >&2; exit 2 ;;
esac
