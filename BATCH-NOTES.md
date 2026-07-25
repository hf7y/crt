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

- **2026-07-25 (ninth cycle): should the mono window get a `CRT_COLS`/`CRT_ROWS`
  pin in `crt-console.sh`, the way window 0's screensaver already has?**
  `bin/crt-monologue.py` sized itself once at import, inside the detached tmux
  session `crt-console.sh` builds before its final `exec tmux attach` — tmux
  sizes a detached session 80x24, so window 1 has been drawing 24 rows into a
  15-row pane and scrolling its own top away every frame. Fixed in `6aecc39` by
  resolving the size per frame (the fix `crt-screensaver.py` already got), which
  self-corrects within one 0.5s refresh of the client attaching. **The open
  half:** the screensaver *also* gets an explicit `CRT_COLS=40 CRT_ROWS=15` pin
  in `crt-console.sh` so its frames are right even before attach. Adding the
  same pin here would fix the handful of pre-attach frames, at the cost of
  overriding a differently-sized terminal you attach from for debugging. Not
  added unilaterally — it changes live boot behaviour, which is Zach's call
  under this project's own rule.

- **2026-07-25 (ninth cycle): should something watch `crt-monologue.py`?** Nine
  cycles have now routed the console's honest-failure reports to
  `~/.crt/thoughts.log` for window 1 to render — capture death, a dead whisper
  server, an unspoken reply, a phone that never rang, and (this cycle) an
  utterance nothing handled. Every one of those assumes the process doing the
  rendering is alive, and nothing checks. `crt-console.sh` runs it as
  `./crt-monologue.py; exec bash`, so a crash leaves a bash prompt on the tube
  and every later report goes to a file nobody is drawing — the same
  silent-degradation shape those reports exist to prevent, one level up. This is
  ranked-backlog item 8's supervisor territory; not built unasked.

- **2026-07-25 (fifth cycle): this tier does not run on mandark. It runs on
  dexter, and that changes what the `ssh potato` ask actually is.** Four
  cycles have reported "`ssh potato` blocked, add a `Host` block / authorize
  `dexter_mandark_deploy.pub`" on the premise FOCUS.md states directly: *"The
  nightly-batch runner operates as the persistent `zach` account on mandark
  ... the SAME account this session added `Host potato` to."* Measured this
  cycle, all read-only:
  - `hostname` → `dexter`; addresses `192.168.0.22` plus a `10.255.255.254`
    WSL interface. mandark is `192.168.0.27` (from the `mandark-lan` block in
    `~/.ssh/config`). **This tier is not on mandark and never was.**
  - `~/.ssh/config` defines exactly three hosts: `mandark-lan`,
    `github-scheduler-deploy`, `github-wtul-deploy`. No `potato`, no
    `crt-vm`. The keys on disk are `dexter_mandark_deploy`,
    `dexter_scheduler_deploy`, `dexter_wtul_deploy` — the naming is
    from-dexter-to-X throughout, which corroborates the hostname.
  - **Routing through mandark is not available either.** `ssh mandark-lan
    <anything>` returns `fatal: unrecognized command` — that account is
    restricted to `git-shell`. It serves `origin`
    (`/home/zach/git-remotes/crt.git`, push/fetch work fine) and nothing
    else. So this tier cannot run the mandark-side setup script, restart the
    bridge, or hop to potato from there.

  So the block is not a config oversight this side could fix: dexter has
  never had a path to potato at all. **The decision needed:** either give
  dexter direct SSH to potato (a `Host potato` block here plus
  `dexter_mandark_deploy.pub` in potato's `authorized_keys`), or accept that
  this tier is offline-only and drop the `nightly-batch` skill's paragraph
  saying "real STT-pipeline/audio work on potato IS in scope for an
  unattended run" — it has not been true for any cycle so far, and it is
  what keeps generating a "blocked on potato" section every night.

  *Not claimed:* nothing here says anything about what is or isn't running on
  mandark itself. `setup-mandark-remote-claude-persistence.sh` hardcodes
  `/home/zach/Documents/Projects/crt/bin/...` in its unit files; that path
  does not exist **on dexter**, which is unremarkable since dexter isn't
  mandark. Whether it exists on mandark is unverifiable from here.

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

- **2026-07-25 (sixth cycle, half-answered in the seventh): what should
  `transcribe_remote()` do when the whisper server is unreachable?** It
  returned `""` on any error talking to `CRT_WHISPER_SERVER`, so an
  unreachable whisper server was indistinguishable from a silent room — the
  same shape as `capture_pane()` before `931c0d9` and `send_to_claude()`
  before `9eeccc3`. FOCUS.md's own 2026-07-23 00:40 note flags it and wants a
  local-whisper fallback.
  **The signal half is now done (`ba33791`)**: failure returns `None`, real
  silence still returns `""`, and the console says so on the tube and on the
  pane instead of going quiet. That half needed no decision — it is decidable
  from the code.
  **The fallback half is still open and still Zach's call.** When mandark is
  unreachable, should potato fall back to local `whisper-cli` (measured at
  ~1x realtime on a Pi 3B+ — a 6s utterance costs ~6s, and it costs that
  while capture is stalled, see `106dcbc`), or just report the outage and
  drop the utterance? The measurement now exists to make it a real choice
  rather than a guess.

- **2026-07-25 (seventh cycle): `bin/crt-stt-stream.py` carries its own copy
  of both defects fixed tonight, and nothing launches it.** It has a private
  `transcribe_remote()`/`transcribe()` pair with the same `return ""`-on-error
  shape (`crt-stt-stream.py:126`/`:157`), and its callers do
  `transcribe(...).split()`, so it cannot simply inherit the `None` fix
  without changing them too. Deliberately left alone: `crt-console.sh` never
  starts it (only `crt-stt-stream-view.sh` mentions it), so patching it would
  be changing code nothing runs, on a night when the same defect was live on
  the boot path. **The decision it needs is whether it should exist at all** —
  it predates the mandark offload and duplicates the engine it was forked
  from. Either retire it (`git log -- bin/crt-stt-stream.py` keeps it) or
  wire it somewhere and give it the same treatment.

- **2026-07-25 (eighth cycle): when speech fails, should the console retry on
  the other output device?** `crt-tts.py`'s `play_wav()` now reports a failed
  aplay instead of returning `True` regardless (`3244250`), and
  `crt-secretary.py`'s `speak()` falls back to putting the words on the tube
  via `crt-think.sh`. Trying the TV speaker when the handset is dead is the
  obvious next move and was deliberately not built: it doubles the latency of
  the failure case, and if ALSA `default` is what is broken it fails twice
  before saying anything. A real behaviour choice, not a code-correctness
  question.

- **2026-07-25 (eighth cycle): is FOCUS.md's 0.1x handset finding still
  supported?** `bin/crt-earcon-loopback-test.py` sent sox's and aplay's exit
  statuses to `/dev/null` until tonight (`f187a45`), so "played, and the mic
  could not hear it" and "never played at all" produced identical output and
  it always reported the first. The 2026-07-23 entry's reading ("this USB
  adapter cannot play and record at once") may well be right — 0.1x is also
  what a working-but-deafened adapter looks like, and the TV path registered
  5.0x in the same session — but the tool could not have established it, and
  the capture-duck work of cycles 3, 4 and `fe46ac1` rests on it. One command
  on potato settles it, and it is written into `AUDIO-DEBUG.md` too:
  `python3 bin/crt-earcon-loopback-test.py handset ; echo "exit $?"` —
  `exit 3` means the measurement never happened, `exit 1` with a ratio near
  0.1 means the finding stands.

- **2026-07-25 (eighth cycle): should `bin/` grow one importable module for
  shared helpers?** `last_line()` — three lines, "the last non-blank line of a
  subprocess's stderr" — now exists in both `crt-stt-solo.py` and
  `crt-earcon-loopback-test.py`, because every script in `bin/` has a hyphen
  in its name and so cannot be imported by another. The duplication is forced
  by the naming convention, and it is the same pressure behind
  ranked-backlog item 1's config sprawl. An underscored `bin/crt_lib.py`
  would fix both; renaming the executables would not (the hyphens are the
  CLI-facing names). Small now, and worth deciding before it is not.

## Pending — for `.claude/FOCUS.md`

- **The "FIRST STEP EVERY CYCLE (2026-07-21): pull from crt-vm before doing
  anything else" section is dead and should be removed.** It instructs every
  cycle to run `bin/crt-sync-vm.sh status` before touching any code. That
  script does not exist in this repo — `bin/crt-sync-vm*`, `bin/crt-vm-*`,
  `bin/dexter-*` and `systemd/crt-vm-*` are all gone (retired with the
  crt-vm→potato move). An instruction headed FIRST STEP EVERY CYCLE that
  names a missing script is the same class of thing as the test-runner
  headers `ad41f5a` removed: it reads as a live gate and is a no-op.

- **Ranked-backlog item 1's concrete claims have been overtaken; only the
  config-consolidation half is still real.** Checked each this cycle:
  - *"delete `bin/dexter-*.py`, `bin/crt-sync-vm*.sh`, `bin/crt-vm-*.sh`,
    `systemd/crt-vm-*`"* — all four globs match nothing. Already done.
  - *"fix the dexter `:8992` default still lurking in
    `crt-tts.py`/`crt-announce.sh`"* — `grep -rn 8992` over the whole repo
    returns nothing. Already done.
  - *"**Real bug found:** port 8993 collides — both
    `crt-remote-claude-bridge.py` and `crt-scanner-feed.py:32` claim it"* —
    `bin/crt-scanner-feed.py` no longer exists; `crt-console.sh:201-204`
    records that the dexter→8993 scanner listener was removed for exactly
    this collision. Already resolved.
  - Still real: **one config source**. 8993 is typed into six files under
    three different env var names (`CRT_MANDARK_PORT`,
    `CRT_CLAUDE_REMOTE_PORT`, `CRT_REMOTE_BRIDGE_PORT`) and 8991 into five.
    The names are not interchangeable — they are genuinely different roles
    (listen / dial / probe-default) — so this is a consolidation job, not a
    rename, and it wants a design decision about which of the three is
    canonical before anything is rewired. Flagged rather than done: a config
    module that half the boot path doesn't read would be worse than the
    sprawl.

- **Ranked-backlog item 5c (test-coverage gaps) needs one line added:** the
  gap was not only "files with no test" but "tests the suite does not run".
  `run_tests.sh` now has a manifest check enforcing both directions
  (`ad41f5a`), so the *class* is closed mechanically; what remains under 5c is
  still the genuinely-missing coverage it already names (`crt-monologue.py` has
  `test_monologue_py.py` now; `crt-stt-solo.py` has helper/gate/device/duck
  tests but still no test of `main()`'s loop as a whole beyond the
  duck end-to-end pair).
