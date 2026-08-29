#!/usr/bin/env bash
# Offline tests for bin/crt-dexter-vendored-units-check.sh (hf7y/crt#105).
# No real dexter access here -- $CRT_DEXTER_UNITS_CHECK_SSH is swapped for a
# fake `ssh` that answers from a script, so the logic is checked without a
# network.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHK="$DIR/../bin/crt-dexter-vendored-units-check.sh"
fail=0
ok()  { echo "ok - $1"; }
bad() { echo "FAIL - $1"; fail=1; }

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

# It discovers real unit names from the tree -- confirm the known zaxon pair
# is among them, so the test itself is pinned to something real.
mapfile -t FOUND < <(grep -horE '/etc/systemd/system/[A-Za-z0-9_.-]+\.(service|timer)' \
  "$DIR"/../provision/dexter/*/*.sh 2>/dev/null | xargs -n1 basename | sort -u)
printf '%s\n' "${FOUND[@]}" | grep -qx 'zaxon-watch.timer' \
  && ok "discovers zaxon-watch.timer from the tree" \
  || bad "did not discover zaxon-watch.timer -- discovery regex broke"

# The real script calls: $SSH "$host" systemctl is-enabled "$u" -- unquoted,
# so a fake with an extra static arg word-splits as argv[0]=that arg,
# argv[1]=host, ..., argv[4]=the unit name.

# All discovered units present -> exit 0, nothing reported MISSING.
cat > "$TMP/ssh-all-enabled" <<'EOF'
#!/usr/bin/env bash
echo enabled
EOF
chmod +x "$TMP/ssh-all-enabled"
out="$(CRT_DEXTER_UNITS_CHECK_SSH="$TMP/ssh-all-enabled" "$CHK" dexter)"
rc=$?
[ "$rc" -eq 0 ] && ok "exits 0 when every unit is enabled" \
  || bad "exit was $rc, expected 0 when every unit is enabled"
echo "$out" | grep -q MISSING \
  && bad "reported MISSING when nothing was missing" \
  || ok "reports nothing MISSING when nothing is missing"

# One unit not-found -> exit 1, and it's named.
cat > "$TMP/ssh-one-missing" <<'EOF'
#!/usr/bin/env bash
# argv: <host> systemctl is-enabled <unit>
unit="$4"
if [ "$unit" = zaxon-watch.timer ]; then
  echo not-found
else
  echo enabled
fi
EOF
chmod +x "$TMP/ssh-one-missing"
out="$(CRT_DEXTER_UNITS_CHECK_SSH="$TMP/ssh-one-missing" "$CHK" dexter)"
rc=$?
[ "$rc" -eq 1 ] && ok "exits 1 when a vendored unit is not-found" \
  || bad "exit was $rc, expected 1 when zaxon-watch.timer is not-found"
echo "$out" | grep -q 'MISSING  zaxon-watch.timer' \
  && ok "names the missing unit in its output" \
  || bad "did not name zaxon-watch.timer as MISSING"

# --help documents itself without touching the network.
# A host that cannot be reached at all must not read as "present" -- that is
# how #105 stayed invisible in the first place.
cat > "$TMP/ssh-unreachable" <<'EOF'
#!/usr/bin/env bash
exit 255
EOF
chmod +x "$TMP/ssh-unreachable"
out="$(CRT_DEXTER_UNITS_CHECK_SSH="$TMP/ssh-unreachable" "$CHK" dexter)"
rc=$?
[ "$rc" -eq 6 ] && ok "exits 6 BLIND when the host cannot be reached" \
  || bad "exit was $rc, expected 6 BLIND when ssh itself fails"
echo "$out" | grep -q MISSING \
  && bad "reported MISSING on an unreachable host -- that is not a confirmed absence" \
  || ok "does not claim MISSING when it never actually asked"
echo "$out" | grep -q BLIND \
  && ok "reports BLIND per unit when the host is unreachable" \
  || bad "did not report BLIND for an unreachable host"

"$CHK" --help >/dev/null 2>&1
[ $? -eq 0 ] && ok '--help exits 0' || bad '--help did not exit 0'

exit "$fail"
