#!/usr/bin/env bash
# zaxon-watch.sh -- publish the state of the human channel at hf7y.com/zaxon.
# Every other sensor reports THROUGH zaxon, so nothing else can report on it.
# LOOPBACK IS CORRECT HERE: this runs ON dexter. Do not "fix" it to the tailnet
# address, which is the route for callers that are not dexter.
# ALWAYS PUBLISHES -- a publisher that needs its subject healthy cannot report
# the outage (monkey-watch.sh's header, at length).
set -uo pipefail

CLI_NAME='zaxon-watch.sh'
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROBE_URL="${ZAXON_PROBE_URL:-http://127.0.0.1:8643/mcp}"
COLLECTOR="${COLLECTOR:-$HERE/zaxon-status-collect.py}"
PAGE_SRC="${PAGE_SRC:-$HERE/zaxon-status.html}"
PUBLISH_REPO="${PUBLISH_REPO:-hf7y/hf7y.github.io}"
PUBLISH_DIR="${PUBLISH_DIR:-zaxon}"
export CADENCE_MIN="${CADENCE_MIN:-60}"
export GRACE_MIN="${GRACE_MIN:-30}"

MODE=--check
for a in "$@"; do
  case "$a" in
    --check|--apply|--install) MODE="$a" ;;
    -h|--help)
      cat <<USAGE
$CLI_NAME -- publish the state of the human channel at hf7y.com/zaxon
  --check     collect and print status.json; publishes nothing
  --apply     collect, then commit the page to $PUBLISH_REPO
  --install   write the systemd unit+timer running --apply hourly (root)
exit: 0 ok  1 publish failed  2 usage  6 BLIND (collector produced nothing)
USAGE
      exit 0 ;;
    *) echo "$CLI_NAME: unknown argument $a" >&2; exit 2 ;;
  esac
done

if [ "$MODE" = --install ]; then
  [ "$(id -u)" -eq 0 ] || { echo "$CLI_NAME: --install needs root" >&2; exit 2; }
  self="$(readlink -f "${BASH_SOURCE[0]}")"
  # As the SSH user, not root: publishing needs that user's gh credential.
  cat > /etc/systemd/system/zaxon-watch.service <<UNIT
[Unit]
Description=Publish the zaxon human-channel status at hf7y.com/zaxon
After=docker.service

[Service]
Type=oneshot
User=${ZAXON_WATCH_USER:-zach}
ExecStart=$self --apply
UNIT
  cat > /etc/systemd/system/zaxon-watch.timer <<UNIT
[Unit]
Description=Hourly publish of the zaxon channel status

[Timer]
OnBootSec=10min
OnUnitActiveSec=1h
Persistent=true

[Install]
WantedBy=timers.target
UNIT
  systemctl daemon-reload
  systemctl enable --now zaxon-watch.timer
  systemctl list-timers zaxon-watch.timer --no-pager | tail -2
  exit 0
fi

# --- 1. does the relay answer? ----------------------------------------------
# An mcp-session-id, not a 200: this endpoint returns 200 for shapes it refuses.
# curl times ITSELF; dexter's date ignores %3N and printed whole nanoseconds.
hdr="$(mktemp)"; trap 'rm -f "$hdr"' EXIT
ms="$(curl -s -D "$hdr" -o /dev/null -m 10 -w '%{time_total}' -X POST "$PROBE_URL" \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"zaxon-watch","version":"1"}}}' \
  2>/dev/null | awk '{printf "%.0f", $1 * 1000}')"
[ -n "$ms" ] || ms=0
sid="$(tr -d '\r' < "$hdr" | awk 'tolower($1)=="mcp-session-id:"{print $2}')"
if [ -n "$sid" ]; then
  RELAY="$(printf '{"answers":true,"url":"%s","ms":%d}' "$PROBE_URL" "$ms")"
else
  RELAY="$(printf '{"answers":false,"url":"%s","ms":%d}' "$PROBE_URL" "$ms")"
fi

# --- 2. the containers ------------------------------------------------------
# A relay answering inside a stack whose gateway is restarting is about to go
# dark; docker is the only place that distinction exists.
CONTAINERS="$(sudo -n docker ps -a --filter 'name=zaxon-' \
  --format '{{.Names}}\t{{.State}}\t{{.Status}}' 2>/dev/null \
  | python3 -c 'import json,sys
print(json.dumps([dict(zip(("name","state","status"),l.rstrip("\n").split("\t")))
                  for l in sys.stdin if l.strip()]))')"
[ -n "$CONTAINERS" ] || CONTAINERS='[]'

# --- 3. the ledger -----------------------------------------------------------
payload="$(python3 "$COLLECTOR" "$RELAY" "$CONTAINERS")"
[ -n "$payload" ] || { echo "$CLI_NAME: collector produced nothing" >&2; exit 6; }

VERDICT="$(printf '%s' "$payload" | python3 -c 'import json,sys; print(json.load(sys.stdin)["verdict"])')"
WHY="$(printf '%s' "$payload" | python3 -c 'import json,sys; print(json.load(sys.stdin)["why"])')"
printf '%s\n' "$payload"
printf '%s: %s -- %s\n' "$CLI_NAME" "$VERDICT" "$WHY" >&2

[ "$MODE" = --apply ] || { printf '%s: NOT published (need --apply)\n' "$CLI_NAME" >&2; exit 0; }

# --- 4. publish --------------------------------------------------------------
# NEVER through zaxon_ask: a channel cannot page a human about being unable to
# page a human. The page IS the alert, read by eye.
WORK="$(mktemp -d)"; trap 'rm -f "$hdr"; rm -rf "$WORK"' EXIT
gh repo clone "$PUBLISH_REPO" "$WORK/site" -- -q --depth 1 2>/dev/null \
  || { echo "$CLI_NAME: could not clone $PUBLISH_REPO -- nothing published" >&2; exit 1; }
mkdir -p "$WORK/site/$PUBLISH_DIR"
printf '%s\n' "$payload" > "$WORK/site/$PUBLISH_DIR/status.json"
[ -f "$PAGE_SRC" ] && cp "$PAGE_SRC" "$WORK/site/$PUBLISH_DIR/index.html"
cd "$WORK/site" || exit 1
if [ -n "$(git status --porcelain "$PUBLISH_DIR")" ]; then
  git add "$PUBLISH_DIR"
  git -c user.name='zaxon-watch' -c user.email='noreply@hf7y.com' \
      commit -q -m "zaxon-watch: $VERDICT ($WHY)"
  git push -q || { echo "$CLI_NAME: push failed" >&2; exit 1; }
  printf '%s: published %s\n' "$CLI_NAME" "$VERDICT"
else
  printf '%s: no change to publish\n' "$CLI_NAME"
fi
