#!/usr/bin/env bash
# zaxon-autoupdate.sh -- pull what crt published, and prove it is running.
# Merging is not shipping: #70's queue sat unrun on dexter for an hour while
# junk it would have held reached Zach's phone. Watches the image: lines in
# compose.yaml, so a new service needs no edit here. crt vendors, a human
# installs once with --install. See hf7y/crt#71.
set -uo pipefail

CLI_NAME='zaxon-autoupdate.sh'
COMPOSE_DIR="${ZAXON_COMPOSE_DIR:-/srv/zaxon}"
PROBE_URL="${ZAXON_PROBE_URL:-http://127.0.0.1:8643/mcp}"
MODE=--check
for a in "$@"; do
  case "$a" in
    --check|--apply|--install) MODE="$a" ;;
    -h|--help)
      cat <<USAGE
$CLI_NAME -- pull what crt published, and prove it is running
  --check     has any watched image moved? writes nothing
  --apply     pull + up -d when it has, then verify the relay answers
  --install   write the systemd unit+timer running --apply hourly (root)
exit: 0 ok  1 update failed/unverified  2 usage  4 no compose.yaml  6 BLIND
USAGE
      exit 0 ;;
    *) echo "$CLI_NAME: unknown argument $a" >&2; exit 2 ;;
  esac
done

COMPOSE="$COMPOSE_DIR/compose.yaml"
[ -r "$COMPOSE" ] || { echo "$CLI_NAME: cannot read $COMPOSE" >&2; exit 4; }

# ONE SOURCE: every image: line in the compose file.
mapfile -t IMAGES < <(grep -oE '^[[:space:]]*image:[[:space:]]*\S+' "$COMPOSE" \
  | awk '{print $2}' | sort -u)
[ "${#IMAGES[@]}" -gt 0 ] || { echo "$CLI_NAME: no image: lines in $COMPOSE" >&2; exit 4; }

if [ "$MODE" = --install ]; then
  [ "$(id -u)" -eq 0 ] || { echo "$CLI_NAME: --install needs root" >&2; exit 2; }
  self="$(readlink -f "${BASH_SOURCE[0]}")"
  cat > /etc/systemd/system/zaxon-autoupdate.service <<UNIT
[Unit]
Description=Pull the zaxon images crt published and verify the relay
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
ExecStart=$self --apply
UNIT
  cat > /etc/systemd/system/zaxon-autoupdate.timer <<UNIT
[Unit]
Description=Hourly check for a new zaxon image

[Timer]
OnBootSec=5min
OnUnitActiveSec=1h
Persistent=true

[Install]
WantedBy=timers.target
UNIT
  systemctl daemon-reload
  systemctl enable --now zaxon-autoupdate.timer
  systemctl list-timers zaxon-autoupdate.timer --no-pager | tail -2
  exit 0
fi

# A failed registry read must never look like "nothing to do".
moved=0; blind=0
# HASH ONLY AFTER PROVING THERE IS OUTPUT. A failed `docker manifest inspect`
# piped to sha256sum hashes the EMPTY STRING into a valid-looking digest, so
# BLIND could never fire and two unreadable images would compare EQUAL and
# report "up to date". Caught by pointing --check at a nonexistent repo.
digest_of() {
  local out rc
  out="$(docker manifest inspect "$1" 2>/dev/null)"; rc=$?
  [ "$rc" -eq 0 ] && [ -n "$out" ] || return 1
  printf '%s' "$out" | sha256sum | cut -c1-16
}

for img in "${IMAGES[@]}"; do
  if ! remote="$(digest_of "$img")"; then
    echo "  BLIND   $img -- registry unreadable"; blind=$((blind + 1)); continue
  fi
  local_id="$(docker image inspect "$img" --format '{{index .RepoDigests 0}}' 2>/dev/null || true)"
  if [ -z "$local_id" ]; then
    echo "  MOVED   $img -- not present locally"; moved=$((moved + 1)); continue
  fi
  if ! cached="$(digest_of "$local_id")"; then
    echo "  BLIND   $img -- local digest $local_id unreadable"; blind=$((blind + 1)); continue
  fi
  if [ "$remote" != "$cached" ]; then
    echo "  MOVED   $img"; moved=$((moved + 1))
  else
    echo "  same    $img"
  fi
done
[ "$blind" -eq 0 ] || { echo "$CLI_NAME: BLIND on $blind image(s) -- refusing to report up-to-date" >&2; exit 6; }

if [ "$moved" -eq 0 ]; then echo "$CLI_NAME: up to date (${#IMAGES[@]} image(s))"; exit 0; fi
if [ "$MODE" = --check ]; then echo "$CLI_NAME: $moved image(s) would be pulled"; exit 0; fi

cd "$COMPOSE_DIR" || exit 4
docker compose pull  || { echo "$CLI_NAME: pull failed" >&2; exit 1; }
docker compose up -d || { echo "$CLI_NAME: up -d failed" >&2; exit 1; }

# VERIFY BY ASKING THE RELAY: a container that starts and crashes still
# reports Started. The tool surface is what callers depend on.
for _ in $(seq 1 20); do
  sid="$(curl -s -m 5 -D- -X POST "$PROBE_URL" \
      -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
      -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"autoupdate","version":"0"}}}' \
      2>/dev/null | grep -i '^mcp-session-id:' | tr -d '\r' | awk '{print $2}')"
  [ -n "$sid" ] && { echo "$CLI_NAME: updated $moved image(s); relay answers (session $sid)"; exit 0; }
  sleep 3
done
echo "$CLI_NAME: pulled and restarted, but the relay did not answer within 60s" >&2
exit 1
