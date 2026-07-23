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

# bad arg -> usage + non-zero
if CRT_MANDARK_CONF="$CONF" bash "$SCRIPT" bogus >/dev/null 2>&1; then
  echo "FAIL: bad arg should be non-zero"; fail=1
else
  echo "PASS: bad arg rejected"
fi

exit "$fail"
