#!/usr/bin/env bash
# crt-potato-status.sh -- crt#325's "potato pushes status" half.
#
# Writes a machine-readable snapshot to ~/.crt/potato-status.json on every
# tick: crt-console-selfcheck.sh's own verdict, tail lines of the three logs
# #325 names (stt.log, gate.log, stt-supervisor.log), and Tailscale backend
# state. This is the LOCAL half only -- publishing it somewhere monkey can
# read without shell on potato (an issue comment, a file on the tailnet) is
# deliberately NOT done here.
#
# Why not: potato holds no GitHub credential today (crt#16 -- pull-only, by
# construction). crt#16's own text sketches a FUTURE credential scoped to
# "contents read+write, nothing else" on hf7y/crt -- that would cover a git
# push of this file to a branch, but not an `issues:write` scope for
# commenting on a pinned status issue. Minting either is Zach's call, not
# something to assume here. crt-console-selfcheck.sh's existing Zaxon relay
# alert (send_zach, no GH credential, already tailnet-reachable) is the one
# transport already proven to leave the box without SSH -- reused below for
# the RED-transition alert (crt#323's own ask). It is capped ~85 chars and
# fires only on transition, so it is not a substitute for the full snapshot.
#
# Run WITHOUT --check (not the probe-only mode): this is the one call per
# tick, its stdout is this snapshot's verdict, and its own state-file/
# send_zach side effect is exactly #323's "RED selfcheck reaches Zach" ask,
# on the same timer, for free -- a second, --check-only call would just be
# the same probe run twice.
set -uo pipefail

BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="${CRT_POTATO_STATUS_OUT:-$HOME/.crt/potato-status.json}"
STT_LOG="${CRT_STT_LOG:-$HOME/.crt/stt.log}"
GATE_LOG="${CRT_STT_GATE_LOG:-$HOME/.crt/gate.log}"
SUP_LOG="${CRT_STT_SUP_LOG:-$HOME/.crt/stt-supervisor.log}"
TAILSCALE="${CRT_POTATO_STATUS_TAILSCALE:-tailscale}"

mkdir -p "$(dirname "$OUT")" 2>/dev/null || true

selfcheck="$(bash "$BIN_DIR/crt-console-selfcheck.sh" 2>/dev/null || true)"
# crt-console-selfcheck.sh's own final line is `printf '%s  %s\n' "$state"
# "$why"` -- two literal spaces, not a tab, in both --check and normal mode.
state="${selfcheck%%  *}"; why="${selfcheck#*  }"
[ -n "$state" ] || { state="UNKNOWN"; why="crt-console-selfcheck.sh produced no verdict"; }

ts_json='{}'
if command -v "$TAILSCALE" >/dev/null 2>&1; then
  probe="$("$TAILSCALE" status --json 2>/dev/null || true)"
  [ -n "$probe" ] && ts_json="$probe"
fi

tail_lines() { [ -r "$1" ] && tail -n "${2:-5}" "$1" 2>/dev/null || true; }

python3 - "$OUT" "$state" "$why" "$ts_json" \
  <(tail_lines "$STT_LOG") <(tail_lines "$GATE_LOG") <(tail_lines "$SUP_LOG") <<'PYEOF'
import json, sys, datetime

out_path, state, why, ts_raw = sys.argv[1:5]
stt_path, gate_path, sup_path = sys.argv[5:8]

def read_lines(path):
    try:
        with open(path) as f:
            return [line.rstrip("\n") for line in f]
    except OSError:
        return []

try:
    tailscale = json.loads(ts_raw)
except ValueError:
    tailscale = {}

doc = {
    "generated_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    "selfcheck": {"state": state, "why": why},
    "tailscale_backend_state": tailscale.get("BackendState", "UNKNOWN"),
    "logs": {
        "stt.log": read_lines(stt_path),
        "gate.log": read_lines(gate_path),
        "stt-supervisor.log": read_lines(sup_path),
    },
}
with open(out_path, "w") as f:
    json.dump(doc, f, indent=2)
    f.write("\n")
PYEOF
