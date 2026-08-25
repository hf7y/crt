#!/usr/bin/env bash
# zaxon-autoupdate.sh -- pull what crt published, and prove it is running.
#
# WHY. #70 shipped the anti-spam question queue, zaxon-image.yml rebuilt the
# image the same minute, and the container on dexter kept running the old code
# for an hour -- during which two junk messages reached Zach's phone that the
# queue would have held. Merging is not shipping, and nothing noticed.
#
# WHAT IT WATCHES IS DERIVED, NOT TYPED. The image list comes from compose.yaml,
# so a service added there is watched without editing this file. Retyping the
# list is how the two drift, and this repo has that failure written down.
#
# crt is DEV and does not operate dexter. It vendors this; a human installs it
# once (see --install), and after that nobody has to remember.
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

  --check     report whether any watched image has moved; writes nothing
  --apply     pull + up -d when it has, then verify the relay answers
  --install   write the systemd unit+timer that runs --apply hourly (root)

exit: 0 up to date, or updated and verified   1 update failed or unverified
      2 usage   4 compose.yaml unreadable      6 BLIND -- registry unreachable
USAGE
      exit 0 ;;
    *) echo "$CLI_NAME: unknown argument $a" >&2; exit 2 ;;
  esac
done

COMPOSE="$COMPOSE_DIR/compose.yaml"
[ -r "$COMPOSE" ] || { echo "$CLI_NAME: cannot read $COMPOSE" >&2; exit 4; }

# ONE SOURCE for what is watched: every image: line in the compose file.
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

# A registry read that fails must never look like "nothing to do" -- that is
# exactly the silence this script exists to end.
moved=0; blind=0
# HASH THE OUTPUT ONLY AFTER PROVING THERE IS OUTPUT. `docker manifest inspect
# X | sha256sum` on a failed lookup hashes the EMPTY STRING and returns a
# perfectly valid-looking digest, so the BLIND branch below could never fire --
# and two unreachable images would both hash to that same empty-sha and compare
# EQUAL, reporting "up to date" for a registry nobody could read. Caught by
# pointing --check at a nonexistent repo, 2026-08-25; it answered MOVED.
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

# VERIFY BY ASKING THE RELAY, not by trusting `up -d`. A container that starts
# and crashes reports Started. The tool surface is the thing callers depend on,
# so that is what gets checked.
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
