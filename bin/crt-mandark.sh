#!/usr/bin/env bash
# Turn the mandark <-> potato remote-Claude bridge ON or OFF from potato's
# side, and check whether it's actually reachable right now.
#
# WHY THIS EXISTS: the console can run its Claude Code brain in one of a
#   [rest: vault:crt/header-archaeology-20260817.md]
set -euo pipefail

CONF="${CRT_MANDARK_CONF:-$HOME/.crt/mandark.conf}"
PORT="${CRT_MANDARK_PORT:-8993}"

write_conf() {
  # $1 = port value to persist (8993 = on, 0 = off)
  mkdir -p "$(dirname "$CONF")"
  cat > "$CONF" <<EOF
# Written by crt-mandark.sh -- do not hand-edit; run 'crt-mandark.sh on|off'.
# Sourced by bin/crt-console.sh at boot. CRT_CLAUDE_REMOTE_PORT is read by
# bin/crt-secretary.py: a real port routes escalations to mandark's remote
# Claude bridge; 0 (or unset) keeps Claude local. See POTATO.md.
CRT_CLAUDE_REMOTE_PORT=$1
export CRT_CLAUDE_REMOTE_PORT
EOF
}

# Probe the bridge the exact way crt-secretary.py does: open the local
# (reverse-tunneled) socket, send CAPTURE, expect a non-empty pane back.
# Returns 0 if the bridge answered, 1 otherwise. Never blocks longer than
# the timeout. Uses python3 (always present here) so we match the real
#   [rest: vault:crt/header-archaeology-20260817.md]
probe_bridge() {
  python3 - "$1" <<'PY'
import socket, sys
port = int(sys.argv[1])
try:
    with socket.create_connection(("127.0.0.1", port), timeout=3) as s:
        s.sendall(b"CAPTURE\n")
        s.shutdown(socket.SHUT_WR)
        data = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
    sys.exit(0 if data.strip() else 1)
except OSError:
    sys.exit(1)
PY
}

current_port() {
  # Echo the configured port, or "(default 8993)" if no conf exists yet.
  if [ -f "$CONF" ]; then
    # shellcheck disable=SC1090
    ( . "$CONF"; echo "${CRT_CLAUDE_REMOTE_PORT:-0}" )
  else
    echo "$PORT"
  fi
}

cmd="${1:-status}"
case "$cmd" in
  on)
    write_conf "$PORT"
    echo "mandark bridge: ON (CRT_CLAUDE_REMOTE_PORT=$PORT)"
    echo "restart the stt window (or reboot) to pick it up: bin/crt-console.sh"
    if probe_bridge "$PORT"; then
      echo "reachable now: yes"
    else
      echo "reachable now: NO -- start the bridge+tunnel on mandark first"
      echo "  (systemctl --user status crt-remote-claude-bridge crt-potato-tunnel)"
    fi
    ;;
  off)
    write_conf 0
    echo "mandark bridge: OFF -- Claude stays local/onsite (or none)."
    echo "restart the stt window (or reboot) to pick it up: bin/crt-console.sh"
    ;;
  status|"")
    p="$(current_port)"
    if [ "$p" = "0" ]; then
      echo "config: OFF (local/onsite brain)"
      # Nothing is configured, so there is no port the console is using.
      # Probing the default is still the useful thing to report -- it
      # answers "is the bridge up, if I turned this back on" -- but the
      # line has to say that's what it did.
      probe_port="$PORT"
      probe_note=" (default; config is OFF, the console is not using it)"
    else
      echo "config: ON  (port $p)"
      probe_port="$p"
      probe_note=""
    fi
    [ -f "$CONF" ] || echo "  (no $CONF yet -- using default, treated as ON)"
    if probe_bridge "$probe_port"; then
      echo "bridge reachable now: yes -- port $probe_port$probe_note"
    else
      echo "bridge reachable now: no -- port $probe_port$probe_note"
    fi
    ;;
  *)
    echo "usage: crt-mandark.sh {on|off|status}" >&2
    exit 2
    ;;
esac
