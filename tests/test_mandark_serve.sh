#!/usr/bin/env bash
# Offline, NON-DESTRUCTIVE test for bin/crt-mandark-serve.sh. Only exercises
# `status` and arg handling -- never `on`/`off`, so it's safe to run on the
# live mandark box without touching the bridge/tunnel processes. The
# whisper component was retired crt#149 -- potato's STT now points at
# dexter's containerized whisper.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$DIR/../bin/crt-mandark-serve.sh"
fail=0

bash -n "$SCRIPT" && echo "PASS: syntax" || { echo "FAIL: syntax"; fail=1; }

# status lists both components and must exit 0
out="$(bash "$SCRIPT" status 2>&1)"; rc=$?
if [ "$rc" -eq 0 ]; then echo "PASS: status exits 0"; else echo "FAIL: status rc=$rc"; fail=1; fi
for c in bridge tunnel; do
  echo "$out" | grep -q "$c:" && echo "PASS: status reports $c" || { echo "FAIL: no $c in status"; fail=1; }
done

# bad arg -> usage + non-zero
if bash "$SCRIPT" bogus >/dev/null 2>&1; then echo "FAIL: bad arg should be non-zero"; fail=1
else echo "PASS: bad arg rejected"; fi

exit "$fail"
