#!/usr/bin/env bash
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
A="$DIR/../provision/dexter/zaxon/zaxon-autoupdate.sh"
fail=0
ok()  { echo "ok - $1"; }
bad() { echo "FAIL - $1"; fail=1; }

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin"
cat > "$TMP/compose.yaml" <<'YAML'
services:
  relay:
    image: ghcr.io/hf7y/zaxon-relay:latest
YAML

cat > "$TMP/bin/docker" <<'SH'
#!/usr/bin/env bash
echo "$*" >> "$DOCKER_LOG"
case "$1 $2" in
  "manifest inspect")
    case "$3" in *"@sha256:oldlocal") echo OLDMANIFEST ;; *) echo NEWMANIFEST ;; esac ;;
  "image inspect")
    case "$5" in
      *RepoDigests*) echo "$3@sha256:oldlocal" ;;
      *.Id*)         echo "sha256:knowngoodid" ;;
    esac ;;
esac
exit 0
SH
chmod +x "$TMP/bin/docker"

DOCKER_LOG="$TMP/docker.log"
export DOCKER_LOG
PATH="$TMP/bin:$PATH" ZAXON_COMPOSE_DIR="$TMP" \
  ZAXON_PROBE_URL="http://127.0.0.1:1/mcp" \
  ZAXON_VERIFY_TRIES=1 ZAXON_VERIFY_SLEEP=0 \
  bash "$A" --apply > "$TMP/out" 2> "$TMP/err"
rc=$?

grep -q '^tag sha256:knowngoodid ghcr.io/hf7y/zaxon-relay:latest$' "$DOCKER_LOG" \
  && ok "an unverifiable update re-tags the image that was running: a bad image may not leave down the channel that would report it down (crt#75)" \
  || bad "no rollback: the tag was left pointing at the image that did not answer"

[ "$(grep -c '^compose up -d$' "$DOCKER_LOG")" -eq 2 ] \
  && ok "the stack is restarted after the rollback, not just re-tagged" \
  || bad "rolled the tag back without restarting the stack"

id_at="$(grep -n -- '--format {{.Id}}' "$DOCKER_LOG" | head -1 | cut -d: -f1)"
pull_at="$(grep -n '^compose pull$' "$DOCKER_LOG" | head -1 | cut -d: -f1)"
[ -n "$id_at" ] && [ -n "$pull_at" ] && [ "$id_at" -lt "$pull_at" ] \
  && ok "the known-good digest is captured before the pull, not after (after the pull it IS the broken image)" \
  || bad "captured the known-good digest after the pull -- that is the bad image"

[ "$rc" -eq 1 ] \
  && ok "exits 1 when neither the update nor the rollback answers" \
  || bad "exit was $rc, not 1, with a relay that never answered"

grep -q 'rolling back' "$TMP/err" \
  && ok "says on stderr that it is rolling back" || bad "rolled back silently"

grep -qE '(/srv|/var)[^ ]*(known.good|last.good|digest)' "$A" \
  && bad "records the known-good digest in a file that can rot" \
  || ok "reads the known-good digest from docker, not from a file under /srv that can disagree with the host it describes"

exit "$fail"
