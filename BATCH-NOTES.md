# BATCH-NOTES.md — the nightly-batch tier's own staging file

**What this is.** The unattended nightly-batch tier (the disposable clone on
mandark, see `DEVELOPMENT-WORKFLOW.md`'s three-tier model) cannot write to
`.claude/`. Every write to `.claude/QUESTIONS.md` and `.claude/FOCUS.md` from
this tier has been refused as a sensitive file on **four consecutive cycles**
(2026-07-24, and three times on 2026-07-25). The `nightly-batch` skill
nonetheless instructs this tier to keep `.claude/FOCUS.md` current and to
append open questions to `.claude/QUESTIONS.md`, so that instruction has been
unsatisfiable for four cycles running and the questions have only ever reached
Zach through `~/reports/crt/LATEST.md`.

**What it is not.** Not a replacement for `.claude/QUESTIONS.md` or
`.claude/FOCUS.md` — those stay the source of truth. This is a *staging area*:
entries below are what this tier would have appended to one of those files and
could not. Anything here should be folded into the real file by a human or by
an ungated (interactive) session, and then deleted from here. If this file is
empty apart from this header, nothing is pending.

**Why in the repo rather than `~/reports/`.** Reports are per-day snapshots and
get superseded; a pending question needs to survive until someone actions it,
and it needs to travel with the code it is about. This tier can commit and push
(see `CLAUDE.md`'s push permission), so a tracked file at the repo root is the
one durable channel it actually owns.

---

## Pending — for `.claude/QUESTIONS.md`

- **2026-07-25 (fourth cycle): what did `bin/crt-mic-footer.sh` do, and does
  potato still have it?** `tests/run_tests.sh` claimed to test it
  (`== crt-mic-footer.sh status-bar rendering ==`) from `38607bd` onward — one
  of the four potato cherry-picks — but neither `tests/test_mic_footer.sh` nor
  `bin/crt-mic-footer.sh` has ever existed in this repo. The cherry-pick took
  the runner's reference and left both files behind on potato, and an
  `if [ -f ]` guard meant the suite printed that header and reported ALL GREEN
  regardless, so nobody noticed. Removed the claim rather than fake it
  (`ad41f5a`).
  **What's needed, one command when potato is reachable:**
  `ssh potato "ls ~/crt/bin/crt-mic-footer.sh ~/crt/tests/test_mic_footer.sh"`
  — pull both back if they're there.

- **2026-07-25 (fourth cycle): does potato's `crt-audio-doctor.sh` emit
  BUSY/ERROR verdicts?** The same inherited runner header claimed
  "BUSY/DEAD/ERROR/LIVE". The copy in this repo emits only `LIVE` and
  `DEAD/STALE` (plus a usage exit 2). `tests/test_audio_doctor.sh` was written
  against what the code here actually does; if potato's copy really does have
  two more verdicts, that is a divergence to reconcile, not something to fake
  on this side.

- **2026-07-25 (fourth cycle): should this tier be allowed to write
  `.claude/`, or is this file the answer?** Four cycles is long enough that it
  is a standing decision rather than a glitch. Either grant the allowance, or
  bless this file and drop the `.claude/FOCUS.md` upkeep instruction from the
  `nightly-batch` skill so it stops asking for something that cannot happen.

## Pending — for `.claude/FOCUS.md`

- **Ranked-backlog item 5c (test-coverage gaps) needs one line added:** the
  gap was not only "files with no test" but "tests the suite does not run".
  `run_tests.sh` now has a manifest check enforcing both directions
  (`ad41f5a`), so the *class* is closed mechanically; what remains under 5c is
  still the genuinely-missing coverage it already names (`crt-monologue.py` has
  `test_monologue_py.py` now; `crt-stt-solo.py` has helper/gate/device/duck
  tests but still no test of `main()`'s loop as a whole beyond the
  duck end-to-end pair).
