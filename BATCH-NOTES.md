# BATCH-NOTES.md — the nightly-batch tier's own staging file

**What this is.** The unattended nightly-batch tier (the disposable clone on
mandark, see `DEVELOPMENT-WORKFLOW.md`'s three-tier model) cannot write to
`.claude/`. Every write to `.claude/QUESTIONS.md` and `.claude/FOCUS.md` from
this tier has been refused as a sensitive file on **twelve consecutive
cycles** (2026-07-24, and eleven times on 2026-07-25). The `nightly-batch` skill
nonetheless instructs this tier to keep `.claude/FOCUS.md` current and to
append open questions to `.claude/QUESTIONS.md`, so that instruction has been
unsatisfiable for twelve cycles running and the questions have only ever
reached Zach through `~/reports/crt/LATEST.md`. Tested directly again each
cycle rather than assumed -- most recently the fifteenth cycle, 2026-07-25,
by attempting a real append to `.claude/QUESTIONS.md` and being refused.

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

## Answered by Zach — folded into the code, kept here for the record

- **2026-07-25 (asked in the twelfth cycle, answered same day): does the arm
  window's ceiling belong to a conversation, or to a wake?** **To a wake.**
  Zach's reply, inline on `~/reports/crt/LATEST.md`, in full: *"Always starts
  a FRESH session, including when one is already open — saying the wake word
  again is deliberate, so it resets the `ARM_MAX_SECS` ceiling rather than
  being swallowed by the conversation already in progress."* So `a9e899b` is
  confirmed behaviour, not a judgement call awaiting an ear. Recorded where
  it is load-bearing rather than only here: `ArmState.arm()`'s docstring in
  `bin/crt-wake-arm.py` now carries his words and an explicit instruction not
  to collapse the re-wake branch of `consume_arm_with_followup()` back into a
  plain slide, and `tests/test_wake_rearm_ceiling.py` cites the confirmation
  in its header. **Still open, and NOT answered by this:** whether
  `CRT_WAKE_ARM_SECS`/`CRT_WAKE_ARM_MAX_SECS` (12s/60s) are the right numbers
  by ear in this room. That is a tuning question, still live-only.
  **Re-affirmed verbatim** on the thirteenth cycle's report (2026-07-25) --
  same wording, nothing new to fold in; `c48ef11` already carries it.

## Pending — for `.claude/QUESTIONS.md`

- **2026-07-25 (fifteenth cycle): the idle face cannot show idle-bait, for
  exactly the reason it was eating scans.** Tonight's fix closed the funnel's
  scan link on the idle-lean layout (`0fc83a6`, `967af9c`). The link BEFORE
  it is still open and cannot be closed from here, because the answer is a
  design decision, not a bug fix. `bin/crt-book-idle-bait.py` pops its book
  quotes into `~/.crt/thoughts.log`, which is rendered by window 1 (`mono`)
  — and the idle-lean layout never displays window 1. So on potato the
  console's whole "pick up a book and scan it" invitation, the first step of
  BOOK-GAME.md's funnel, is being written to a screen nobody is looking at,
  while the tube shows a potato captioned "say 'potato' to wake me". Three
  honest options: (a) the screensaver renders bait itself — it already has a
  caption line, and a rotating one is a small change to a file that has no
  database in it, (b) the idle-lean layout selects `mono` rather than the
  screensaver as its idle face, retiring the potato art from the boot path,
  or (c) idle-bait stays a window-1 feature and the potato is simply the
  idle face on potato. This is a persona call as much as a wiring one.

- **2026-07-25 (fifteenth cycle): when a Claude exchange goes idle, should
  the tube return to `book` or to the idle face?**
  `bin/crt-window-switcher.py` returns focus from `mono` to `book`, full
  stop — written when `book` WAS the boot default and there was no other
  candidate. In the idle-lean layout that means one conversation permanently
  retires the screensaver: the tube sits on the book window's shelf screen
  until the next scan happens and times out. Tonight's `CRT_IDLE_FACE_WINDOW`
  gives the switcher a well-defined answer to point at if you want it
  (one line, same env var), but which screen "resting" means is yours to
  say, and the two are not obviously different in value — the shelf screen
  is an idle face too, and was the only one for most of this project's life.

- **2026-07-25 (fifteenth cycle): should the screensaver forward scans, or
  should the idle-lean layout stop taking the keystrokes in the first
  place?** Tonight took the first road: the scanner types into whichever
  window has focus, the idle-lean layout gives focus to the screensaver, so
  the screensaver hands what it catches to `scanner.log` and the `book`
  window brings itself forward. The other road is one line — keep selecting
  `book` at boot in both layouts, and let the screensaver be a window you
  reach deliberately. That costs the idle face its boot-default status,
  which was a deliberate 2026-07-23 decision, so I did not quietly undo it.
  If the potato-on-boot matters less than the simplicity, say so and this
  becomes a two-line revert of `0fc83a6`'s wiring (the forwarding code is
  still correct for any future window that holds focus).

- **2026-07-25 (fifteenth cycle): how long should a question hold the tube?**
  `CRT_BOOK_CONSOLE_IDLE_SECS` (default 20) used to decide only what the
  `book` window painted on itself. Since tonight it also decides how long
  the scan borrows the whole screen from the idle face, which is a different
  question with a different right answer — 20s of question-then-shelf may be
  too short to read a question and speak an answer, and the answer window
  (`CRT_BOOK_ANSWER_WINDOW_SECS`, also 20) is counted from the scan, not
  from when the question appeared. Both are by-eye numbers now. Not guessed
  at here.

- **2026-07-25 (fourteenth cycle): should `stt.log` say what the engine DID
  with a line?** `2d823cc` stopped the Book Game grading an utterance that
  carries the wake word, because that utterance is a request to Claude, not
  a trivia answer. The other half is not closeable from here. With
  `CRT_WAKE_ARM_ENABLED=1` — which potato's `~/.bash_profile` actually sets
  — a follow-up spoken inside the arm window carries **no wake word by
  design**, and from `crt-book-answer-listen.py` it is indistinguishable
  from an answer. The arm state lives in `crt-stt-solo.py`'s memory and
  nothing writes it down. There is a near-miss already: `emit()` writes
  `[you] <text>` to `thoughts.log` for every utterance it routes, including
  arm follow-ups — but it writes `stt.log` *first*, so a reader tailing
  `stt.log` can see the line before the marker exists. Closing this properly
  means the engine recording its decision **before** or **inside** the
  `stt.log` write, which changes a log format three programs read. That is
  yours: either a routed-marker in `stt.log` itself, or a small state file
  the grader can consult, or accept that a follow-up mid-round gets graded.

- **2026-07-25 (fourteenth cycle): a mishear candidate still guesses that
  the speaker was RIGHT.** `85e1dfc` cleaned the input to
  `generate_candidate_fixups()`: `mismatches` now holds only transcriptions
  that matched none of the offered options, instead of every wrong guess.
  What it did not touch is the mapping. A row's `expected` is the CORRECT
  option, so a mishear of a *wrong* answer — someone says "nonfiction", it
  comes out "nonfriction" — becomes the candidate `nonfriction -> fiction`,
  a mapping to a word they never said. Two occurrences and
  `crt-stt-training-merge.py` merges it live at confidence `auto`. The
  honest options are (a) only generate a candidate when the heard string is
  a near-miss of exactly one option (edit distance, which this project has
  no fuzzy matcher for yet and deliberately grades "close to literal"),
  (b) log both options and let a human pick during a calibration round, or
  (c) leave it and rely on `auto` never being treated as confirmed — which
  is only safe if the tenth cycle's question 7 below is answered "no".

- **2026-07-25 (fourteenth cycle): what should happen to training rows
  written before `85e1dfc`?** Their `correct_stt` means "matched the correct
  answer"; rows after it mean "was one of the offered options". Nothing in
  the row distinguishes the two, so any mixed file quietly averages two
  different measurements. Every STATUS note in this subsystem says no real
  scan has ever been graded, which would make this moot — but potato is
  unreachable from this tier and that is unverified for the live file. One
  command settles it: `ssh potato "wc -l ~/.crt/book-game-training.jsonl"`.
  If it is non-empty, the cheap fix is to move it aside rather than migrate
  it; the rows predate any real calibration anyway.

- **2026-07-25 (thirteenth cycle): should a wrong trivia answer get a second
  try?** `2776f99` made a scan open ONE graded round rather than a 20-second
  grading window, because everything said inside that window was being graded
  against the same question and written to `book-game-training.jsonl`. The
  round therefore closes on the FIRST graded utterance, right or wrong. For a
  wrong answer that felt clearly right to me: `format_result_line()` has
  already announced *"nope, it was fiction"* on the tube, so a retry would be
  grading someone reading the answer off the screen — worse than useless as
  STT training data, since the whole value of a row is that `expected` is what
  the person actually tried to say. But a game that says "nope" and moves on
  is a different feel from one that lets you have another go, and the feel is
  yours. If you want retries, the shape is a retry budget on the round rather
  than reopening it wholesale, and the announcement would have to stop
  revealing the answer until the budget is spent.

- **2026-07-25 (thirteenth cycle): `_now_iso()`'s one-second resolution now
  decides a round, in one narrow case.** A round is closed when
  `last_answered >= last_scanned`, both stamped by `_now_iso()`
  (`'%Y-%m-%dT%H:%M:%S'`, no sub-second field). So re-scanning a book in the
  *same second* as answering it leaves the two equal and the re-scan does not
  re-open the round. I chose `>=` over `>` deliberately: the other direction
  means anyone who answers within the same second as the scan gets the
  original bug back, and a missed grade is recoverable by scanning again
  while a mislabelled training row is not. Worth knowing rather than acting
  on — the fix, if it ever matters, is sub-second timestamps throughout
  `books.db`, not a comparison tweak.

- **2026-07-25 (twelfth cycle): should re-scanning a book ask the same
  question again, or a different one?** `bb2bd8e` made a re-scanned book
  answerable at all — it was not, see that commit. It deliberately kept
  `register_book`'s cache, so the second scan puts the SAME question on the
  tube as the first. For STT training that is arguably the ideal: the same
  expected string, spoken again by the same person in the same room, is a
  repeated measurement rather than a new one. For a game it is repetitive.
  `questions_json` is already a list and rotating through it is a small
  change, so this is not a cost question — it is a question about what the
  Book Game is primarily for, which is yours to answer.

- **2026-07-25 (eleventh cycle): may a background window keep running after
  it has skipped an iteration, or should it eventually give up loudly?**
  `bin/crt_loop_guard.py` (`442562b`) makes `book`, `bookidle`, `bookanswer`
  and `stttrain` survive one raising iteration and report it on window 1.
  It cannot tell a transient hiccup from a fault that will now repeat
  forever: it reports the first occurrence of each distinct cause, reports
  a recovery with a count if one comes, and keeps going either way. The
  alternative posture is a give-up threshold — N consecutive failures, then
  stop and say so loudly. I chose to keep running, because a window that is
  up and complaining is strictly better than the bash prompt this replaces,
  and because a loop that stops on its own is the failure the guard exists
  to prevent. But it is a real call, and it is the same seam as ranked
  item 8's supervisor: a give-up threshold only makes sense once something
  outside the process is watching for it.

- **2026-07-25 (eleventh cycle): `bin/` now has two underscored modules —
  is that the answer to the eighth cycle's shared-helper question, or
  should it be one?** `crt_loop_guard.py` and `crt_config.py` landed this
  cycle (`442562b`, `24a94ac`) because the alternative was copy-pasting a
  guard into four files and an env-var lookup into three, which is exactly
  the drift that produced the `CRT_STT_FIXUPS` / `CRT_STT_FIXUPS_PATH`
  split in the first place. Both are loaded by `spec_from_file_location`
  rather than plain `import`, so they work regardless of `sys.path` — the
  same idiom the scripts already used for each other. The open question is
  the shape, not the principle: one `crt_lib.py` holding everything shared,
  or one small module per concern as now. See the eighth-cycle entry below,
  which asked this before there was anything to point at.

- **2026-07-25 (tenth cycle): may an `auto`-confidence fixup open the wake
  gate without a human ever seeing it?** The gate now re-reads
  `bin/stt-fixups.json` while the engine runs (`0ccdf13`) — that is what
  makes a calibration-game alias work the moment it is saved instead of at
  the next reboot. It also means an entry merged unattended by the
  `stttrain` window (`crt-stt-training-merge.py`, `confidence: "auto"`) goes
  live without a restart, where before it waited for one. Reaching it today
  needs a Book Game trivia answer that is literally the wake word, so it is
  close to unreachable in practice — but `addressed_to_console()` ignores
  the confidence tier entirely, and those tiers exist precisely so an
  unverified entry can be told from a confirmed one. Either the gate should
  require `confidence in {confirmed, candidate}` for wake purposes, or the
  tier is documentation-only and should say so. Not decided unilaterally:
  it changes which words wake the console.

- **2026-07-25 (tenth cycle): should a hand-visit to window 1 ever time
  out?** `crt-window-switcher.py` used to bounce you off `mono` back to
  `book` within one poll whenever the last Claude exchange was older than
  `CRT_WINDOW_SWITCHER_IDLE_SECS`, which after the first return is always
  — so window 1 could not be read by hand at all. Fixed in `016d816` by
  treating an exchange as spent once it has been returned from. The choice
  inside that fix: a deliberate visit now lasts until *you* leave, with no
  timer at all. The alternative would be to re-arm the idle timer from the
  moment you arrive, so the tube drifts back to the book game after 30
  quiet seconds. I picked "stay until you leave" because the surprise
  direction matters — a screen that will not stay put is worse than one
  that waits — but it is a feel question, and the console's idle face is
  the book game by design.

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
