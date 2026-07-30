#!/usr/bin/env bash
# contract-test.sh -- run this project's contract against ANY implementation.
#
# The whole point: the SAME assertions run against the legacy
# implementation and against the bashified verb. That is what makes "the bashified
# tree keeps the same contract as before" a measured claim
# rather than an assertion.
#
#   ./test/contract-test.sh <command-under-test> [label]
#
# It never hangs: every invocation is wrapped in `timeout`. A failure is
# REPORTED and scored, never fatal to the run -- a contract test that dies
# on assertion 1 tells you nothing about assertions 2..n.

set -uo pipefail
CUT="${1:?usage: contract-test.sh <command-under-test> [label]}"
LABEL="${2:-$CUT}"
TIMEOUT="${CONTRACT_TIMEOUT:-20}"

PASS=0; FAIL=0; GAP=0
declare -a FAILED=()

# run <expected-exit> <description> -- args...
# expected-exit of '*' means "any exit, we assert on output only"
_run() {
  local want="$1" desc="$2"; shift 2
  local out rc
  out="$(timeout "$TIMEOUT" "$CUT" "$@" 2>&1)"; rc=$?
  if [ "$rc" = 124 ]; then
    FAIL=$((FAIL+1)); FAILED+=("$desc -- TIMED OUT after ${TIMEOUT}s")
    printf 'FAIL  %s\n        timed out after %ss\n' "$desc" "$TIMEOUT"; return 1
  fi
  LAST_OUT="$out"; LAST_RC="$rc"
  if [ "$want" != '*' ] && [ "$rc" != "$want" ]; then
    if [ "$rc" = 4 ]; then
      GAP=$((GAP+1)); printf 'GAP   %s\n        exit 4: tooling does not exist yet\n' "$desc"; return 1
    fi
    FAIL=$((FAIL+1)); FAILED+=("$desc -- exit $rc, wanted $want")
    printf 'FAIL  %s\n        exit %s (wanted %s): %s\n' "$desc" "$rc" "$want" "$(printf '%s' "$out" | head -2)"; return 1
  fi
  PASS=$((PASS+1)); printf 'PASS  %s\n' "$desc"; return 0
}

# assert LAST_OUT matches a regex
_out_matches() {
  local re="$1" desc="$2"
  if printf '%s' "${LAST_OUT:-}" | grep -qE "$re"; then
    PASS=$((PASS+1)); printf 'PASS  %s\n' "$desc"
  else
    FAIL=$((FAIL+1)); FAILED+=("$desc")
    printf 'FAIL  %s\n        output did not match /%s/\n' "$desc" "$re"
  fi
}

_out_lacks() {
  local re="$1" desc="$2"
  if printf '%s' "${LAST_OUT:-}" | grep -qE "$re"; then
    FAIL=$((FAIL+1)); FAILED+=("$desc")
    printf 'FAIL  %s\n        output contained /%s/, which it must not\n' "$desc" "$re"
  else
    PASS=$((PASS+1)); printf 'PASS  %s\n' "$desc"
  fi
}

printf '=== contract: %s\n' "$LABEL"
printf '    under test: %s\n\n' "$CUT"

# --------------------------------------------------------------------------
# UNIVERSAL assertions -- every bashified verb must keep these, and they are
# also the ones legacy tooling most often fails, which is the finding.
# --------------------------------------------------------------------------
_run 0 'responds to --help'                     --help
_out_matches 'usage'            'help mentions usage'
_out_matches 'exit'             'help documents its exit codes'

_run 2 'rejects an unknown flag loudly (not exit 0)'  --definitely-not-a-real-flag

# The cost boundary. Either the tool declares it can spend and refuses to do
# so implicitly, or it declares it cannot and rejects the flag outright.
# BOTH are passes. What fails is silence.
_run '*' 'has a stated position on --summon'    --summon
if [ "${LAST_RC:-1}" = 0 ]; then
  FAIL=$((FAIL+1)); FAILED+=('--summon with no argument spent money silently (exit 0)')
  printf 'FAIL  --summon exited 0 with no work requested -- implicit spend\n'
fi

# The no-bundling rule: a near-miss on the cost flag must FAIL, never be
# silently ignored, because a silently-ignored cost flag is a misparse that
# spends money the caller did not authorise.
_run 2 'rejects -s as a cost-flag near-miss'    -s
_run 2 'rejects -S as a cost-flag near-miss'    -S

printf '\n--- %s: %d passed, %d failed, %d gaps\n' "$LABEL" "$PASS" "$FAIL" "$GAP"
if [ "${#FAILED[@]}" -gt 0 ]; then
  printf 'failures:\n'; printf '  - %s\n' "${FAILED[@]}"
fi
# Report, do not hang the sweep: a nonzero here is information for the
# caller, and the caller decides whether it is fatal.
[ "$FAIL" = 0 ]
