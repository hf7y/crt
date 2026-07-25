#!/usr/bin/env bash
# Offline test for bin/crt-mandark.sh: on/off/status write the right
# CRT_CLAUDE_REMOTE_PORT into a temp conf. No live bridge exists in the
# test env, so we only assert on the persisted config, not reachability.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$DIR/../bin/crt-mandark.sh"
fail=0

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
CONF="$TMP/mandark.conf"

# on -> port 8993 persisted, sources cleanly as a shell fragment
CRT_MANDARK_CONF="$CONF" bash "$SCRIPT" on >/dev/null 2>&1 || true
if grep -q "CRT_CLAUDE_REMOTE_PORT=8993" "$CONF"; then
  echo "PASS: on writes port 8993"
else
  echo "FAIL: on did not write port 8993"; cat "$CONF"; fail=1
fi
if ( . "$CONF" ) 2>/dev/null; then
  echo "PASS: conf sources cleanly"
else
  echo "FAIL: conf is not a valid shell fragment"; fail=1
fi

# off -> port 0 persisted
CRT_MANDARK_CONF="$CONF" bash "$SCRIPT" off >/dev/null 2>&1 || true
if grep -q "CRT_CLAUDE_REMOTE_PORT=0" "$CONF"; then
  echo "PASS: off writes port 0"
else
  echo "FAIL: off did not write port 0"; cat "$CONF"; fail=1
fi

# secretary's own parse: 0 -> None (local); a real port -> that port.
port_from_conf() {
  ( . "$CONF"; python3 -c 'import os;print(int(os.environ.get("CRT_CLAUDE_REMOTE_PORT","0")) or 0)' )
}
if [ "$(port_from_conf)" = "0" ]; then
  echo "PASS: off parses to local (0) the way crt-secretary.py reads it"
else
  echo "FAIL: off did not parse to 0"; fail=1
fi

# status must not error out (probe just returns 'no' with no bridge).
if CRT_MANDARK_CONF="$CONF" bash "$SCRIPT" status >/dev/null 2>&1; then
  echo "PASS: status exits 0"
else
  echo "FAIL: status errored"; fail=1
fi

# status must probe the CONFIGURED port, not the default (2026-07-25).
# Before this, probe_bridge() always read $PORT while current_port() read
# the conf, so status could report "config: ON (port 9001)" and then answer
# about 8993. Asserted by standing a real listener on one port only: the
# status line must name the port it actually probed, and reachability must
# follow the configured port, not the default.
# Behavioural, not just a message check: a real listener stands on 19001
# and NOTHING listens on the default 8993, so "reachable: yes" is only
# possible if status probed the port it was configured with.
python3 -c '
import socketserver, sys
class H(socketserver.StreamRequestHandler):
    def handle(self):
        self.rfile.readline()
        self.wfile.write(b"pane content")
class S(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
S(("127.0.0.1", 19001), H).serve_forever()
' &
LISTENER_PID=$!
sleep 0.5

CRT_MANDARK_PORT=19001 CRT_MANDARK_CONF="$CONF" bash "$SCRIPT" on >/dev/null 2>&1 || true
out="$(CRT_MANDARK_CONF="$CONF" bash "$SCRIPT" status 2>&1)"
kill "$LISTENER_PID" 2>/dev/null
wait "$LISTENER_PID" 2>/dev/null

if grep -q "reachable now: yes" <<<"$out"; then
  echo "PASS: status probed the configured port (19001), not the default"
else
  echo "FAIL: status did not reach the listener on the configured port"
  echo "$out"; fail=1
fi
# Specifically the reachability line -- "port 19001" also appears in the
# config line above it, so grepping the whole output would pass either way.
if grep -qE "reachable now: (yes|no) -- port 19001" <<<"$out"; then
  echo "PASS: the reachability line names the port it probed"
else
  echo "FAIL: reachability line did not name the probed port"; echo "$out"; fail=1
fi

# ...and with the config OFF, the line has to say the port it probed is the
# default rather than one the console is using.
CRT_MANDARK_CONF="$CONF" bash "$SCRIPT" off >/dev/null 2>&1 || true
out="$(CRT_MANDARK_CONF="$CONF" bash "$SCRIPT" status 2>&1)"
if grep -q "config is OFF, the console is not using it" <<<"$out"; then
  echo "PASS: OFF status says the probed port is not the one in use"
else
  echo "FAIL: OFF status did not qualify the probed port"; echo "$out"; fail=1
fi

# bad arg -> usage + non-zero
if CRT_MANDARK_CONF="$CONF" bash "$SCRIPT" bogus >/dev/null 2>&1; then
  echo "FAIL: bad arg should be non-zero"; fail=1
else
  echo "PASS: bad arg rejected"
fi

exit "$fail"
