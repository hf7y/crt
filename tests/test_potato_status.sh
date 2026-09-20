#!/usr/bin/env bash
# Offline test for bin/crt-potato-status.sh (crt#325): the local snapshot
# half -- selfcheck verdict, log tails, Tailscale state, all written to one
# JSON file. Uses the same door-stub pattern as test_console_selfcheck.sh so
# the underlying crt-console-selfcheck.sh call never reaches a real network.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$DIR/../bin/crt-potato-status.sh"
pass=0; fail=0
ok()  { pass=$((pass+1)); printf '  ok - %s\n' "$1"; }
bad() { fail=$((fail+1)); printf '  FAIL - %s\n' "$1"; [ $# -gt 1 ] && printf '        %s\n' "$2"; }

D="$(mktemp -d)"
trap 'rm -rf "$D"; [ -n "${DPID:-}" ] && kill "$DPID" 2>/dev/null; true' EXIT

cat > "$D/door_stub.py" <<'PY'
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.send_response(200)
        self.send_header("mcp-session-id", "stub")
        self.end_headers(); self.wfile.write(b'{"jsonrpc":"2.0","id":1,"result":{}}')
HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
PY
python3 "$D/door_stub.py" 8801 & DPID=$!
for _ in $(seq 40); do
  curl -sf -o /dev/null -m 1 -X POST "http://127.0.0.1:8801/" -d '{}' 2>/dev/null && break
  sleep 0.1
done

export CRT_SELFCHECK_DOOR="http://127.0.0.1:8801/mcp"
export CRT_SELFCHECK_STATE="$D/selfcheck.state"
# crt#363 added a third selfcheck state file (the "brain leg" log) that this
# stub never pinned -- it fell through to the real ~/.crt/selfcheck-legs.log,
# caught by run_tests.sh's own live-state guard.
export CRT_SELFCHECK_LEGLOG="$D/selfcheck-legs.log"

OUT="$D/potato-status.json"
STT_LOG="$D/stt.log"; GATE_LOG="$D/gate.log"; SUP_LOG="$D/stt-supervisor.log"
printf '10:00:00  hello there\n10:00:05  potato scan the book\n' > "$STT_LOG"
printf '10:00:01  [stt-gate] dropped (no wake word): ambient noise\n' > "$GATE_LOG"
printf '10:00:00  supervisor start\n' > "$SUP_LOG"

FAKEBIN="$D/fakebin"; mkdir -p "$FAKEBIN"
cat > "$FAKEBIN/tailscale" <<'EOF'
#!/usr/bin/env bash
[ "$1" = status ] && echo '{"BackendState":"Running"}'
EOF
chmod +x "$FAKEBIN/tailscale"

run_status() {
  CRT_POTATO_STATUS_OUT="$OUT" CRT_STT_LOG="$STT_LOG" CRT_STT_GATE_LOG="$GATE_LOG" \
    CRT_STT_SUP_LOG="$SUP_LOG" CRT_POTATO_STATUS_TAILSCALE="$FAKEBIN/tailscale" \
    bash "$SCRIPT" "$@"
}

run_status >/dev/null 2>&1
if [ -s "$OUT" ] && python3 -c "import json; json.load(open('$OUT'))" 2>/dev/null; then
  ok "writes valid JSON"
else
  bad "no valid JSON written" "$(cat "$OUT" 2>/dev/null)"
fi

state="$(python3 -c "import json; print(json.load(open('$OUT'))['selfcheck']['state'])")"
[ "$state" = RED ] || [ "$state" = GREEN ] \
  && ok "selfcheck state is a real verdict ($state)" \
  || bad "selfcheck state is neither RED nor GREEN" "$state"

ts_state="$(python3 -c "import json; print(json.load(open('$OUT'))['tailscale_backend_state'])")"
[ "$ts_state" = Running ] && ok "tailscale backend state comes through" \
  || bad "tailscale backend state missing/wrong" "$ts_state"

stt_lines="$(python3 -c "import json; print(len(json.load(open('$OUT'))['logs']['stt.log']))")"
[ "$stt_lines" = 2 ] && ok "stt.log tail carries both lines" \
  || bad "stt.log tail has $stt_lines lines, expected 2"

gate_text="$(python3 -c "import json; print(json.load(open('$OUT'))['logs']['gate.log'][0])")"
printf '%s' "$gate_text" | grep -q "dropped" && ok "gate.log tail line comes through" \
  || bad "gate.log tail missing content" "$gate_text"

generated_at="$(python3 -c "import json; print(json.load(open('$OUT'))['generated_at'])")"
printf '%s' "$generated_at" | grep -qE '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$' \
  && ok "generated_at is a real UTC timestamp" || bad "generated_at malformed" "$generated_at"

# A missing log file (never written yet) is an empty list, not a crash.
rm -f "$STT_LOG"
run_status >/dev/null 2>&1
rc=$?
missing_lines="$(python3 -c "import json; print(len(json.load(open('$OUT'))['logs']['stt.log']))" 2>/dev/null || echo BAD)"
[ "$rc" = 0 ] && [ "$missing_lines" = 0 ] \
  && ok "a missing log file is an empty list, not a crash" \
  || bad "missing log file was not handled cleanly (rc=$rc, lines=$missing_lines)"

# The RED/GREEN-transition alert to Zach (crt#323's ask) is
# crt-console-selfcheck.sh's own behavior, run here unmodified (this script
# calls it plain, no --check) -- already covered end-to-end by
# tests/test_console_selfcheck.sh; not re-asserted here.

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" = 0 ]
