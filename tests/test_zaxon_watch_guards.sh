#!/usr/bin/env bash
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
W="$DIR/../provision/dexter/zaxon/zaxon-watch.sh"
C="$DIR/../provision/dexter/zaxon/zaxon-status-collect.py"
fail=0
ok()   { echo "ok - $1"; }
bad()  { echo "FAIL - $1"; fail=1; }

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
cat > "$TMP/db.py" <<'PY'
import sqlite3,sys
c=sqlite3.connect(sys.argv[1])
c.execute("CREATE TABLE tickets (id TEXT PRIMARY KEY, from_agent TEXT, question TEXT,"
          " wa_message_id TEXT, status TEXT, answer TEXT, created_at TEXT,"
          " answered_at TEXT, options TEXT)")
c.commit()
PY
python3 "$TMP/db.py" "$TMP/tickets.db"
run() { ZAXON_DB="$1" python3 "$C" "$2" "${3:-[]}" 2>/dev/null; }

# The relay lives on dexter and this script runs there, so loopback is the
# default on purpose. Every "zaxon is unreachable from monkey" report traced to
# someone probing the wrong one of these two addresses.
grep -q 'ZAXON_PROBE_URL:-http://127\.0\.0\.1:8643/mcp' "$W" \
  && ok "probes loopback by default (it runs ON dexter)" \
  || bad "default probe URL is not loopback -- see bin/lib/zaxon.sh in realisateur"

# A publisher that needs its subject healthy cannot report the subject's outage.
# Both of these must still produce a document, not an early exit.
[ -n "$(run "$TMP/tickets.db" '{"answers":false}')" ] \
  && ok "still emits a document when the relay is silent" \
  || bad "emitted nothing when the relay was silent -- the outage is the report"
[ -n "$(run "$TMP/nope.db" '{"answers":true}')" ] \
  && ok "still emits a document when the ledger is unreadable" \
  || bad "emitted nothing when the ledger was unreadable"

# A verdict is the whole point; BLIND and DOWN must survive into the document.
v() { run "$1" "$2" | python3 -c 'import json,sys; print(json.load(sys.stdin)["verdict"])'; }
[ "$(v "$TMP/tickets.db" '{"answers":false}')" = DOWN ] \
  && ok "a silent relay is DOWN in the document" || bad "silent relay did not publish DOWN"
[ "$(v "$TMP/nope.db" '{"answers":true}')" = BLIND ] \
  && ok "an unreadable ledger is BLIND, never OK" || bad "unreadable ledger did not publish BLIND"

# stdout is the document and nothing else, or `--check | jq` breaks.
run "$TMP/tickets.db" '{"answers":true}' | python3 -c 'import json,sys; json.load(sys.stdin)' 2>/dev/null \
  && ok "collector stdout is bare JSON" || bad "collector stdout is not parseable JSON"

# A channel cannot page a human about being unable to page a human.
grep -qE 'zaxon_ask|ask_zach' "$W" \
  && bad "publisher calls the relay it is reporting on -- the page IS the alert" \
  || ok "never alerts through zaxon"

# `date +%3N` printed whole nanoseconds on dexter and the page rendered
# "answers in 15750928 ms". curl must time itself.
grep -q 'date +%s%3N' "$W" \
  && bad "times the probe with date +%s%3N -- dexter's date ignores the width" \
  || ok "does not hand-roll the latency measurement"
grep -q "w '%{time_total}'" "$W" \
  && ok "curl reports its own elapsed time" || bad "no curl -w time_total"

# A session id proves the tool surface booted; this endpoint returns 200 for
# shapes it then refuses.
grep -q 'mcp-session-id' "$W" \
  && ok "liveness is a session id, not an HTTP code" || bad "does not read mcp-session-id"

# data/whatsapp/session is a linked-device session and exactly one process may
# hold it. The rule used to live in the README; nothing enforced it after
# realisateur#511 deleted dexter-service-deploy.sh, so the page reports it.
grep -q 'WSL_EXE" -l -v' "$W" \
  && ok "probes for another WSL distro that could seize the session" \
  || bad "nothing detects a second holder for data/whatsapp/session"
grep -q '"hazards"' "$C" \
  && ok "hazards reach the document" || bad "the hazard probe has no field to land in"

# #402: this distro also carries a house-LAN address, so "8643:8643" once gave
# the whole LAN ask_zach. Naming addresses IS the guard.
CMP="$DIR/../provision/dexter/zaxon/compose.yaml"
grep -qE '^\s*-\s*"?0\.0\.0\.0:' "$CMP" \
  && bad "compose binds 0.0.0.0 -- the MCP port has no auth, only a bind" \
  || ok "compose binds named addresses, never 0.0.0.0"

grep -qE '^\s*-\s*"100\.107\.253\.56:8090:8090"' "$CMP" \
  && ok "whisper answers the tailnet" || bad "8090 has no tailnet twin (#133)"
grep -qE '^\s*-\s*"127\.0\.0\.1:8090:8090"' "$CMP" \
  && ok "whisper still answers loopback" || bad "8090 lost its loopback bind"

# The repo's whisper_stt.sh never ran while this lived in data/.env, which
# .deploykeep shields from every deploy.
grep -q 'HERMES_LOCAL_STT_COMMAND' "$CMP" \
  && ok "the STT command ships in compose, not in the shielded .env" \
  || bad "HERMES_LOCAL_STT_COMMAND is not in compose.yaml"

# Publishing needs the ssh user's gh credential, so the unit may not run as root.
grep -q 'User=' "$W" \
  && ok "the systemd unit names a User" || bad "unit would run as root and lose the gh credential"
exit "$fail"
