#!/usr/bin/env bash
# digest_of() must not hash docker's stderr-drained empty stdout into a
# valid-looking digest when the registry is unreachable -- see
# zaxon-autoupdate.sh's own comment beside digest_of().
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
case "$1 $2" in
  "manifest inspect") exit 1 ;;
  "image inspect")    echo "ghcr.io/hf7y/zaxon-relay:latest@sha256:oldlocal" ;;
esac
exit 0
SH
chmod +x "$TMP/bin/docker"

out="$(PATH="$TMP/bin:$PATH" ZAXON_COMPOSE_DIR="$TMP" bash "$A" --check 2>"$TMP/err")"
rc=$?

[ "$rc" -eq 6 ] \
  && ok "exits 6 BLIND when the registry read fails, not 0" \
  || bad "exit was $rc, expected 6"

echo "$out" | grep -q '^  BLIND' \
  && ok "reports BLIND for the unreadable image" \
  || bad "did not report BLIND: $out"

echo "$out" | grep -qE '^  same|up to date' \
  && bad "a failed manifest read was reported as up to date -- the empty-string digest bug" \
  || ok "never claims up to date on an unreadable registry"

grep -q 'BLIND' "$TMP/err" \
  && ok "says on stderr that it is refusing to report up-to-date" \
  || bad "stayed silent on stderr about the BLIND result"

exit "$fail"
