#!/usr/bin/env bash
# crt-dexter-vendored-units-check.sh -- did a vendored --install unit ever
# land on dexter? (hf7y/crt#105). Unit names come from grepping
# provision/dexter/*/*.sh, not a hardcoded list. is-enabled, not
# list-unit-files: only "not-found" means absent (crt#15).
set -uo pipefail

CLI_NAME='crt-dexter-vendored-units-check.sh'
HOST="${1:-dexter}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SSH="${CRT_DEXTER_UNITS_CHECK_SSH:-ssh -o BatchMode=yes -o ConnectTimeout=8}"

case "${1:-}" in
  -h|--help)
    cat <<USAGE
$CLI_NAME [host] -- confirm every provision/dexter/*/*.sh --install unit
                    actually exists on the host (default: dexter)
exit: 0 every discovered unit exists  1 at least one is not-found
      2 usage  4 no vendored --install units found under provision/dexter
      6 BLIND -- could not reach $HOST at all, so nothing was confirmed
USAGE
    exit 0 ;;
esac

mapfile -t UNITS < <(grep -horE '/etc/systemd/system/[A-Za-z0-9_.-]+\.(service|timer)' \
  "$HERE"/provision/dexter/*/*.sh 2>/dev/null | xargs -n1 basename | sort -u)

if [ "${#UNITS[@]}" -eq 0 ]; then
  echo "$CLI_NAME: no vendored --install units found under provision/dexter" >&2
  exit 4
fi

missing=0
blind=0
for u in "${UNITS[@]}"; do
  state="$($SSH "$HOST" systemctl is-enabled "$u" 2>/dev/null)"
  rc=$?
  if [ -z "$state" ] && [ "$rc" -ne 0 ]; then
    echo "BLIND    $u -- could not reach $HOST to ask (ssh exit $rc)"
    blind=$((blind + 1))
  elif [ "$state" = not-found ]; then
    echo "MISSING  $u -- vendored, never installed on $HOST"
    missing=$((missing + 1))
  else
    echo "present  $u ($state)"
  fi
done

if [ "$blind" -gt 0 ]; then
  echo "$CLI_NAME: could not reach $HOST -- $blind of ${#UNITS[@]} unit(s) unconfirmed" >&2
  exit 6
fi
[ "$missing" -eq 0 ] || exit 1
exit 0
