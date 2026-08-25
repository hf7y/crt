#!/bin/bash
# Prove STT end to end from inside the gateway: prints a known sample's
# transcript and exits 0, else prints why. Asserted by dexter-liveness.sh, whose
# header says why a port check is not enough. Writes one mktemp dir, removes it.
set -uo pipefail

SAMPLE="${STT_SELFTEST_SAMPLE:-/opt/zaxon-relay/samples/jfk.wav}"
[ -r "$SAMPLE" ] || { echo "no sample at $SAMPLE"; exit 2; }

# RESOLVED AS THE GATEWAY RESOLVES IT: .env is loaded with override=True and so
# beats compose. Reading it first is what notices a re-added mount-local path.
env_file="${HERMES_HOME:-$HOME/.hermes}/.env"
cmd="$(sed -n 's/^[[:space:]]*HERMES_LOCAL_STT_COMMAND=//p' "$env_file" 2>/dev/null | tail -1)"
[ -n "$cmd" ] || cmd="${HERMES_LOCAL_STT_COMMAND:-}"
[ -n "$cmd" ] || { echo "HERMES_LOCAL_STT_COMMAND is unset"; exit 3; }

out="$(mktemp -d)"; trap 'rm -rf "$out"' EXIT

cmd="${cmd//\{input_path\}/$SAMPLE}"
cmd="${cmd//\{output_dir\}/$out}"
cmd="${cmd//\{language\}/en}"

err="$(eval "$cmd" 2>&1 >/dev/null)"; rc=$?
if [ "$rc" -ne 0 ]; then
  # rc=7 is curl's CURLE_COULDNT_CONNECT: whisper is not listening on 8090.
  echo "STT command failed (rc=$rc): ${err:-no stderr}"
  exit 4
fi

[ -s "$out/transcript.txt" ] || { echo "STT command produced no transcript"; exit 5; }
tr -d '\r' < "$out/transcript.txt" | tr '\n' ' ' | sed 's/[[:space:]]\{1,\}/ /g;s/^ //;s/ $//'
