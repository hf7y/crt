#!/usr/bin/env bash
# What the mute month cost, asserted: a console that cannot transcribe says
# so once (crt#132).
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SELF="$DIR/../bin/crt-console-selfcheck.sh"
pass=0; fail=0
ok()  { pass=$((pass+1)); printf '  ok - %s\n' "$1"; }
bad() { fail=$((fail+1)); printf '  FAIL - %s\n' "$1"; [ $# -gt 1 ] && printf '        %s\n' "$2"; }

D="$(mktemp -d)"; trap 'rm -rf "$D"; [ -n "${WPID:-}" ] && kill "$WPID" 2>/dev/null; [ -n "${DPID:-}" ] && kill "$DPID" 2>/dev/null; true' EXIT

cat > "$D/stub.py" <<'PY'
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
MODE, LOG = sys.argv[2], sys.argv[3]
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if MODE == "door":
            body = json.loads(raw or b"{}")
            if body.get("method") == "tools/call":
                open(LOG, "a").write(json.dumps(body["params"]["arguments"]) + "\n")
            self.send_response(200)
            self.send_header("mcp-session-id", "stub")
            self.end_headers(); self.wfile.write(b'{"jsonrpc":"2.0","id":1,"result":{}}')
            return
        open(LOG, "a").write("posted\n")
        payload = ({"text": ""} if MODE == "good" else
                   {"oops": "Invalid request " + "x" * 300})
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers(); self.wfile.write(data)
HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
PY

serve() {  # serve <port> <mode> <log>
  python3 "$D/stub.py" "$1" "$2" "$3" & echo $!
  for _ in $(seq 40); do
    curl -sf -o /dev/null -m 1 -X POST "http://127.0.0.1:$1/" -d '{}' 2>/dev/null && break
    sleep 0.1
  done
}

printf 'crt-console-selfcheck -- what the mute month cost\n\n'

WPID="$(serve 8794 good "$D/whisper.log" | head -1)"
DPID="$(serve 8795 door "$D/door.log" | head -1)"
WHISPER="http://127.0.0.1:8794/inference"
export CRT_SELFCHECK_DOOR="http://127.0.0.1:8795/mcp" CRT_SELFCHECK_STATE="$D/state"

out="$("$SELF" --check --server "$WHISPER" 2>&1)"
case "$out" in GREEN*) ok "a server that answers with a transcription is GREEN" ;;
  *) bad "GREEN not reported" "$out" ;; esac
[ ! -s "$D/door.log" ] && ok "--check says nothing to Zach" || bad "--check sent a message"

out="$("$SELF" --check --server "http://127.0.0.1:1/inference" 2>&1)"
case "$out" in RED*) ok "a server that cannot be reached is RED" ;;
  *) bad "unreachable server not RED" "$out" ;; esac

kill "$WPID" 2>/dev/null; WPID="$(serve 8796 bad "$D/whisper2.log" | head -1)"
out="$("$SELF" --check --server "http://127.0.0.1:8796/inference" 2>&1)"
case "$out" in RED*) ok "an answer carrying no transcription is RED" ;;
  *) bad "shape mismatch not RED" "$out" ;; esac
printf '%s' "$out" | grep -q "Invalid request" \
  && ok "names what the server said instead" || bad "did not quote the refusal" "$out"

rm -f "$D/state" "$D/door.log"
WPID4="$(serve 8799 good "$D/whisper5.log" | head -1)"
"$SELF" --server "http://127.0.0.1:8799/inference" >/dev/null 2>&1
kill "$WPID4" 2>/dev/null
[ ! -s "$D/door.log" ] && ok "a healthy first tick says nothing" \
  || bad "the first tick announced itself: $(cat "$D/door.log")"
[ "$(cat "$D/state")" = GREEN ] && ok "and still records the state" || bad "state not written"

rm -f "$D/state" "$D/door.log"
"$SELF" --server "http://127.0.0.1:1/inference" >/dev/null 2>&1
[ -s "$D/door.log" ] && ok "a first tick that is already RED does speak" \
  || bad "installed onto a broken console and said nothing"

# --- the one that matters: it says it ONCE ---
rm -f "$D/state" "$D/door.log"
"$SELF" --server "http://127.0.0.1:1/inference" >/dev/null 2>&1
"$SELF" --server "http://127.0.0.1:1/inference" >/dev/null 2>&1
"$SELF" --server "http://127.0.0.1:1/inference" >/dev/null 2>&1
n="$(wc -l < "$D/door.log" 2>/dev/null || echo 0)"
[ "$n" = 1 ] && ok "three RED ticks in a row send one message" \
  || bad "three RED ticks sent $n messages"
grep -q "cannot transcribe" "$D/door.log" \
  && ok "the message says what happened" || bad "message does not name the fault"
longest="$(python3 -c 'import json,sys
print(max(len(json.loads(l)["message"]) for l in open(sys.argv[1])))' "$D/door.log")"
[ "$longest" -le 130 ] \
  && ok "the message fits what send_zach accepts ($longest chars)" \
  || bad "message is $longest chars; send_zach refuses over 140 including its tag"

rm -f "$D/state" "$D/door.log"
WPID3="$(serve 8798 bad "$D/whisper4.log" | head -1)"
"$SELF" --server "http://127.0.0.1:8798/inference" >/dev/null 2>&1
kill "$WPID3" 2>/dev/null
longest="$(python3 -c 'import json,sys
print(max(len(json.loads(l)["message"]) for l in open(sys.argv[1])))' "$D/door.log")"
[ "$longest" -le 130 ] \
  && ok "a 300-char refusal still fits the relay ($longest chars)" \
  || bad "a long reason produced $longest chars; the relay refuses over 140"

rm -f "$D/state" "$D/door.log"
"$SELF" --server "http://127.0.0.1:1/inference" >/dev/null 2>&1
WPID2="$(serve 8797 good "$D/whisper3.log" | head -1)"
"$SELF" --server "http://127.0.0.1:8797/inference" >/dev/null 2>&1
kill "$WPID2" 2>/dev/null
n="$(wc -l < "$D/door.log")"
[ "$n" = 2 ] && ok "recovery is worth exactly one more message" \
  || bad "recovery sent the wrong number of messages ($n)"
grep -q "transcribing again" "$D/door.log" \
  && ok "and says the console is back" || bad "recovery message missing"

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" = 0 ]
