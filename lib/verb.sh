#!/usr/bin/env bash
# verb.sh -- the shared runtime every bashified utility sources.
#
# One copy of the argument grammar, the cost boundary, and the failure
# vocabulary, so nineteen utilities cannot drift into nineteen dialects.
# Config is read here and nowhere else.
#
# WHAT --summon ACTUALLY IS (read this before the cost boundary below;
# stating it only as a cost boundary is what made it misread -- Zach,
# interactive, 2026-07-31):
#
#   A summon is how a verb WRITES ITSELF FROM THE INSIDE.
#
#   In this ecosystem the man page is written BEFORE the utility works, and
#   the utility is judged against the page. So a page routinely contracts an
#   action with no mechanism behind it yet. That is the normal case, not a
#   defect. When a caller invokes such an action:
#
#     without --summon  the verb exits 3 and PRINTS THE SUMMON it would have
#                       made. Nothing is spent. The gap is named, not hidden.
#     with --summon     an agent is summoned to perform the action AND to
#                       leave behind a durable mechanism that performs it
#                       WITHOUT an agent next time (basheur Law 2: every
#                       summon leaves residue; residue becomes an impl).
#
#   So the flag does not merely buy one answer. It buys the answer plus the
#   machine that makes the next answer free. A verb carrying --summon is a
#   verb still under construction by its own callers, and the correct
#   direction of travel is that the flag stops costing anything, one
#   subcommand at a time, because the mechanism now exists.
#
#   Escalate through basheur -- `basheur run --summon <contract>` -- never by
#   contacting a model directly. basheur is the contract store that decides
#   MECHANIZED (exec the impl, spend nothing, say so) versus AGENT (summon).
#   A verb that calls a model itself has re-animated its own project, which
#   is what Law 3 forbids.
#
# THE COST BOUNDARY (the second thing this file exists for):
#   Nothing in a bashified utility may spend money implicitly. A utility
#   that CAN spend declares VERB_CAN_SUMMON=1 and gains --summon; one that
#   cannot does not carry the flag at all.
#
#   --summon means "spend IF AND ONLY IF the contract cannot be fulfilled
#   mechanically" -- a grant of permission, never an instruction to spend.
#   On an already-mechanized action it costs zero and says so on stderr.
#   The other reading ("spend because I said so") looks identical at the
#   prompt and diverges completely in the bill: under it, de-animation stops
#   showing up in the only place it was ever going to show up.
#
#   Because nearly every verb can now escalate, the presence of --summon no
#   longer sorts tools into spending and non-spending. The informative
#   question moved from WHETHER a tool spends to WHICH OF ITS SUBCOMMANDS do,
#   which is why a man page must name them and the page test checks it.
#
#   Short form is deliberately ABSENT. `-s` collides with existing tools
#   and `-S` differs from it by one shift key, which is an unacceptable
#   property for the only flag that spends real money. Typing the whole
#   word IS the deliberateness.
#
# ===========================================================================
# DE-FORKED 2026-08-02. This file is the UNION of four dialects.
# ===========================================================================
# The header above says this exists "so nineteen utilities cannot drift into
# nineteen dialects." It had drifted into FOUR, and the canonical skeleton was
# running in only two of the seven repos. Measured, not asserted:
#
#   105 lines  ecosim, realisateur, vim-arcade
#   155 lines  bibliothecaire, scheduler          <- was the skeleton
#   128 lines  senechal                           (+ write vocabulary)
#   184 lines  gardien                            (+ refusal, measured cost)
#
# The 105-line copy was API-IDENTICAL to the skeleton -- same functions, same
# variables; only comments and output wording differed. It was simply older.
# The other two are genuine supersets in different directions, and both are
# adopted here because each was already being re-invented locally:
#
#   verb_refuse / exit 7 was re-implemented BY HAND in bibliothecaire's
#   bin/fonde and senechal's bin/installe, independently, because the shared
#   runtime did not carry it. Three copies of a thing is the evidence that it
#   belongs in one.
#
# WHAT ADOPTING IT DECIDES. gardien's copy recorded exit 7 as "PROPOSED
# ecosystem-wide, see realisateur QUESTIONS -- until it is decided there, this
# file is the only copy carrying it, and that divergence is deliberate and
# recorded." Adopting it here DECIDES that proposal, in the direction the
# evidence had already gone without waiting for a ruling. Said out loud rather
# than folded in quietly, because a proposal adopted by merge is indistinguish-
# able from one nobody ever ruled on.
#
# WHAT IS DELIBERATELY *NOT* ADOPTED, and this is the important one.
# gardien's `verb_gap_or_summon` is NOT here. It calls `claude -p` directly.
# Read line 32 of this file: escalate through basheur, "never by contacting a
# model directly... a verb that calls a model itself has re-animated its own
# project, which is what Law 3 forbids." Merging it verbatim would propagate a
# violation of this runtime's own stated law into every repo that sources it.
#
#   gardien's `bin/garde` calls it at 4 sites, so GARDIEN CANNOT BE DE-FORKED
#   onto this runtime until that is resolved, and the drift guard reports it
#   as a finding rather than exempting it. The fix is not mechanical: the
#   function's second argument is a free-text prompt, while `basheur run
#   --summon <contract>` takes a CONTRACT NAME, so all four call sites change
#   shape. That is its own piece of work.
#
#   A guard that quietly exempted gardien would be worse than the fork: the
#   fork is at least visible.

set -uo pipefail

VERB_NAME="${VERB_NAME:?verb.sh: VERB_NAME must be set before sourcing}"
VERB_SUMMARY="${VERB_SUMMARY:-}"
VERB_CAN_SUMMON="${VERB_CAN_SUMMON:-0}"

# A verb that CHANGES something declares VERB_CAN_WRITE=1 and gains the two
# flags every unix writing tool has: -n/--dry-run and -f/--force. Same opt-in
# shape as --summon, for the same reason -- a read-only verb that accepted
# --force would advertise a power it does not have, and `--help` is where a
# caller finds out whether a tool can change anything. (From senechal, whose
# `installe` is the only verb in the ecosystem built on it.)
VERB_CAN_WRITE="${VERB_CAN_WRITE:-0}"
VERB_DRYRUN=0
VERB_FORCE=0

# THE COST IS READ FROM A MEASUREMENT, NEVER TYPED IN. (From gardien.) A
# summon flag printing "cost: unmeasured" asks a human to authorise an unknown
# amount, which is weaker than the argument this file makes at length about
# why -s/-S are rejected. If no measurement exists, say so in those words and
# mark the next run as the measuring one -- honest, and it closes the gap by
# construction rather than by intention.
#
# An explicit VERB_SUMMON_COST still wins, so a verb that already knows its own
# cost (`bashify` sets one) is unaffected by this.
VERB_COST_FILE="${VERB_COST_FILE:-${XDG_DATA_HOME:-$HOME/.local/share}/$VERB_NAME/summon-cost}"
if [ -n "${VERB_SUMMON_COST:-}" ]; then
  :
elif [ -s "$VERB_COST_FILE" ]; then
  VERB_SUMMON_COST="$(head -1 "$VERB_COST_FILE")"
else
  VERB_SUMMON_COST="UNMEASURED -- the next summon is the measuring run"
fi

# Record what a summon actually cost, so the NEXT caller sees a number.
# Never fatal: bookkeeping must not be able to break the verb that called it.
verb_record_cost() {
  mkdir -p "$(dirname "$VERB_COST_FILE")" 2>/dev/null || return 0
  printf '%s\n' "$1" > "$VERB_COST_FILE" 2>/dev/null || return 0
}

VERB_SUMMON=0        # did the caller authorise spending?
VERB_JSON=0
VERB_QUIET=0

# ---------------------------------------------------------------- failing
# Exit codes are part of the contract. An exit-0 no-op is the failure this
# ecosystem records more than any other, so every one of these is loud.
#   0  the promise was kept
#   2  usage error (the caller is wrong)
#   3  this needs a summon and did not get one -- A FINDING, NOT AN ERROR
#   4  GAP: SHOULD DO -- in scope, not built yet. A summon is legitimate here.
#   5  the promise was broken (ran, produced a wrong or partial answer)
#   6  BLIND: cannot read the domain, so cannot report on it
#   7  REFUSED: WON'T DO -- out of scope on principle. No summon exists.
#
# ON 4 vs 7. Exit 4 is a TEMPORAL claim -- "not yet". It invites escalation:
# summon an agent or do it by hand, then mechanize it so the next call is free.
# GAPS.md is its sink and those entries are meant to DRAIN.
#
# Exit 7 is a claim about SCOPE -- "never". Filing it as a gap would put a
# permanent decision on a to-do list, and GAPS.md would stop being a list that
# can drain, which destroys it as a signal.
#
# The rule that keeps the two honest: --summon is available on 4 and FORBIDDEN
# on 7. A gap names its own escalation; a refusal offers none, because having
# no escalation path is what refusing on principle MEANS. Without this,
# --summon degrades into a general-purpose "do it anyway" flag -- the failure
# mode a spending flag wired to an agent invites most.
verb_die()   { printf '%s: %s\n' "$VERB_NAME" "$*" >&2; exit 2; }
# The wording here is LOAD-BEARING and deliberately unchanged. gardien's copy
# said "in scope, not built yet"; adopting that phrasing along with its 4-vs-7
# substance broke `man/bashify.1`'s EXAMPLES doctest and bibliothecaire's
# `man/verse.1`, both of which reproduce this line verbatim. A runtime string
# that pages assert is part of the contract, and the page is what the tool is
# judged against -- so the doctrine came across and the phrasing did not.
# Changing it later means amending every page that quotes it, in the same
# commit, through `bashify amend`.
verb_gap()   { printf '%s: GAP: %s\n' "$VERB_NAME" "$*" >&2
               printf '%s: no tooling exists for this yet; see GAPS.md\n' "$VERB_NAME" >&2
               exit 4; }
verb_broke() { printf '%s: BROKEN: %s\n' "$VERB_NAME" "$*" >&2; exit 5; }
verb_blind() { printf '%s: BLIND: %s\n' "$VERB_NAME" "$*" >&2
               printf '%s: this is "I cannot see", NOT "nothing to report".\n' "$VERB_NAME" >&2
               exit 6; }
verb_refuse() { printf '%s: REFUSED: %s\n' "$VERB_NAME" "$*" >&2
                printf '%s: this is out of scope on principle, not unbuilt. No summon lifts it.\n' "$VERB_NAME" >&2
                exit 7; }

# ------------------------------------------------------------ the summon
# Refuse rather than spend. Callers that want the money spent must say so.
verb_need_summon() {
  local what="$1"
  [ "$VERB_CAN_SUMMON" = 1 ] || verb_die "internal: verb_need_summon in a utility that declares no summon"
  if [ "$VERB_SUMMON" = 1 ]; then
    return 0
  fi
  printf '%s: this needs a summon: %s\n' "$VERB_NAME" "$what" >&2
  printf '%s: no mechanism for it exists yet, so nothing was done and nothing was spent.\n' "$VERB_NAME" >&2
  printf '%s: cost if summoned: %s\n' "$VERB_NAME" "$VERB_SUMMON_COST" >&2
  printf '%s: re-run with --summon to have an agent perform it AND leave behind\n' "$VERB_NAME" >&2
  printf '%s: the mechanism that performs it without an agent next time.\n' "$VERB_NAME" >&2
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
      -n|--dry-run)
        [ "$VERB_CAN_WRITE" = 1 ] || verb_die "--dry-run: this utility changes nothing; the flag does not exist here"
        VERB_DRYRUN=1 ;;
      -f|--force)
        [ "$VERB_CAN_WRITE" = 1 ] || verb_die "--force: this utility changes nothing; the flag does not exist here"
        VERB_FORCE=1 ;;
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
  if [ "$VERB_CAN_WRITE" = 1 ]; then
    printf '  -n, --dry-run print what would change; change nothing\n'
    printf '  -f, --force   override a refusal (see the man page for which)\n'
  fi
  printf '  --json        machine-readable output\n'
  printf '  --quiet, -q   suppress commentary; results only\n'
  printf '  -h, --help    this text\n'
  printf '  --version     print version\n'
  if [ "$VERB_CAN_SUMMON" = 1 ]; then
    printf '  --summon      permit an agent to be summoned for an action this\n'
    printf '                utility does not yet implement -- it performs the\n'
    printf '                action and leaves behind the mechanism that will\n'
    printf '                perform it next time without an agent.\n'
    printf '                Spends real money ONLY if no mechanism exists yet\n'
    printf '                (cost: %s). Already-mechanized work costs nothing\n' "$VERB_SUMMON_COST"
    printf '                and says so. Without this flag such an action\n'
    printf '                exits 3 and prints the summon it would have made.\n'
    printf '                No short form exists, deliberately.\n'
  else
    printf '\nThis utility cannot spend money. It has no --summon flag.\n'
  fi
  # A utility that cannot return every code must not advertise every code:
  # `--help` and the man page are the same promise stated twice, and row 4 of
  # THE PAGE TEST is bidirectional. VERB_EXITS lets a verb name only the codes
  # it can actually reach; the full vocabulary remains the default. (From
  # senechal, where `installe` reaches 7, 8 and 9 and not 3 or 4.)
  printf '\nexit: %s\n' "${VERB_EXITS:-0 kept  2 usage  3 needs-summon  4 gap  5 broken  6 blind  7 refused}"
  printf 'see: man %s\n' "$VERB_NAME"
}
