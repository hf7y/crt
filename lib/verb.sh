#!/usr/bin/env bash
# verb.sh -- the shared runtime every bashified utility sources.
#
# One copy of the argument grammar, the cost boundary, and the failure
# vocabulary, so nineteen utilities cannot drift into nineteen dialects.
# Config is read here and nowhere else.
#
# THE COST BOUNDARY (the reason this file exists at all):
#   Nothing in a bashified utility may spend money implicitly. A utility
#   that CAN spend declares VERB_CAN_SUMMON=1 and gains --summon; one that
#   cannot does not carry the flag at all, so `--help` alone answers the
#   question "can this cost me anything?".
#
#   Short form is deliberately ABSENT. `-s` collides with existing tools
#   and `-S` differs from it by one shift key, which is an unacceptable
#   property for the only flag that spends real money. Typing the whole
#   word IS the deliberateness.

set -uo pipefail

VERB_NAME="${VERB_NAME:?verb.sh: VERB_NAME must be set before sourcing}"
VERB_SUMMARY="${VERB_SUMMARY:-}"
VERB_CAN_SUMMON="${VERB_CAN_SUMMON:-0}"
VERB_SUMMON_COST="${VERB_SUMMON_COST:-unmeasured}"

VERB_SUMMON=0        # did the caller authorise spending?
VERB_JSON=0
VERB_QUIET=0

# ---------------------------------------------------------------- failing
# Exit codes are part of the contract. An exit-0 no-op is the failure this
# ecosystem records more than any other, so every one of these is loud.
#   0  the promise was kept
#   2  usage error (the caller is wrong)
#   3  this needs a summon and did not get one -- A FINDING, NOT AN ERROR
#   4  GAP: the tooling to keep this promise does not exist yet
#   5  the promise was broken (ran, produced a wrong or partial answer)
#   6  BLIND: cannot read the domain, so cannot report on it
verb_die()   { printf '%s: %s\n' "$VERB_NAME" "$*" >&2; exit 2; }
verb_gap()   { printf '%s: GAP: %s\n' "$VERB_NAME" "$*" >&2
               printf '%s: no tooling exists for this yet; see GAPS.md\n' "$VERB_NAME" >&2
               exit 4; }
verb_broke() { printf '%s: BROKEN: %s\n' "$VERB_NAME" "$*" >&2; exit 5; }
verb_blind() { printf '%s: BLIND: %s\n' "$VERB_NAME" "$*" >&2
               printf '%s: this is "I cannot see", NOT "nothing to report".\n' "$VERB_NAME" >&2
               exit 6; }

# ------------------------------------------------------------ the summon
# Refuse rather than spend. Callers that want the money spent must say so.
verb_need_summon() {
  local what="$1"
  [ "$VERB_CAN_SUMMON" = 1 ] || verb_die "internal: verb_need_summon in a utility that declares no summon"
  if [ "$VERB_SUMMON" = 1 ]; then
    return 0
  fi
  printf '%s: this needs a summon: %s\n' "$VERB_NAME" "$what" >&2
  printf '%s: cost: %s\n' "$VERB_NAME" "$VERB_SUMMON_COST" >&2
  printf '%s: re-run with --summon to authorise spending real money.\n' "$VERB_NAME" >&2
  exit 3
}

# ------------------------------------------------------------ arg parsing
# Hand-rolled rather than getopts: getopts cannot express "--summon has no
# short form on purpose", and silently accepting a bundled cost flag is
# exactly the misparse that would spend money the caller never authorised.
verb_parse() {
  VERB_ARGS=()
  while [ $# -gt 0 ]; do
    case "$1" in
      --summon)
        [ "$VERB_CAN_SUMMON" = 1 ] || verb_die "--summon: this utility never spends; the flag does not exist here"
        VERB_SUMMON=1 ;;
      --summon=*) verb_die "--summon takes no value" ;;
      -s|-S|-\$|--sum|--summ|--summo)
        # Named explicitly so a near-miss FAILS rather than being ignored.
        verb_die "no short or abbreviated form of --summon exists. Spell it out; that is the point." ;;
      --json)    VERB_JSON=1 ;;
      --quiet|-q) VERB_QUIET=1 ;;
      -h|--help) verb_usage; exit 0 ;;
      --version) printf '%s (bashified)\n' "$VERB_NAME"; exit 0 ;;
      --) shift; VERB_ARGS+=("$@"); break ;;
      -*) verb_die "unknown flag: $1  (try --help)" ;;
      *)  VERB_ARGS+=("$1") ;;
    esac
    shift
  done
}

verb_usage() {
  printf '%s -- %s\n\n' "$VERB_NAME" "$VERB_SUMMARY"
  printf 'usage: %s\n\n' "${VERB_USAGE:-$VERB_NAME [flags]}"
  printf 'flags:\n'
  printf '  --json        machine-readable output\n'
  printf '  --quiet, -q   suppress commentary; results only\n'
  printf '  -h, --help    this text\n'
  printf '  --version     print version\n'
  if [ "$VERB_CAN_SUMMON" = 1 ]; then
    printf '  --summon      AUTHORISE SPENDING REAL MONEY (cost: %s)\n' "$VERB_SUMMON_COST"
    printf '                No short form exists, deliberately.\n'
  else
    printf '\nThis utility cannot spend money. It has no --summon flag.\n'
  fi
  printf '\nexit: 0 kept  2 usage  3 needs-summon  4 gap  5 broken  6 blind\n'
  printf 'see: man %s\n' "$VERB_NAME"
}
