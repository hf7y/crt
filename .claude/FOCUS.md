## Stability milestone

**Current:** the core voice loop (wake word → STT → Claude reply → spoken response, with a sticky follow-up window and no handset play-while-capture interference) is reliable on real potato hardware, AND the Book Game funnel (idle-bait → scan → question → spoken answer → STT-training log) runs end-to-end on potato's current layout — status: in-progress
Done when:
- [ ] sticky-conversation-window / arm-window state machine — **code done** (`consume_arm_with_followup()`/`check_arm_timeout()` implemented in `bin/crt-wake-arm.py`, wired into `crt-stt-solo.py`, tested in `tests/test_wake_arm.py`, commit `ede80b5`, 2026-07-23) — **2026-07-28 live-verify pass: `CRT_WAKE_ARM_ENABLED=1` is already live in potato's `~/.bash_profile`** (set some prior session, not this one — default in code is still OFF, this is a per-host override). **Tried live, no clean result yet.** Multiple real attempts at a wake-then-follow-up-without-repeating-the-word: every attempt that actually omitted "potato" arrived 16s+ after its preceding wake (cross-checked against `potato-claude`'s pane — neither reached the brain, both gated out as "no wake word") — past the 12s `CRT_WAKE_ARM_SECS` window. Given tonight's confirmed potato↔mandark transcription lag (see the network-flakiness QUESTIONS.md entry), it's unclear how much of that 16s+ gap is real speaking pace vs. queueing lag eating into the window before it's even logged. **Real open question, not just an untested checkbox:** is 12s tight for natural pacing, or is the window's clock starting from the wrong reference point given lag? Needs a retry on a quiet network, or the window's timing reference reconsidered.
- [x] handset play-while-capture bug — **code done AND live-verified 2026-07-28.** Re-ran `crt-earcon-loopback-test.py handset` live on potato, both against raw `plughw:1,0` and against the dmix/dsnoop-shared `crtmic`/`crthandset` devices from `bin/setup-potato-audio-sharing.sh` (deployed to `~/.asoundrc` some prior session, unused by the console until now): **same result either way — tone ratio 0.1x, NOT DETECTED.** This confirms the 2026-07-23 finding is real hardware behavior, not a fluke, and that dmix/dsnoop sharing does NOT fix it (it's not a device-contention problem, it's the USB adapter physically not doing both at once) — the CTL-file mute/duck approach already built (`crt-tts.py`/`crt-earcon.sh`, `CRT_CTL_FILE` export bug fixed commit `fe46ac1`) is the correct and necessary fix, confirmed by measurement, not just by design reasoning. **Duck confirmed live end-to-end**: `~/.crt/ctl` shows 24 clean mute/unmute cycles from tonight's real earcon fires (both wake-side and reply-side, both confirmed audible by ear separately) — capture pauses and resumes around every playback with no stuck state. Done.
- [x] capture device resolved by NAME — **live-verified 2026-07-28.** Ran `resolve_capture_device_by_name()` against potato's real `arecord -l` output live: resolves to `plughw:1,0`, matching the hard-pinned `CRT_AUDIO_DEV` default exactly. Done.
- [ ] Book Game funnel re-verified end-to-end — **offline half still passing** (`tests/test_console_book_game_layout.sh`, re-run 2026-07-28, all PASS). Live half genuinely needs a human hand on the real barcode scanner — confirmed 2026-07-28 the `book` tmux window is live and correctly prompting ("0 book(s) registered — scan o[ne]"), but nothing remote can produce a real scan event. Ranked-backlog item 4, unchanged: needs Zach with a physical book.

  **2026-07-28 (realisateur, live-verify pass from within crt, Zach-directed):** ran the above against real potato hardware over SSH (`vkv_deploy_key`). One operational finding worth keeping: the live `stt` tmux window's process still had its cwd pointed at `~/crt.bak-2026-07-28` (the pre-reconciliation orphan repo, renamed not deleted by the 2026-07-27 `da45280` swap) — a process started before a `~/crt` swap keeps its old cwd even though the path now points somewhere else. Paused it (`C-c`), restarted it fresh from `~/crt/bin` with its exact `crt-console.sh` launch command; confirmed clean restart, no data lost. **Any tmux window opened before a future repo swap needs a manual restart to actually pick up the new tree — a plain path rename doesn't do it.** Worth a note in `POTATO.md`'s deploy section if this recurs.

  **2026-07-28 (realisateur, Zach-directed): reply-capture leaked Claude Code's own TUI chrome into what gets spoken/printed — fixed.** First real remote reply captured end-to-end tonight ("brain's on, screen's warm...") came back as `❯ trying to reach your brain... ● » yeah, i'm right here... ✻ Baked for 2s` — `wait_for_claude_reply()`'s raw-terminal-line diff (its own docstring already called this "a first cut, not a robust terminal parser") had never been exercised against a real reply before. Added `clean_claude_pane_reply()` in `bin/crt-secretary.py` (strips the echoed prompt, box-drawing borders, the bottom status bar, and the spinner line; keeps everything else including multi-line structure), wired into `wait_for_claude_reply()`'s return, regression-tested against tonight's exact captured fixture (`tests/test_clean_claude_pane_reply.py`, 8/8 pass, registered in `run_tests.sh`'s manifest). Deployed to potato via scp, diffed byte-identical against this repo. Not a full terminal parser — still pattern-matching known chrome, same posture as the diff it cleans — but the one shape seen live is now handled and pinned by a test.

  **2026-07-28 (realisateur, Zach-directed): earcon room-alert toggle wired AND audibility CONFIRMED BY EAR.** `crt-earcon.sh` already supported `--device tv` (`plughw:2,0`, HDMI) alongside `handset`, but `crt-secretary.py`'s own `play_earcon()` never passed `--device` at all, silently falling through to the ALSA system default regardless of what `crt-stt-solo.py`'s earcons were routed to. Fixed: both call sites now read the same `CRT_EARCON_DEVICE` env var (default `handset`, unchanged). Set `CRT_EARCON_DEVICE=tv` in potato's `~/.bash_profile` as the room-wide **testing default** (toggle: unset or set back to `handset` to revert) — durable across reboots, not just this session. The loopback-test read (2.9x, below the 8.0x auto-detect threshold) undersold it — **Zach confirmed live by ear that it sounded.** Real topology, corrected in `POTATO.md`: potato's video/audio is HDMI → an RF converter → the CRT, not composite as that doc previously implied (nothing was disconnected; the doc was just silent about HDMI being the thing feeding the converter, which cost real time this session chasing a nonexistent wiring gap). Room-alert-over-HDMI is a real, working, confirmed path. Done.

  **2026-07-28, later same session: "potato has no earcons access" investigated and disproven.** Checked every layer directly: `crt-earcon.sh --device tv` shell trace (`bash -x`) completes clean, `aplay -D plughw:2,0` exits 0; the exact `play_earcon()` function from `bin/crt-stt-solo.py` (not just the shell script) fires without exception, `EARCON_DEVICE` resolves to `tv`; `/proc/<pid>/environ` on the live `stt` process confirms `CRT_EARCON_DEVICE=tv`; `~/.crt/ctl` ends on `mute 0` and `~/.crt/sideband.mute` doesn't exist, so nothing was stuck ducked. Fired `play_earcon("addressed")` directly via that exact code path twice — **Zach confirmed hearing it both times.** No code or config change came out of this: access was never actually broken, this was a false alarm (likely the same live-in-the-room-vs-remote-test attention gap as the mandark-bell mixup a few entries up). Leaving this note so a future session doesn't re-open "earcon access" as if it were still an open question.

  **2026-07-28, later still: the `crt-secretary.py` "thinking" earcon (fires after a real reply is dispatched to Claude, not just on wake) confirmed separately, twice.** Zach's specific report was "potato claude can't find it" — the *reply-side* earcon, not the wake-side one already confirmed above. Ran the real invocation `crt-stt-solo.py`'s `send_to_secretary()` uses (`python3 crt-secretary.py "<text>"`, matching env including `CRT_EARCON_DEVICE=tv`) live, twice, end-to-end through the actual bridge to mandark and back — Zach confirmed hearing the "thinking" tone both times. Both earcon call sites (`crt-stt-solo.py`'s wake-side, `crt-secretary.py`'s reply-side) are now independently, audibly confirmed on real hardware. No code change; another false alarm, same shape as the one above.

  **2026-07-28, later still: real capture crash live during testing — root-caused, fixed, and generalized.** "Potato doesn't wake" traced to `crt-stt-solo.py`'s own process having crashed 1353s earlier (`CAPTURE DIED... USB replug? device grabbed by another reader?`, `arecord: read error: No such device`) — the USB audio device re-enumerated fine (dmesg confirms a clean re-attach) but nothing restarted the python process, so the console was silently deaf until this session noticed over SSH. Zach's direction: make restart "sticky" (persistent-reattempt daemon) and make failure noisy, not silent. Built `bin/crt-stt-supervisor.sh` (new): restarts `crt-stt-solo.py` on any exit, backoff (instant retry first couple times, widening after, capped at 30s, reset after a 60s-healthy run), fires a new `alarm` earcon (`crt-earcon.sh`, deliberately harsh — a documented, acknowledged exception to that file's own "never sound like an alarm" rule, reserved exclusively for this) on every restart. Regression-tested (`tests/test_stt_supervisor.sh`, fakes both `crt-stt-solo.py` and `crt-earcon.sh`, asserts restart-on-crash, one-alarm-per-crash, and that backoff measurably slows retries). Wired into `crt-console.sh`'s `stt` window launch (replaces the direct `crt-stt-solo.py` invocation, same env passed through) and deployed live to potato. Left `bin/crt-capture-watchdog.sh` untouched — VM-era, unverified, and answers a different failure shape (stale-but-alive signal via its own reader, not a fully-exited process).

  **2026-07-28 (realisateur, Zach-directed): wake word was aspirational, not real — fixed.** `POTATO.md` has always described the wake word as "potato" (pool match). `CRT_WAKE_WORD` defaults to `"claude"` in code (`crt-stt-solo.py`, `crt_wake_gate.py`) and nothing had ever set the env var on potato — every session including this one's own live test was silently gated on "claude." Caught live: `~/.crt/stt.log` shows Zach saying "Potato... trying to wake you, get a sign of life" at 01:53:13 and it never reaching the brain, exactly the mechanism gap. **Fix, not a workaround:** `export CRT_WAKE_WORD=potato` added to potato's `~/.bash_profile` (before the tty1 autoboot `exec`, so it survives a real reboot, not just this session's manual restart), `stt` window restarted to pick it up, confirmed live via `/proc/<pid>/environ`. Policy now matches mechanism. No code changed — the env var plumbing already existed everywhere (`crt-book-answer-listen.py` reads the same var); it was only ever unset.

Ideas beyond this bar are PARKED by default (see realisateur/STABILITY-MILESTONES.md): **dual-tier local+offsite STT** and **Vosk/Sherpa-ONNX keyword-spotting evaluation** (ranked-backlog item 9 — real design ideas, but the core loop above doesn't need them yet); **compute-stick/bare-metal migration** (explicitly excluded from this bar by Zach 2026-07-24 — one deployment target is a separate, later goal, not required for the core loop or Book Game to be reliable); **refactor sweep / config consolidation, docs consolidation, no-brain standalone jobs, interaction streamlining, screensaver CRT-margin depth, calibration-suite promotion** (ranked-backlog items 1, 2, 3, 5, 5b, 6 — real cleanup/polish, not required for the bar); **wake supervisor + dormant wake-judge autonomy** (ranked-backlog items 7/8's *judge* half, and the `CRT_WAKE_JUDGE_ENABLED` flag — the arm-window mechanism itself is IN the active bar above, but turning on autonomous judge-driven tuning is beyond it until the arm window is proven live); **Gemini-before-Claude fallthrough, dexter NPU tooling** (cost/perf optimizations on a loop that isn't reliable yet).

*(Milestone drafted 2026-07-24 via realisateur's `/ideate crt` — revise if it doesn't fit crt's own read of its bar.)*

# crt — focus & backlog

- **2026-07-27 (realisateur, via `/ideate`): potato reachability is confirmed live, not just theoretically fixed — the 4 milestone checkboxes above are unblocked, do the live-verify pass now.** Tonight's own reconciliation session (`da45280`) confirmed potato is still `192.168.0.45` (unchanged — no static-IP change actually landed, that was a stale premise carried into this session), reachable, and `~/crt`'s repo relationship is now a real clone of `origin` (was an orphan tar-deploy history since 2026-07-22). Zach confirmed: run the live-verification pass next — wake-arm live-confirm, handset-duck loopback test, capture-device-by-name against real `arecord -l`, Book Game funnel end-to-end scan — the four items this file's Stability milestone has listed as "code done, needs live-confirm" since 07-24. Vision unchanged (core voice loop + Book Game funnel reliable on potato); this is the milestone's next concrete step, not a new direction. **`steward-survey.sh` will misreport crt as DARK** — it reads only `_paced.conf` (mandark), not `_paced.dexter.conf`, where crt actually runs (`enabled=1`, weight 3, 274 commits/7d as of tonight); a fix for that gap is scheduler's own, not filed again here (see realisateur's own FOCUS.md 2026-07-27 entry and [[feedback_probe_survey_headlines]] for the prior false-DARK incident this would repeat).

- **2026-07-26 (realisateur):** the parked "bibliothecaire" catalog-split
  fork below is RESOLVED — Zach chose the third preserved option, **split
  scope-only**: a wholly separate greenfield project (own repo, own
  scheduler registration, queued for nightly-batch at low weight via
  realisateur's inbox) that never forks crt's scan/grade/STT-log code and
  shares at most `books.db`'s data. It merges the catalog wing with a new
  operations/cybernetics knowledge base seeded from realisateur's
  `UNIVERSE.md` (closed loops, stigmergy, theories of the firm, holons —
  sourced quotes with attribution). The merged project owns the name;
  the unrelated "page 92" idea — which realisateur's 2026-07-26 nightly
  had meanwhile scaffolded as a live project under the contested name —
  gets renamed to `quatre-vingt-douze` as step 0 of the librarian's
  scaffold drop (Zach's call, asked directly), which also resolves the
  fable-review name-collision item further down this file. Nothing moves
  out of crt's tree and nothing here is required for crt's current
  milestone. Full vision + milestone chain: realisateur `.claude/FOCUS.md`
  2026-07-26 entry.

  **New offline-safe backlog item registered with it** (answering this
  file's own QUESTIONS.md note that the offline-safe backlog appears
  exhausted): **[batch] `(waiting: bibliothecaire quotes file)`** — extend
  the idle-bait quote rotation (`pick_idle_quote()` path in
  `bin/crt-book-game.py` / `bin/crt-book-idle-bait.py`, tests in
  `tests/test_book_idle_bait.py`) to ALSO draw from an external
  bibliothecaire-published quotes file when one is present, keeping the
  existing non-API-at-idle-time rule and the `CRT_BOOK_ENTICE_RATE` mix.
  Chosen over a dedicated splash app deliberately — no new tmux
  window/surface (realisateur `UNIVERSE.md` Law 3), quotes surface on the
  book channel's existing idle screen. **Stated park-by-default override:**
  this is not required for the current milestone bar; it's promoted only
  because it feeds the starved offline-safe lane and adds no surface. It
  stays `waiting` (not buildable) until bibliothecaire's first research
  pass actually publishes the file — don't start it on spec.

- **2026-07-24 (realisateur, parked):** split Book Game's library/catalog
  half into its own "bibliothecaire" program — designed to eventually know
  book contents, relationships, citations, further reading (a real
  knowledge graph, not just ISBN→title/author/LCC). Raised via
  `/ideate crt` and explicitly parked by Zach (not split now): the current
  DECLARED milestone above still has the Book Game funnel itself as an
  unmet bar item, and this feature is deliberately embedded in crt as the
  byproduct-first STT-training instrument (see `../BOOK-GAME.md`'s "Why
  this exists") — a 2026-07-22 entry already declined to scaffold this
  same feature as a separate project for the same reason. Revisit once
  the funnel is confirmed live end-to-end on potato; when it is, the
  three options from that session are still open: split now as a new
  scheduler-registered project, park further, or split scope-only (a
  wholly separate greenfield program that never forks crt's existing
  scan/grade/STT-log code, sharing at most `books.db`'s data). See
  realisateur's own `.claude/QUESTIONS.md` for the mirror entry.

- **2026-07-24 16:12 (via `scheduler -i`):** batch run audio tests are outputting to mandark card, not pi

- **2026-07-23 13:41 (via `scheduler -i`):** reduce this to a simple potato game where the user either says or doesn't say potato on prompt, earcon and visual feedback, designed to train the stt. could be the core default on-boot mode with a toggle switch until we get this calibration right

- **2026-07-23 13:40 (via `scheduler -i`):** figure out what's wrong with the text column constraints, problem on mono window and more. suggest 40 column limit but overscan detect idea is better

- **2026-07-23 13:14 (via `scheduler -i`):** establish passwordless sudo on potato with a reminder to turn that off when we get out of this prototyping phase. unnecessary friction right now when there's no security risk (I'm the only user)

- **2026-07-23 13:05 (via `scheduler -i`):** scrape this site for viable potatos (no character encoding problems) and
  swap out potato_small.txt with one or more (for personality)
  https://textart.sh/topic/potato

## PRIORITIZED BATCH BACKLOG (2026-07-23, scheduler-integrated)

How to read this: items are ranked by **value ÷ risk**, offline-safe work
first (the `nightly-batch` skill / disposable-clone tier can do these
unattended — it reads THIS file and is scoped by it). Each item is tagged:

- **[batch]** — offline-safe. Buildable + unit-testable on mandark with no
  potato/live hardware. A nightly-batch cycle can land it, run
  `tests/run_tests.sh`, commit, and push (per CLAUDE.md push permission).
- **[hw]** — needs the physical Pi / mic / handset. Batch tier must NOT
  guess at these: build the offline-safe half, then flag for Zach's live
  session, same posture the rest of this file already uses.

Scheduler integration: the batch runner picks the top unblocked **[batch]**
item, does it end-to-end (code + test + commit + push + note in its
report), then stops — it does not chain into **[hw]** items or flip live
defaults. **[hw]** items surface in the report as "waiting on Zach".

### Landed this session (2026-07-23) — brain-placement / screensaver

The idle-lean architecture Zach asked for is scaffolded + offline-tested;
see `POTATO.md` for the whole picture. Shipped: `bin/crt-mandark.sh`
(on/off/status toggle), `bin/crt-wake-router.py` (remote/local/none
decision brain), `bin/crt-screensaver.py` (renders `potato-small.txt`),
`crt-console.sh` sources `~/.crt/mandark.conf` + `CRT_NO_IDLE_CLAUDE`
layout. **The one remaining live piece is [hw]:** a wake supervisor that
acts on the router's decision (on-demand local-brain spin-up + screensaver↔
brain window swap) — see POTATO.md "remaining live wiring".

### Ranked backlog

1. **[batch] Refactor sweep — kill dead dexter/crt-vm code + config sprawl.**
   Full plan in `REFACTOR-ASSESSMENT.md`. Highest value/lowest risk:
   delete `bin/dexter-*.py`, `bin/crt-sync-vm*.sh`, `bin/crt-vm-*.sh`,
   `systemd/crt-vm-*` (dead on bare-metal potato); fix the dexter `:8992`
   default still lurking in `crt-tts.py`/`crt-announce.sh` (silent-fail
   class, same as the earcon bug); introduce one config source
   (`crt-config.sh` + `crt_config.py`) for the port `8993`, whisper URL,
   and ALSA device now retyped across many files. **Real bug found:** port
   8993 collides — both `crt-remote-claude-bridge.py` and
   `crt-scanner-feed.py:32` claim it. Resolve as part of the config
   consolidation.
2. **[batch] Docs consolidation.** ~37 `.md` files, heavy overlap,
   SESSION-STATE/HANDOFF self-declare superseded. Add `DOCS-INDEX.md` +
   `docs/archive/`, fold design-only docs into one backlog. Low risk,
   makes every future pass faster.
3. **[batch] Pi-without-mandark standalone jobs.** Things the console does
   with NO brain attached at all (the `none` route, or deliberate offline
   mode) — all reuse existing local-only code, no API cost:
   - Screensaver + book-game idle-bait loop as a self-sufficient "attract
     mode" (`crt-book-idle-bait.py` already API-free).
   - `crt-book-game-stats.py export-fixups` on a timer → candidate
     `stt-fixups.json` entries from accumulated training data.
   - Noise-floor / `CRT_VAD_THRESHOLD` calibration from
     `crt-earcon-loopback-test.py`'s ambient-RMS report (no ear needed).
   - Local canned-response cache: pre-answer common utterances from past
     `stt.log`/Claude exchanges so the screen can respond instantly with
     no brain, then let a brain overwrite it later when one is available
     (directly the 2026-07-22 14:11 scheduler note + the 2026-07-20 15:57
     vision line — "canned responses injected before claude responds").
4. **[batch] Book Game reboot audit.** The funnel (idle-bait→scan→question→
   spoken answer→STT training) is fully built but was disrupted by the
   VM→potato move and the brain-off-box change. Verify each window
   (`book`/`bookidle`/`bookanswer`/`windowswitch`) still composes on
   potato's current layout; the full integration test
   (`test_book_game_integration.py`) is the offline half — re-run + extend
   it to cover the no-idle-Claude layout. Live scan re-test is [hw].
5. **[batch] Interface / interaction streamlining.**
   - Single wake vocabulary source: fold the wake-word/pool constants
     scattered across `crt-stt-solo.py`/`crt-wake-pool.py`/gate logic into
     one place (ties to item 1's config work).
   - Reduce `crt-console.sh`'s ~10 always-on windows: make the Book Game
     windows and `stttrain` lazy/on-demand (RAM lever on a 1GB Pi — see
     `REFACTOR-ASSESSMENT.md` #5).
   - "Grey partial → white final" reply streaming: the `on_partial` seam
     already exists in `crt-secretary.py`; build the real grey/white
     overwrite (2026-07-23 07:15 note has the foothold).
5b. **[batch]+[hw] Potato screensaver: CRT-margin-correct rendering (DEEP
   WORK, filed 2026-07-23).** Quick fix already shipped (the art was
   centering for 80 cols before the tmux client attached, so lines wrapped
   on the 40-col tube -- now re-reads size every frame + CRT_COLS/ROWS
   pinned from crt-console.sh + clamps so no line exceeds width;
   regression-tested in test_screensaver.py). Remaining depth:
   - **Consume the overscan safe-margin** (`~/.crt/display.conf`, the same
     one crt-pager.py/crt-monologue.sh already honor) so the potato
     centers inside the *visible* safe area, not raw 40 cols -- at pad 5
     the edges may still clip on a real tube. Offline: wire the margin +
     test the math. [hw]: confirm by eye on the tube.
   - **Resolve `potato_large.txt`**: byte-identical dup of
     `potato-small.txt`, inconsistent naming (hyphen vs underscore),
     referenced by nothing. Either make it a genuinely larger/detailed
     awake-screen variant or delete it (Zach's art call -- see POTATO.md).
   - Consider an awake/listening frame distinct from the sleeping potato
     (the old crt-screensaver.py had a LISTENING/zzz pair) so the screen
     reflects wake state once the wake supervisor (item 7) lands.
5c. **[batch] Test-coverage gaps found during the 2026-07-23 tidy.**
   `crt-monologue.py` has NO direct python test (run_tests.sh referenced a
   never-written `test_monologue_py.py` -- now guarded, but the test
   itself should be written). `crt-stt-solo.py` -- the single most
   critical process -- also has no direct test (REFACTOR-ASSESSMENT.md #6).
6. **[batch] Calibration tests as first-class, non-interactive checks.**
   Promote the acoustic-loopback + noise-floor tools into a
   `crt-calibrate` suite that emits pass/fail + numbers (not just
   exit-0), so silent-audio regressions (the earcon-bug class) get caught
   mechanically. Live re-run on potato is [hw].
7. **[batch] Handset 3-pin switch: write up the design options (filed
   2026-07-24, routed here after first being mis-filed in scheduler's
   BLOCKERS.md — that file is human-only blockers, not a work queue this
   project's batch reads, so it never would have surfaced otherwise).**
   The handset's 3-pin switch is now printed and physically functional
   (see `cad/HANDSET-MEASUREMENTS.md`); the open question is how it gets
   wired up in software/hardware — hard-kill audio, software mute on
   switch-close, or a Pi GPIO signal into existing logic. Deliverable: a
   short design-options doc (tradeoffs, not a recommendation only —
   Zach decides), flagged-status style like `RFP-GALLERY.md`'s `## Status`
   section. **First check whether this is the same physical switch
   `HOOKSWITCH.md` already specs** (same on/off-hook shape, has debounce
   logic + a "Future states" section already) before assuming it's a
   distinct mechanism — don't duplicate that doc if it's the same switch.
   No hardware access needed for the writeup itself.
8. **[hw] Wake supervisor** (POTATO.md remaining-wiring #1) — on-demand
   local-brain spin-up + screensaver↔brain swap. Offline half: the
   decision + a dry-run harness (done via `crt-wake-router.py`). Live
   spin-up/teardown + RAM/whisper readiness gating needs the Pi.
9. **[hw] Sticky wake window / dormant wake-judge wiring** — `crt-wake-arm.py`
   exists (opt-in, `CRT_WAKE_ARM_ENABLED`); needs live tuning of the
   arm-window duration by ear. See the 2026-07-23 08:00 entry below.
10. **[hw] Streaming STT (Vosk/Sherpa-ONNX) for wake-spotting** — whisper
   is the wrong tool for instant wake on this Pi (measured). See the
   2026-07-23 07:45 / 09:25 entries below for the real numbers.

---

## CURRENT TOP PRIORITY (2026-07-23 evening, before a context reset) --
## Claude-on-mandark is LIVE, verify it stays that way

1. Run `bin/setup-mandark-remote-claude-persistence.sh` on mandark (needs
   sudo password) so the bridge+tunnel survive a reboot -- still ad-hoc
   `nohup` processes as of this writing.
2. Keep live-testing real conversations through it (see
   `.claude/SESSION-STATE.md`'s LATEST section for the full picture) --
   watch specifically for tunnel drops, bridge restarts losing state, and
   whether `CLAUDE_IDLE_SECS`'s idle-detection timing holds up over the
   network (should be negligible on LAN, unverified over a longer
   session).
3. Everything else below this is real but secondary to confirming this
   new architecture is actually solid.

- **2026-07-23 18:00 (cleanup flags from the mandark-Claude/bridge
  work):**
  - Port `8993` is hardcoded in THREE places with no single source of
    truth: `bin/crt-remote-claude-bridge.py`'s default, both systemd
    unit files in `bin/setup-mandark-remote-claude-persistence.sh`, and
    `CRT_CLAUDE_REMOTE_PORT` in `crt-console.sh`'s stt launch line. If
    this port ever needs to change, all three need updating together --
    worth a shared config source (env file, or one constant imported by
    all three) if this setup survives past the prototype stage.
  - `setup-mandark-remote-claude-persistence.sh` kills the ad-hoc
    `nohup` bridge/tunnel processes by hardcoded PID (756846/756877) --
    scaffolding for this one-time transition, not a pattern to copy for
    future setup scripts (harmless no-op if those exact PIDs are already
    gone, but worth removing the dead kill lines once this has actually
    been run).
  - No log rotation/size cap on the bridge server's own stdout
    (`crt-remote-claude-bridge.service`'s journal) or the tunnel's --
    fine for now, worth checking after this has run for a while.
  - Testing live now (2026-07-23): potato's `stt` window escalates to
    Claude running on mandark via this bridge+tunnel instead of a local
    tmux pane. Watch for real failure modes over the next few real
    conversations: tunnel drop mid-conversation, bridge server restart
    losing in-flight state, `wait_for_claude_reply()`'s idle-detection
    timing against network-added latency (should be small on LAN, but
    unverified over a longer live session).

- **2026-07-23 09:30 (MAXUTT/TRAIL review, recommendation only -- not
  changed):** per the 2026-07-23 finding that continuous speech with no
  real pause rides the full `CRT_VAD_MAX` (20s) hard cap before an
  utterance even gets cut, reviewed both constants
  (`bin/crt-stt-solo.py`): `CRT_VAD_TRAIL` (0.8s silence-to-cutoff) seems
  reasonable as-is -- it's not what caused tonight's stuck-utterance
  case, that was purely "no pause happened at all." `CRT_VAD_MAX=20`
  is the one worth a human ear-tuning session: lowering it (e.g. to
  8-10s) would force more frequent chunking during continuous speech at
  the cost of possibly cutting a genuinely long single thought
  mid-sentence. NOT changed here -- this is exactly a "live session
  confirms it feels right" tuning call, not a code-correctness fix, same
  posture this project applies everywhere else to default-behavior
  changes. Flagging as a concrete open question for Zach rather than
  guessing at a number unattended.

- **2026-07-23 09:25 (nightly-batch finding, recalibrates the earlier
  Vosk/Sherpa-ONNX recommendation):** potato is a **Raspberry Pi 3 Model
  B+** (`cat /proc/cpuinfo` confirmed) -- quad-core Cortex-A53 @1.4GHz,
  905MB total RAM, only 183MB free with active swap use and load average
  1.36 at the time of testing. This is meaningfully weaker than the
  Pi 4/5-class hardware most Vosk/whisper.cpp benchmarks assume, and
  under real memory pressure from everything else already running
  (crt-stt-solo.py, tmux, etc). Installed `vosk` (venv
  `~/.venvs/crt-vosk` on potato, real aarch64/cp313 wheel, works) and its
  small English model, tested live: a 1.5s clip took until t+1.53s for
  the FIRST partial result, and 2.65s wall-clock for the final result --
  i.e. Vosk on THIS specific hardware right now is not dramatically
  faster than realtime either, contrary to the "<100ms, built for weak
  ARM hardware" framing in the earlier research note. Streaming partial
  results (available continuously, not gated on a full utterance/fixed
  encode window like whisper.cpp) is still Vosk's real structural
  advantage over the batch-VAD approach -- that reasoning still holds --
  but the earlier assumption that it'd feel snappy specifically ON THIS
  BOX needs re-testing once the system isn't under memory pressure (or
  after trimming what else runs on potato) before committing design
  decisions to it. Test scripts left in
  `~/vosk-models/vosk_test.py`/`vosk_test_short.py` on potato for re-use.
  Worth considering as a separate, orthogonal question: is potato's own
  hardware (a Pi 3B+) the right long-term choice at all, independent of
  which STT approach it runs -- flagging for a human decision, not
  something to guess at unattended.

## TOP PRIORITY for tonight's/next unattended pass (2026-07-23 08:20) --
## calibration/testing features first, per Zach's explicit instruction,
## ahead of the bigger dormant-wake-judge-wiring item further down.

1. **Confirm/fix the handset play-while-capture finding below** (real
   loopback-test evidence, needs either a code fix + re-test, or live
   human confirmation next time Zach is on the handset -- whichever
   this session/pass can actually do).
2. **Live-test `bin/crt-calibration-game.py`** on potato (tmux window
   9, "game") now that its continuous-tailing bug is fixed -- this
   was fixed but never actually re-played live end-to-end tonight.
3. Everything else in this file's other 2026-07-23 entries, roughly in
   the order they appear (dormant wake-judge wiring is the biggest/
   last item, intentionally not first).

**Acoustic loopback test built and run live tonight**
(`bin/crt-earcon-loopback-test.py`) -- real, fairly strong evidence of a
NEW bug, separate from the earlier dexter-bridge routing bug (which IS
fixed): the handset output device (`plughw:1,0`) is the SAME USB
hardware as the active mic capture device, and a tone played on it while
capture is running showed almost no signal in the recording (0.1x above
baseline) -- backwards from what physical proximity would predict, and
much worse than the TV path (a separate physical device, 5.0x above
baseline, itself below my test's conservative 8x "detected" threshold
but at least in the right direction). Likely explanation: this USB
audio adapter can't reliably play+record simultaneously (a real hardware/
driver limitation, not a software routing bug this time) -- earlier
tonight's successful "yes, heard both in order" confirmation of the
handset path happened while capture was ACCIDENTALLY DEAD (the
`plughw:0,0` bug, fixed later the same session), so there was no
device contention at that time to reveal this. **Needs**: either (a) a
code fix -- briefly duck/pause the capture arecord process during a
handset earcon, same pattern as the existing sideband-mute duck, then
re-run `crt-earcon-loopback-test.py handset` to confirm it fixes the
measured ratio, or (b) failing a code fix, live human confirmation
(the tool's own measurement, while informative, is not 100% proof --
Zach's ear is the ground truth) next time he's on the handset. The tool
itself is genuinely reusable going forward -- also reports the room's
noise floor (peak/rms) each run, directly useful for retuning
`CRT_VAD_THRESHOLD` without a by-ear session.

## Nightly-batch / unattended-pass access to potato, confirmed tonight

The nightly-batch runner operates as the persistent `zach` account on
mandark (same `$HOME` FOCUS.md's crt-vm section already documents the
`crt_vm_pull` SSH key living in, "NOT the disposable clone, so they
survive the `git reset --hard` this repo's clone gets every cycle") --
the SAME account this session added `Host potato` to in
`~/.ssh/config` tonight (key auth, no password). Confirmed: `whoami` /
`$HOME` in this session match `zach`/`/home/zach`, the persistent
account crt-vm's own access already relies on. **This means `ssh potato`
should already work for an unattended pass without further setup** --
but this has NOT been end-to-end verified by actually triggering a real
nightly-batch run and watching it use `ssh potato` successfully. If a
pass starts and `ssh potato` fails (host key, auth, connection), don't
spend the whole cycle debugging it -- note it in the report and continue
with whatever else is in scope, same policy the crt-vm section below
already established for that host.

- **2026-07-23 08:00 (built tonight, live on potato):** `bin/crt-calibration-game.py`
  -- the "potato game" from earlier tonight's idea, built as a real
  interactive script rather than a background service. Reuses
  `crt-wake-pool.py`'s `closest_pool_word()`/`difflib` scoring (which its
  own header comment says was built "2026-07-21, calibration-game pass"
  -- this game is what that comment was anticipating). Tails
  `~/.crt/stt.log` live, splashes recognized words around ASCII art
  scored/colored by similarity to a target word, offers to save
  recurring near-misses into `stt-fixups.json` as confirmed aliases, plus
  an earcon device-confirmation round. Running in tmux window 9 ("game")
  on potato. Deliberately does NOT touch the live capture process --
  passive `stt.log` reader only, same posture as
  `crt-book-answer-listen.py`.
- **2026-07-23 08:00 (NEXT SESSION / overnight pass -- concrete spec, not
  vague):** wire the dormant autonomous wake-judge system into potato's
  live pipeline. Everything for this already exists except the actual
  state machine:
  - `bin/crt-wake-pool.py` (fuzzy/exact wake-pool matching, real code,
    tested) and `bin/crt-wake-judge.py` (autonomous `claude -p` judge,
    rate-limited, real code, tested) both exist and work in isolation.
  - `WAKE-TUNING-STATE.md` has a genuinely rich judgment log (dozens of
    real dated entries from 2026-07-21) proving this ran live at some
    point -- almost certainly lost in the VM->potato hardware migration,
    same pattern as other features that silently regressed in that move.
  - **What's actually missing**: an arm-window state machine in
    `crt-stt-solo.py` itself. `consume_arm_with_followup()` and
    `check_arm_timeout()` are referenced by name in `crt-wake-judge.py`'s
    prompt-building code and in the judgment log's own vocabulary, but
    grep confirms **zero implementations exist anywhere in bin/*.py** --
    only comments/docs reference them. The missing piece: on a wake-pool
    match (not just the exact-wake-word gate `addressed_to_console`
    already handles), arm a short window; if a real follow-up utterance
    arrives before it closes, dispatch it and call
    `crt-wake-judge.py --outcome consumed`; if it times out, call with
    `--outcome timeout-with-leftover` or `--outcome timeout-empty`
    depending on whether anything was pending. This is also the natural
    real implementation of the OTHER still-open gap from earlier tonight
    (07:23 note): the sticky-conversation-window idea and this arm-window
    mechanism are the same feature, not two separate ones -- build once.
  - Once wired, this closes the loop the user asked for tonight
    ("Claude snoops around after silence, finds logs of failed wake
    attempts, tries to repair the cause") -- the judge already knows how
    to do exactly that, it just has no live trigger calling it.

- **2026-07-23 07:20 (design constraint for the "resolve capture device
  by name" fix filed above):** keep BOTH paths available, don't replace
  the hardcoded ALSA index with name-resolution outright -- resolve by
  name (parse `arecord -l` for "KT USB Audio" or similar) as the
  default/preferred path, but keep `CRT_AUDIO_DEV` (or an equivalent
  explicit override) working as a hard override for when name-matching
  is ambiguous (two identical USB adapters plugged in, a renamed/generic
  device string, etc) or when name-resolution itself breaks. Same
  reasoning as `stt-fixups.json`'s tiered confidence levels elsewhere in
  this project -- never remove the manual escape hatch when adding an
  automatic path.
- **2026-07-23 07:22 (test/diagnostic idea, not yet built):** can the
  mic hear the earcons? i.e. an acoustic loopback self-test -- play a
  known earcon (or a plain fixed-frequency tone) through the actual
  output device, simultaneously record via the actual capture device,
  and check for that frequency's energy spike in the recording (a simple
  Goertzel/FFT bin check, not full whisper transcription -- this is
  tone-detection, not speech). Would give:
  - A real audio-diagnostic test (does sound actually reach the mic from
    each output path -- TV/handset/whatever), not just "the subprocess
    exited 0" (which is exactly the false confidence that let tonight's
    silent-earcon bug go unnoticed for a while).
  - A **noise-floor calibration tool**: record N seconds of ambient room
    audio with nothing playing, report peak/RMS stats -- directly useful
    for retuning `CRT_VAD_THRESHOLD` (see `crt-stt-solo.py`'s own header
    comment on why VAD is peak-based, tuned for THIS room's specific
    noise floor) without guessing/live-testing by ear each time the room
    or hardware changes.
  - Loopback timing could also give a real measured round-trip number
    for "how long between telling ALSA to play and the mic actually
    picking it up" -- a concrete input to any future latency budget,
    rather than an assumed-negligible constant.

- **2026-07-23 07:10 (real bug, hotfixed live, root cause not fully
  closed):** restarting potato's stt tmux window (to pick up tonight's
  earcon changes) exposed that `crt-stt-solo.py`'s capture device default
  (`CRT_AUDIO_DEV=plughw:0,0`) doesn't exist as a capture device on
  potato at all -- `arecord -l` only lists card 1 ("KT USB Audio") for
  capture; card 0 (bcm2835 onboard) is playback-only. The process
  restarted silently exits (no error, no capture) rather than failing
  loudly. Confirmed via dmesg a real USB reconnect event happened
  mid-session (~01:25 BST, KT USB Audio re-enumerated with new HID
  instance IDs) -- plausible trigger, though it doesn't fully explain why
  the ORIGINAL process (started 03:47, after that reconnect) kept working
  fine on the same default all evening; didn't chase that discrepancy
  further tonight. Hotfixed by pinning `CRT_AUDIO_DEV=plughw:1,0` in both
  the live tmux relaunch and `crt-console.sh`'s stt window (so a future
  full restart doesn't regress). **Real fix, not done tonight**: stop
  hardcoding an ALSA card INDEX at all -- resolve the capture device by
  NAME (parse `arecord -l` for "KT USB Audio" or similar) at startup
  instead, so any future USB replug/reboot-driven renumbering can't
  silently break capture again the same way.

- **2026-07-23 07:45 (measured live on potato, real numbers, pivots the
  earlier dual-tier design idea):** tested "beep the instant the wake
  word is detected, via a local tiny.en whisper pass on potato" (Zach's
  ask, extending the 2026-07-23 01:00 dual-tier STT note above). Result:
  **not viable as designed** -- whisper (any size, including tiny.en) is
  the wrong model family for this job on this hardware. Measured on
  potato directly (`~/whisper.cpp/build/bin/whisper-cli`, real
  `ggml-tiny.en.bin`, not the test stub):
  - Full jfk.wav sample (11s audio), `-bs 1 -t 4`: **11.1s** -- ~1x
    realtime, no faster than the audio itself.
  - Trimmed to 1.2s of audio, same flags, default `-ac` (audio context):
    still **12.0s** -- whisper's encoder pads/processes a fixed internal
    window regardless of actual input length, so trimming the clip alone
    does nothing.
  - Same 1.2s clip with `-ac 512` (reduced audio context): **4.1s**
    total, encode time alone **2.8s** -- this is the real floor, a CPU
    throughput ceiling on this Pi, not a config problem.
  - `-ac 128`: destabilized rather than sped up further -- one run hung
    past a 2-minute timeout, a second returned garbled/truncated text
    ("And") with a nonsensically long total-time figure. Not a usable
    direction, don't push audio-context reduction further than ~512.
  - Bottom line: best case (~2.8-4s) is slower than or comparable to the
    full remote pipeline's just-tuned end-to-end latency (~1.5-3s,
    2026-07-23 07:15 note above) -- a "beep on detect" meant to feel
    instant would land AFTER the real answer's own round-trip, which
    defeats the purpose.
  - **Right tool instead**: the offsite-STT research note from earlier
    tonight (2026-07-23 00:15) already named the correct fit --
    **Vosk or Sherpa-ONNX**, Kaldi-based keyword spotters purpose-built
    for exactly this (<100ms, designed for weak ARM hardware), not
    general transcription. Next step for the wake-detect-beep idea is
    evaluating one of those for keyword-spotting specifically, not
    retrying whisper at a smaller size.

- **2026-07-23 07:15 (live latency-tuning session, real changes made):**
  root cause of the ~6s felt round-trip found and addressed: it wasn't
  STT/whisper (measured 1-3s), it was `crt-secretary.py`'s fixed
  `CLAUDE_IDLE_SECS=3` wait before the pane-diff idle-detector considers
  Claude "done" replying. Changed tonight:
  - `CLAUDE_IDLE_SECS` default lowered 3->1.5 (still env-overridable).
    Added a "grace-check" in `wait_for_claude_reply()`: right before
    finalizing on an apparent idle break, one more poll confirms the pane
    really stayed quiet; if it grew during that grace window, waiting
    resumes instead of returning a reply cut off mid-thought. This is the
    real answer to "what if a reply gets cut off, can't we append" --
    rather than reopening an already-spoken reply, it just doesn't
    finalize early in the first place. Needs live re-tuning by ear over
    more sessions, 1.5s is a first retune not a final number.
  - Added a `thinking` earcon (`bin/crt-earcon.sh`), fired the instant
    secretary escalates to Claude (before the real wait begins) --
    kills dead air during the wait. Deliberately one fixed sound for now;
    documented as the seed of a fuller expressive layer (contour/urgency
    varying with expected wait length, escalation type, etc) for later,
    not built beyond the single sound tonight.
  - Added a cheap scaffold toward the bigger "stream grey partial text,
    overwrite with white flavorful final text" idea: `wait_for_claude_reply`
    now takes an `on_partial` callback, fired once on first real pane
    growth. Wired to `show_composing_line()`, which just pushes
    "...composing" through the existing `crt-think.sh` -> thoughts.log ->
    window 1 path (same path `show_filler_line()`'s speculative-filler
    idea already uses). This is NOT the grey/white streaming design --
    just a foothold in the right place if/when that gets built.
  - Filed, not built: running the actual Claude Code session on mandark
    instead of potato, to see if Pi CPU/network path (not just
    CLAUDE_IDLE_SECS) is also costing latency. Added a documented
    stub/seam in `crt-secretary.py` right above `capture_pane()` --
    only `capture_pane()`/`send_to_claude()` assume a local tmux pane;
    swapping those two for an SSH- or HTTP-based remote equivalent is
    the whole change needed later. Explicitly NOT built tonight because
    the measured bottleneck was the idle-wait, not the host running
    Claude -- don't build this until that's separately confirmed to
    matter.

- **2026-07-23 06:40 (gap found via live log review, not yet built):**
  the STT wake-word gate (`addressed_to_console()` in
  `bin/crt-stt-solo.py`) has NO "stay open" window after a successful
  wake -- every single utterance must contain the wake word (or a
  confirmed `stt-fixups.json` alias) to reach secretary/Claude at all,
  even mid-conversation right after a reply. Confirmed live 2026-07-23
  ~06:21 BST on potato: "Potato, this is Zach" woke it and got a reply
  ("still listening"), but the next four follow-up utterances in the
  same breath ("we made some updates to the model", "routed off-site...",
  etc) all got silently gate-dropped for lacking the wake word again.
  Zach expected this to already exist -- likely conflated with
  `crt-claude-bridge.py`'s `CRT_BRIDGE_FALLBACK_STALE_SECS` (2min,
  window-1 marker-filter fallback), a similarly-shaped but *unrelated*
  timer in a different part of the pipeline. Needs an actual
  sticky-conversation-window: once woken, keep the gate open for N
  seconds/turns without re-requiring the wake word, then re-arm.
  Threshold tuning (how long to stay open, single-word-utterance
  handling, etc) is a real design question, not just a number to guess
  -- Zach floated making the tuning itself a game/rhythm-game rather
  than a config file.
- **2026-07-23 06:41 (game idea, not yet built):** "potato game" --
  ASCII-art potato on screen, user says "potato" (or whatever the wake
  word/pool is), and each STT-recognized word/fragment from the
  utterance gets splashed around the potato scored by string similarity
  to "potato" (reuse `crt-wake-pool.py`'s `difflib`-based near-match
  scoring, already built for the wake-pool near-miss tally). Splash
  duration and brightness proportional to similarity score. Doubles as:
  (a) a fun way to *feel out* the STT error pattern for this specific
  word live instead of reading `stt.log` after the fact, and (b) per the
  sticky-window note above, a candidate vehicle for actually tuning
  gate/threshold parameters interactively (a rhythm-game-style loop
  instead of editing a config value and guessing) -- these two ideas
  may be the same feature.

- **2026-07-23 01:00 (higher-concept design, not yet built):** dual-tier
  STT design idea from Zach — potato runs a small/fast local whisper
  model (tiny.en) continuously in parallel with the offsite transcribe
  (mandark's `mandark-whisper-server.py`, or a higher-quality API later),
  same audio, two consumers. The local tiny pass exists purely for
  low-latency, low-confidence tasks: single-word/short-utterance
  wake-word and CONTROL-keystroke detection (yes/no/enter/up/down/etc,
  see `CONTROL` dict in `bin/crt-stt-solo.py`) via simple thresholding —
  "did I just hear my wake word or a control word" doesn't need
  base.en-quality accuracy or a network round-trip, just fast local
  signal. The offsite/remote pass stays the accuracy source of truth for
  actual content (everything that gets routed to secretary/Claude).
  This is the "high-responsivity watchword" design floated earlier in
  this project (see Option C in prior conversation/PARKING-LOT.md-style
  hybrid discussion) — same shape as the tiny.en-local +
  better-model-remote hybrid, but the local tier's *job* narrows to
  wake/control-word spotting specifically rather than full transcription.
  **Reusable fallback**: this is also the natural shape for "what
  happens if `CRT_WHISPER_SERVER` is unreachable" (flagged separately
  above/2026-07-23 00:40 note re: `transcribe_remote()`'s silent-empty
  failure) — if the local tiny-model pass is already running for
  wake/control words, promoting it to full-utterance duty when the
  remote is down is a small extension, not a new subsystem.

- **2026-07-23 00:40:** two things worth re-checking/hardening now that
  `crt-stt-solo.py` on potato offloads transcription to
  `bin/mandark-whisper-server.py` (`CRT_WHISPER_SERVER`, wired into
  `crt-console.sh`'s stt window 2026-07-23):
  - The "single mic reader only" design constraint in `crt-stt-solo.py`'s
    header was measured on the VirtualBox guest's *emulated* capture
    device (dsnoop starving a second reader). Potato has a real ALSA
    device (`ALC3271`/`plughw:0,0`) — that constraint may not actually
    apply on real hardware. Worth re-measuring before assuming a second
    concurrent reader (e.g. a separate level-meter process) would still
    starve `crt-stt-solo.py` here.
  - `transcribe_remote()` (bin/crt-stt-solo.py) returns `""` silently on
    ANY error talking to `CRT_WHISPER_SERVER` (timeout, mandark down, LAN
    drop) — no fallback to local `whisper-cli`. Right now that means a
    dead/unreachable mandark makes potato go fully silent, not just
    slower. Worth adding a local-whisper fallback path if this offload
    becomes the permanent default rather than a low-risk experiment.

- **2026-07-23 00:15 (research to-do, not yet acted on):** offsite/real-time STT alternatives to self-hosting whisper on mandark/potato, surfaced via a Gemini conversation Zach pasted in. Options worth evaluating later if the mandark-whisper-server (Option A, `bin/mandark-whisper-server.py`) latency/uptime ever becomes a real constraint:
  - **Managed APIs w/ free tiers**: Deepgram Nova (~$200 free credit, ~450+ hrs, native WebSocket streaming ~300ms latency), Gladia (10 hrs/month free forever, Whisper-based streaming), AssemblyAI ($50 free credit).
  - **Free-hosted open-source**: HF Inference Endpoints/Spaces free CPU tier (whisper-tiny/small via whisper.cpp or faster-whisper — may struggle with latency), Colab/Kaggle notebook + ngrok/localtunnel relay (zero-cost but sessions reset, not for 24/7).
  - **Self-hosted streaming-native projects** (better fit than plain whisper-server for true streaming vs. chunked-VAD): `whisper-live` (faster-whisper, ~500ms), whisper.cpp server mode (~200-400ms, already have the binary built on mandark), Vosk/Sherpa-ONNX (Kaldi-based, not Whisper, <100ms, lightest weight — worth a look if latency ever matters more than accuracy).
  - Current mandark server already covers the "self-hosted offsite" case reasonably (2.7s for 11s audio via faster-whisper); this list is for if/when we want lower latency (streaming vs. full-clip POST) or to compare against a managed option's accuracy.
- **2026-07-22 14:11 (via `scheduler -i`):** set up claude on pi to not use thinking. looking for the lowest api usage possible. eventually, canned responses injected before claude responds based on cached past conversations with claude calls in batches for review. visually, claude should be able to overwrite the canned responses on the screen with its informed response later. minimize api usage, maximize responsiveness.

## FIRST STEP EVERY CYCLE (2026-07-21): pull from crt-vm before doing anything else

This account now has standing SSH access to crt-vm (`ssh crt-vm`, alias
in `~/.ssh/config`, key `~/.ssh/crt_vm_pull` — both live in this
account's home directory, NOT the disposable clone, so they survive the
`git reset --hard` this repo's clone gets every cycle). crt-vm runs its
own hands-on, interactive Claude sessions independently of this batch
job, and has repeatedly diverged from this repo without anyone noticing
until the next manual pull — as of 2026-07-21 the VM had built an
entire fuzzy-wake-word "calibration game" feature (see its own
`.claude/SESSION-STATE.md`, fetch with
`ssh crt-vm "cat ~/crt/.claude/SESSION-STATE.md"`) that had never once
synced back. Real feature work has sat un-synced for a while before —
don't assume this repo reflects everything crt-vm has done.

**Before reading further in this file, before touching any code:** run
`bin/crt-sync-vm.sh status` (read-only) to see what's changed on
crt-vm since the last sync. If it reports anything under `ONLY_VM` or
`DIFFER`, run `bin/crt-sync-vm.sh pull` next (never auto-commits —
copies VM-only files into the working tree for review). Then:
- Anything genuinely standalone (new files with their own tests that
  pass against this repo as-is) — safe to `git add`/commit normally as
  part of this cycle's work.
- Anything that DIFFERs from a file already tracked here — do NOT
  blindly overwrite either direction. Read both versions, understand
  why they diverged (crt-vm's `.claude/SESSION-STATE.md` explains its
  own recent changes), and only merge what you can verify still passes
  the full test suite. If a real conflict needs a human decision, leave
  it uncommitted in the working tree and describe it in tonight's
  report rather than guessing.
- If `bin/crt-sync-vm.sh` fails (host key, auth, connection) — don't
  spend the whole cycle debugging SSH; note it in the report and
  continue with whatever this cycle would otherwise do. The credential
  is new (set up 2026-07-21) and not yet proven reliable across many
  unattended runs.
- **Check crt-vm's own `.claude/SESSION-STATE.md` header before merging
  anything DIFFER.** As of 2026-07-21 it explicitly warns of a SEPARATE
  live SSH Claude Code session actively working on the VM in real time
  (Zach talking directly to the physical console, tuning things live) —
  merging a file mid-edit by that session would be actively destructive,
  not just risky. If that header's still there, treat any DIFFER file
  as off-limits for this cycle beyond pulling+reading, no matter how
  tempting the merge looks.

## Compute-stick migration in progress (2026-07-21) — read this before touching install.sh/scanner/console boot wiring

Moving off dexter+crt-vm onto a single Intel Compute Stick, **Debian
13.6 amd64 confirmed as the target**. This is a genuine architecture
shift, not a hardware swap — the whole dexter<->crt-vm bridge (separate
Windows host + VM guest) goes away, one machine does everything. Commits
so far, in order: `43bf894` `4a5fb27` `a932b08` `64947fe` `5484d5a`
`985ac4a`. What each did:

- **`43bf894`** — Gemini wired as a cheap-tier question source for Book
  Game (`crt-book-game.py`'s `call_gemini_batch()`), key installed via
  `install.sh` (`CRT_GEMINI_API_KEY`, file or interactive prompt).
- **`4a5fb27`** — two input-routing bugs closed: `crt-scanner-feed.py`
  no longer `tmux send-keys`'s scans into whatever window has focus
  (dead leftover from before the stdin pivot, a second uncontrolled
  escalation path into Claude's pane); window 1 (`mono`) now also shows
  the user's own STT utterances, not just Claude's replies.
- **`a932b08`** — registered (not built) the next offline-safe item:
  Gemini-before-Claude fallthrough in `crt-secretary.py` itself (see the
  entry below this one) — separate track, not part of the stick move,
  just filed the same day.
- **`64947fe`** — **`bin/dexter-scanner-forward.ps1` retired** (git
  history only, `git log -- bin/dexter-scanner-forward.ps1`). It only
  ever existed to bridge the scanner across two machines; bare metal
  has one. `crt-book-console.py`'s stdin path now writes its own
  `scanner.log` entries (`format_scan_log_line()`, self-echo-suppressed)
  so the audit trail survives without that listener running.
- **`5484d5a`** — `install.sh` gained optional `CRT_WIFI_SSID/PSK/IFACE`
  (nmcli or wpa_supplicant, whichever's present) and
  `CRT_CLAUDE_CREDENTIALS_PATH` (pre-seeds `~/.claude/.credentials.json`
  so first boot skips the interactive Claude Code login — same
  mechanism this account's own nightly-batch jobs already rely on for
  unattended `claude -p`).
- **`985ac4a`** — `avahi-daemon` + `CRT_HOSTNAME` (default
  `crt-console`) for `crt-console.local` mDNS discovery; `crt-console.sh`
  flashes the real IP on the physical screen for `CRT_IP_FLASH_SECS` at
  boot as a same-segment-only mDNS's fallback; `install.sh` restructured
  around one editable `CONFIG` block up top PLUS interactive prompts for
  every value (WiFi password, Gemini key, Claude credentials can now be
  **pasted directly**, EOF-terminated, jq-validated) — both paths work
  for everything now, not just one value.

**What's still open, not this account's job to build:**
- **OS-level preseed/unattended-install** — a different agent is on
  this already, blocked on a GRUB blind-mode issue on the real
  hardware. Don't duplicate that work; `install.sh` assumes Debian is
  already installed and network-reachable by the time it runs.
- **Nothing here is hardware-verified.** Every piece above (WiFi via
  nmcli/wpa_supplicant, avahi/mDNS, the IP flash, the credentials
  paste/pre-seed path) is written and unit-tested offline only — same
  acceptance bar as everything else in this repo. First real boot on
  the actual stick is the actual test.
- If you're a fresh session picking this up (on the stick itself, or
  continuing this migration from mandark/svc-vaporwave): read
  `README.md`'s "Bare-metal deployment" section and `install.sh`'s own
  header/CONFIG block first, they're kept current with all of the above.

- **2026-07-22 (folded in via realisateur's nightly-batch):** two
  duplicate inbox drops in realisateur
  (`service-that-runs-on-the-crt-v-20260720-214544.idea` and the
  `...214555.idea` twin, same text) independently re-described the
  barcode-scanner → book quote/summary feature — this is exactly the
  Book Game funnel already designed in `SCANNER.md`/`BOOK-GAME.md`
  ("Not yet implemented" section of `SCANNER.md`: stdin-reading in
  `crt-book-console.py`, flip default tmux window to `book`). No new
  work added here, just a corroborating signal from Zach that this is
  the right feature to keep pushing on — both source notes archived in
  realisateur, not scaffolded as a separate project.
- **2026-07-22 (folded in via realisateur's nightly-batch):** dexter NPU
  idea (`dexter-npu-tools-20260722.idea`) — clean up `dexter` (the Ryzen
  mini-PC hosting `crt-vm`) and wire in its real NPU (Ryzen AI/XDNA)
  tooling to accelerate whisper.cpp STT inference (Ryzen AI SDK/DirectML/
  ONNX Runtime backend) instead of the current plain-CPU build, letting
  the console run a bigger/more accurate model than `base.en` at the
  same latency. NPU can't do training/fine-tuning (quantized low-power
  inference silicon, no backprop toolchain) — inference acceleration
  only. Needs a different whisper.cpp build/backend than `install.sh`
  builds now, and dexter is live hardware — treat like the `potato`
  reachability item above: hands-on work, not something this unattended
  tier can execute blind. Flagging here rather than scaffolding a
  separate project since it's dexter/crt-vm-specific infrastructure, not
  a standalone idea.

- **2026-07-20 15:57 (via `scheduler -i`):** vision: crt off, handset on killswitch hookswitch. handset picked up = noise in line. lightweight watcher tracks mic signal, no AI API yet. handset pick up, IR beam monitor on, sidetone in earpiece. user speaks command in natural language, earpiece beeps expressively in response based on keyword type filter that directs a search tree. users voice shows as flickering line on crt (stt at bottom of screen, right aligned, line length based on amplitude, visual decay, eventually predictive text auto fills in words, or lighter weight stt with shorter window drops words that later get replaced by better stt. tunable afterglow that lets last recorded line persist for a few seconds for auditing. words grey out from left to right. language tree does its best to navigate without API calls, calls out to API when unsure, little light in the corner indicates claude has been requested. claude comes in and takes over the bot voice (user never feels it). program is always recording stt results (eventually voice when we merge vm and windows halves) and generating more accurate handling of interactions. games and idle bait are important ways of requesting specific sonic information in a structured way that informs the voice detection model. we never feel it when claude comes in to take over, other than the color change. calls to claude leave residue for future refinement automatically but the token usage of claude calls should be minimized by default and tunable.

**Heads-up (2026-07-20, from scheduler's own repo) — check scheduler's
current state before building against old assumptions.** A significant
scheduler redesign session happened today: the `.claude/**` permission
gate crt's own `MORNING-REPORT-PRESENTATION.md` work ran into is now
root-caused and fixed (files move to a top-level `.scheduler/` dir,
outside `.claude/`); `bin/morning-report.sh`/`DIGEST.md` — the interface
`crt-present-morning-report.py` parses — is very likely getting retired
in favor of `bin/scheduler` (a real, already-working CLI: `scheduler`,
`scheduler -b/-f/-q/-r`), not just fixed for the hang bug crt reported.
Before doing more work on the morning-report presenter specifically,
read scheduler's own `.scheduler/FOCUS.md` (the "Vision", "Consolidation
roadmap", and blockers-aggregation sections) to see whether the shape
being parsed is still the right target.

**Next offline-safe pickup, registered 2026-07-21 (interactive session,
not yet built): Gemini-before-Claude fallthrough in `crt-secretary.py`.**
Gemini is already wired as a cheap-tier source, but only inside
`crt-book-game.py`'s trivia-question generation (`call_gemini_batch()`,
committed `43bf894`) -- that path never touches `crt-secretary.py` at
all. `crt-secretary.py`'s own fallthrough (an utterance that matches no
PLAYBOOKS) still goes straight to live Claude Code every time. Zach's
direct call (2026-07-21): leave this for a nightly batch pass rather
than build it in the interactive session that scoped it. Shape to
follow: on fallthrough, try a Gemini call first (reuse the
`_load_gemini_key()`/`call_gemini_batch()`-style pattern already in
`crt-book-game.py`, but this is free-form assistant-style text, not the
structured question-JSON contract -- needs its own prompt/parse, not a
literal reuse of those functions) and only escalate to real Claude Code
if Gemini's answer is missing/low-confidence/fails outright. See
`SECRETARY.md`/`STT-GATE.md` for the existing playbook-dispatch shape
this slots into, and this session's commits `43bf894`/`4a5fb27` for the
input-routing cleanup it follows on from.

**Current focus: the core STT pipeline** (see "Now (core STT, blocked on
VM)" below) — but every item there needs a live `crt-vm` session, which an
unattended batch run doesn't have. See `../HANDOFF.md` for full state and
access.

**2026-07-20: all 8 offline-safe items below are DONE** (opt-in secretary
wiring, calibration-margin consumption, glissando earcons, ANSI colors,
TTS prosody, sideband wiring, calibrate playbook, fallthrough logging —
126 offline checks green, `tests/run_tests.sh`). Kept below for the
record/links; nothing left in this section for an unattended pass to
pick up until either a new offline-safe batch is registered here, or VM
access unblocks the STT section.

## potato migration — blocked on physical reachability (2026-07-22)

`potato` (Raspberry Pi migration target, see `../SELF-REPAIR.md` and the
assistant's own memory) went unreachable mid-physical-move tonight and
came back on an unknown IP. **Branch around this — needs Zach's hands**,
same as any live-hardware item: a subnet scan (`nmap -sn` /
`nmap -p22 --open`) found no host with SSH open except the known
OctoPrint Pi (`192.168.0.43`); the old address (`192.168.0.45`) is dead.
Zach was looking at potato's actual monitor and saw the book-game tmux
window, not window 0 — **that is NOT a bug**, `bin/crt-console.sh` selects
`book` as the boot-default window on purpose (see that file's own
2026-07-21 comment on raw-scanner-keystroke focus) — do not "fix" this
away in a future pass. He couldn't read the tiny on-screen text to get
the IP either.

**Real code-shaped fix once potato is reachable again (do this first, it
directly prevents tonight's exact problem from recurring):** potato has
no mDNS/avahi — `ping potato.local` fails with "Name or service not
known" from mandark. Install/enable `avahi-daemon` on potato (Debian
trixie, `apt-get install avahi-daemon`, plus confirm mandark has
`libnss-mdns`/avahi resolution working, which it may not either) so
`potato.local` resolves regardless of DHCP lease changes after a move —
this is exactly the class of problem that just cost a live session real
time. Also worth checking whether the router can hand out a DHCP
reservation for potato's MAC instead/in addition.

Self-repair mechanism itself (`bin/crt-self-repair.sh`,
`systemd/crt-self-repair.{service,timer}`) is designed and committed to
THIS repo but was never copied onto potato or `git init`'d there — still
todo, also blocked on reachability.

## Book Game — structured STT training-data game (2026-07-21, vision session)

**End-goal statement (2026-07-21, Zach) — the whole point of this
subsystem, keep every future piece pointed at this:** a voice-interactive
scanner system that idle-baits someone into picking up a book and
scanning it, then entices them to speak trivia into the mic that's used
for training the voice (STT). Idle-bait → scan → question → spoken
answer → STT training log is one continuous funnel, not four separate
features — judge any future addition by whether it strengthens a step in
that funnel. **Division of labor going forward**: this account (the
unattended nightly-batch tier) develops continuously at a controlled
pace; a separate hands-on agent watches this work, syncs it to crt-vm,
does simple dexter/crt-vm-side tasks, and reports back on its own
recurring loop (see the "2026-07-21 late session" pivot below for an
example of exactly that kind of hands-on finding this account can't
produce alone).

Full vision, roadmap, and open questions: `../BOOK-GAME.md`. Direct instance
of this file's own 2026-07-20 15:57 vision line ("games and idle bait are
important ways of requesting specific sonic information in a structured
way that informs the voice detection model") — scan a book's ISBN barcode,
ask a 2-option multiple-choice question about it, grade the spoken answer
against the two known option strings, log every (expected, heard) mismatch
as labeled STT training data, register the book locally. Stretch: print an
LCC label per book via the existing Phomemo/`catprint` channel or a
dedicated label printer (open question, see BOOK-GAME.md).

**Offline-safe slice: DONE, 2026-07-21.** `bin/crt-book-game.py` +
`tests/test_book_game.py` (40 cases, all green in `tests/run_tests.sh`,
plus a live smoke-test against the real Open Library API). Covers ISBN
lookup, question templates + Claude-batch prompt/parse (pure functions,
no live `claude -p` shell-out wired yet), grading/logging, SQLite
registry, best-effort LCC, screen layout/centering, ASCII art, CRT-safe
color palette, non-API idle-bait quotes (`bin/crt-book-idle-bait.py` +
`tests/test_book_idle_bait.py`), and `parse_scan_line()` bridging
`bin/crt-scanner-feed.py`'s `[scan] <isbn>` delivery convention
(SCANNER.md) to this CLI's `--isbn`/`--scan-line` args. Full detail in
`../BOOK-GAME.md`'s Roadmap step 1 and `../BOOK-GAME-STYLE.md`.
**Now wired into `crt-console.sh` as its own tmux window (`book`),
2026-07-21** — `bin/crt-book-console.py` tails `~/.crt/scanner.log` and
renders the question screen for each new scan. 10 more tests
(`tests/test_book_console.py`), full suite green. Not yet wired into
`crt-secretary.py`'s playbook dispatcher — that's still a separate,
not-yet-built step.

**Spoken-answer grading now automatic, 2026-07-21** (closes the last
manual-only link in the funnel): new `bookanswer` tmux window,
`bin/crt-book-answer-listen.py`, watches `~/.crt/stt.log` and grades the
next recognized utterance against whatever book was scanned within
`CRT_BOOK_ANSWER_WINDOW_SECS` (default 20s), reusing
`grade_answer()`/`log_training_row()` unchanged — "pending question" is
derived from `books.db`'s own `first_scanned` column, not new shared
state. Built as its own file rather than editing `crt-book-console.py`/
`crt-book-game.py` directly, since both were mid-live-debug elsewhere the
same session (missing `random` import, `quote`-column migration) —
avoided colliding with that work.

**Result announcement added, 2026-07-21**: grading used to only print
debug text to the `bookanswer` pane. `format_result_line()` now composes
an actual game-show-host announcement in `BOOK-GAME-STYLE.md`'s register
(content/settled "got it!" for correct, clipped "nope, it was X" for
wrong, neutral "logged your answer" for ungradeable fallback questions,
never gloating or sad either way) and appends it to `~/.crt/thoughts.log`
— same channel `crt-monologue.sh` already tails, so a graded answer now
actually shows up on screen instead of only in a background pane's debug
log. 6 more tests, 19 total (`tests/test_book_answer_listen.py`), full
suite green.

**Idle-bait rebuilt around the actual end-goal, 2026-07-21 (see above)**:
`bin/crt-book-idle-bait.py` and `crt-book-console.py`'s idle screen now
mix enticement lines (invite a NEW scan — `pick_entice_line()`,
`ENTICE_LINES`) with quote lines (celebrate a book already scanned) —
previously an empty `books.db` meant idle-bait silently did nothing at
all, now it always shows an enticement line. Also added real per-book
quotes via a Wikiquote webscrape (`scrape_quote()`, not an AI call,
cached once per book) and 3 kawaii ASCII art entries. Full detail in
`../BOOK-GAME-STYLE.md`'s "Idle-bait: two registers" section. 12 more
tests, full suite green.

### Stdin-scan pivot: DONE 2026-07-21 (was "NEXT (late session)")

Both steps of the hands-on agent's confirmed-live plan are now built:
1. **`bin/crt-book-console.py` reads its own stdin.** A background thread
   (`stdin_reader`) iterates `sys.stdin` (terminal cooked mode already
   buffers a scan's fast keystrokes until Enter, same as a human typing)
   and pushes lines onto a queue the main loop drains non-blockingly
   alongside the existing `scanner.log` tail — `parse_stdin_scan_line()`
   validates ISBN shape (no tab-prefix to strip, unlike `scanner.log`'s
   format), then reuses `handle_scan()` unchanged. Stdin is the primary
   path in practice now; `scanner.log` stays wired as a fallback in case
   the dexter bridge is ever fixed.
2. **`bin/crt-console.sh` makes `book` the boot-default window** instead
   of `claude` (window 0) — the manual `tmux select-window` the hands-on
   agent did live now survives a respawn/reboot. `claude` stays one
   `prefix+0` away.

**Verified**: a real subprocess smoke test (bare ISBN piped to stdin,
real Open Library fetch) rendered the correct question screen end to
end. `dexter-scanner-forward.ps1` + the scanner NAT port-forward +
`crt-scanner-feed.py`'s systemd service are now "nice to have, not
load-bearing" for book-scanning, exactly as planned. 4 new tests
(`tests/test_book_console.py`), full suite green. **Still needs an
actual physical scan on the real tube** to fully close this out — this
session already got burned once by an unverified "confirmed working"
claim on the dexter-side path, so treat this as offline-verified only
until a human watches a real scan render correctly.

Original context/writeup (dexter dead-end root cause) kept in
`../SCANNER.md`'s "2026-07-21 late session" section for history.

### Book Game training-data stats, DONE 2026-07-21

The end-goal (see this section's opening statement) is STT training
data — until now that data just sat in `~/.crt/book-game-training.jsonl`
with no way to see progress without reading the raw file by hand. New
`bin/crt-book-game-stats.py` (zero Claude calls, pure local reads of
`books.db` + the training log) surfaces book count, question-source
mix, and — given top billing over trivia correctness, since it's the
actual point — **STT accuracy**: how often what was heard matched what
was expected, plus every logged mismatch (the literal training
artifact). `screen`/`print-all` modes match
`crt-present-morning-report.py`'s existing convention. Also wired into
`crt-secretary.py` as a new `book_game_stats` playbook ("how's the book
game going", "trivia stats") so it's reachable by voice the same
locally-answered way `status`/`morning_report` already are. 14 + 3 new
tests (`tests/test_book_game_stats.py`, `TestBookGameStatsPlaybook`),
full suite green.

**Training data made actionable, 2026-07-21**: displaying mismatches
wasn't enough — `crt-book-game-stats.py export-fixups` now converts
repeated (expected, heard) mismatches into candidate
`bin/stt-fixups.json` entries, the exact shape that file already uses
(`STT-MECHANISM.md`'s garble taxonomy), always marked `confidence:
candidate` (never `confirmed` — matches that file's own bar, only a
human calibration session earns `confirmed`). Only surfaces a pair once
it's recurred at least twice (tunable), since a one-off mismatch could
just be noise. This is the actual "improve STT inference over time"
loop CLAUDE.md names as this console's top priority, closed end to end:
scan → question → spoken answer → logged mismatch → candidate fixup a
human can review and copy straight into the real file. 5 more tests,
24 total, full suite green.

**Full-funnel offline integration test added, 2026-07-21**:
`tests/test_book_game_integration.py` runs `crt-book-game.py` →
`crt-book-console.py` → `crt-book-answer-listen.py` →
`crt-book-game-stats.py` together against one shared `books.db` +
training log — real registration, real grading, real announcement
rendering, real re-scan cache-hit check, and a repeated-mismatch →
candidate-fixup check, all in one scenario. Distinct from every
individual file's own unit tests (which each mock their neighbors) —
this catches data-shape mismatches between files that grew across many
separate passes, before they'd ever surface live. All 3 scenarios passed
on first write, confirming the pieces built independently across today's
passes do actually compose correctly.

**Real crash bug found and fixed, 2026-07-21 — CONFIRMED LIVE, not
theoretical.** `fetch_book_metadata()` raises on any ISBN Open Library
doesn't recognize (confirmed live: a real `curl` against
`openlibrary.org/isbn/0000000000.json` returns a genuine `404`) or on a
network failure — and until this fix, **nothing caught it anywhere**.
Since the whole point of this feature is inviting someone to scan "any
book nearby," this was guaranteed to crash the `book` window (now the
boot-default tmux window) on a large fraction of real scans — out-of-
print books, non-ISBN barcodes, a network hiccup — not a rare edge case.
Same failure class as the earlier missing-`random`-import crash, just
certain to recur constantly instead of being a one-off. Fixed:
`crt-book-console.py`'s `handle_scan()` now raises a distinct
`ScanLookupFailed` (not a bare re-raise) that `main()` catches and shows
via a new `render_scan_error()` screen ("couldn't find that book, try
another!", clipped/`COLOR_WRONG` register) instead of crashing;
`crt-book-game.py`'s CLI degrades to a clear message instead of a raw
traceback. **Verified live against the real Open Library API** (not just
mocked): both the console window and the CLI handled ISBN `0000000000`
cleanly, no crash, no traceback. 6 new tests, full suite green.

**Second real bug found, this one via a self-written stress test, 2026-07-21**:
`books.db` is no longer single-process — `crt-book-console.py`,
`crt-book-answer-listen.py`, `crt-book-idle-bait.py`,
`crt-book-game-stats.py`, and this CLI can all open it concurrently now,
but `get_db()` never enabled WAL mode. Fixed: `get_db()` now sets
`PRAGMA journal_mode=WAL` and bumps the connect `timeout` to 10s. Writing
a real 10-thread concurrent-writer stress test
(`tests/TestConcurrentAccess`) then caught a SECOND, narrower race: fresh
schema initialization (`CREATE TABLE`/`ALTER TABLE`) can still
transiently collide when several connections race to set up a
brand-new database file at the exact same instant — WAL fixes ongoing
read/write contention, not concurrent schema creation. Fixed with a
short retry-with-backoff in a new `_init_schema()` (best-effort for this
fresh-install-only edge case, not a hard guarantee under an adversarial
thundering herd — documented as such, not oversold). Split the test into
a realistic steady-state case (schema already exists, must never
error — stable across 20 repeated runs) and a harsher fresh-init case
(allowed occasional retries, also stable across 20 runs). 2 new tests.

**Third real bug found via the same happy-path audit, 2026-07-21**:
`crt-book-console.py`'s `stdin_reader()` background thread (the primary
scan path now) had a silent-failure mode — if `sys.stdin` ever hit EOF
(e.g. the tmux pane's stdin gets closed/reattached) or raised any read
error, the thread just died. The main loop kept running and looked
perfectly healthy (idle/quote screens still rotating normally), but
scanning via stdin quietly stopped working forever for the rest of that
process's life, with zero visible indication — the exact same class of
invisible failure as the two bugs above, just in the input path instead
of storage. Fixed: `stdin_reader()` now always pushes a `STDIN_DEAD`
sentinel (via `try/except/finally`) when it exits for any reason;
`main()`'s drain loop detects it and calls `warn_stdin_dead()`, which
appends a clipped/`COLOR_WRONG` warning to `~/.crt/thoughts.log` (the
same channel `crt-monologue.sh` tails) instead of the failure being
silent. **Verified live**: piped an immediately-closed stdin into the
real script — the warning appeared in `thoughts.log` exactly as
designed. 4 new tests, full suite green.

**Fourth real bug, same audit, 2026-07-21**: `log_training_row()` — the
function that writes the actual STT training data, the entire point of
this subsystem — had **zero error handling** around its file write,
unlike every other logging call in this project
(`crt-secretary.py`'s `log_fallthrough`, `crt-book-answer-listen.py`'s
`announce`, both already best-effort). A failed write (disk full,
permission issue) would crash whichever caller invoked it —
`crt-book-answer-listen.py`'s `main()` loop, silently killing grading
for the rest of that process's life, same invisible-failure shape as
bugs 2 and 3 above. Fixed: wrapped in `try/except OSError`, prints a
visible warning to stderr (both known callers run in a foreground tmux
pane by default, so this is actually seen, unlike the fully-backgrounded
`stdin_reader` case bug 3 had to solve differently for), still returns
the computed row either way since the grade data itself is valid even
if persisting it failed. **Verified live** with a real broken-path call.
1 new test, full suite green.

**Fifth bug, found via a focused sweep of every `bin/crt-book-*.py`
file's remaining unguarded file I/O, 2026-07-21**:
`crt-book-idle-bait.py`'s `main()` had the exact same missing-try/except
shape as bug 4, but in its own steady-state `while True` loop rather
than a called function — the `thoughts.log` append sat directly inline
with no error handling, so a single write failure would silently kill
the whole background idle-bait loop forever. (Swept the other
`crt-book-*.py` files' remaining `open()`/`os.makedirs()`/
`sqlite3.connect()` call sites too — `tail_new_lines()` in both
`crt-book-console.py` and `crt-book-answer-listen.py` are unguarded at
startup, but that's a fail-fast-and-visible crash on launch, not a
silent steady-state death, so left as-is; nothing else unguarded found.)
Fixed by extracting the write into a new `append_thought_line()`
wrapped in `try/except OSError`, same convention as bug 4's fix. 2 new
tests, full suite green.

**Next offline-safe batch pickup (registered 2026-07-21, not yet
built): real webscrape quotes + kawaii ASCII art.** Idle-bait quotes
currently only use Open Library's `first_sentence` field (rarely
populated) plus a 5-entry static fallback pool (`bin/crt-book-idle-bait.py`,
`BOOK-GAME-STYLE.md`) — Zach wants an actual per-book quote pulled by
webscrape (explicitly NOT an AI/Claude call, just literal scraped text).
Confirmed live from this account's sandbox: Wikiquote's MediaWiki API
(`https://en.wikiquote.org/w/api.php?action=query&list=search&srsearch=<title>`
then `...&prop=revisions&rvprop=content&rvslots=main&titles=<page>`) is
reachable and its wikitext is straightforwardly parseable — top-level
`* text` lines are real quotes, `** text` lines are attributions/sources
to skip, `[[link|display]]`/`'''bold'''`/`''italic''` markup needs
stripping. Build a `scrape_quote(title, fetcher=None)` pure-ish function
in `crt-book-game.py` (injectable fetcher for tests, same pattern as
`fetch_book_metadata`), called once at fresh-registration time (not at
idle-bait read time, so idle-bait itself stays a pure local read) and
cached into a new `quote` column in `books.db` — never re-scraped on a
re-scan, same cache-once philosophy as questions/LCC. Wire the fallback
chain as: cached scraped quote → `extract_quote()`'s `first_sentence` →
the static pool, in that priority order. Wrap the whole scrape in a
broad try/except (network flake, no Wikiquote page, empty parse all
possible) so a slow/unreachable Wikiquote can never block or crash a
scan — falls through to the existing chain instead. Also add 2-3
kawaii/kaomoji-style entries to `ASCII_ART` (in the same voice as
`crt-idle-bait.sh`'s existing `(=^-^=)`-style faces, not the current
plain line-art `book`/`cat_reading`/`bookworm`/`shelf` set) — hand-authored,
not scraped, per the ASCII-art library's existing "not machine-fetched"
convention. Full offline-buildable and testable (mock the Wikiquote
fetcher in tests, same as Open Library's), no hands-on crt-vm session
needed for this piece.

**Scanner hardware bridge is no longer a blocker** — `SCANNER.md`
(built by a separate hands-on crt-vm/dexter session, 2026-07-21) has the
dexter→crt-vm scanner forward live and systemd-persistent, and the new
`book` tmux window above already consumes it directly. Remaining
hands-on work (BOOK-GAME.md roadmap step 2): run against the real mic,
and eyeball `BOOK-GAME-STYLE.md`'s screen/color/art choices on the
actual tube. Also still open (not hardware, just not built this pass):
the live `claude -p` shell-out for batch question generation, and
grading wired into a live session instead of the manual CLI.

### Claude escalation now switches windows; STT training now merges unattended (2026-07-21)

Two more of Zach's direct asks from the same message, both closed this pass:

**How calls into Claude actually work, and why it was invisible on `book`**:
`crt-secretary.py`'s `send_to_claude()`/`capture_pane()` operate on tmux
window 0's pane directly (`tmux send-keys`/`capture-pane -t SESSION:PANE`),
entirely independent of which window is currently *displayed* — so an
escalation while someone was watching `book` (the boot-default window) was
happening completely off-screen. Fixed with two pieces:
`crt-secretary.py`'s `handle()` now calls `switch_tmux_window(CLAUDE_VIEW_WINDOW)`
(default `mono`) the moment it escalates, and touches a small state file
(`~/.crt/claude-window-active.state`) each time. New `bin/crt-window-switcher.py`
is a separate long-running background process (new `windowswitch` tmux window)
that watches that state file and switches focus back to `book` after
`CRT_WINDOW_SWITCHER_IDLE_SECS` (default 30s) of no Claude activity — has to be
a separate process because `crt-secretary.py` itself is a fresh short-lived
process per utterance, it can't host its own idle timer. A new
`return_to_book_game` playbook ("book game" / "back to the game" / etc.) gives
the explicit-command half too. Watch the trigger-ordering: `"book game"` is a
substring of the existing `"book game stats"` trigger, so `return_to_book_game`
had to be placed AFTER `book_game_stats`/`book_catalog` in `PLAYBOOKS` or it
would permanently shadow them — caught by a new collision test before shipping.
13 new tests across `tests/test_secretary.py` + new `tests/test_window_switcher.py`.

**STT training in the background**: `generate_candidate_fixups()`
(`crt-book-game-stats.py`) previously only ever printed candidates for a human
to copy-paste into `stt-fixups.json` by hand (`export-fixups` CLI mode). New
`bin/crt-stt-training-merge.py` closes that loop — periodically recomputes
candidates from the accumulated training log and merges new ones directly into
the live `stt-fixups.json`, tagged a new third confidence tier `"auto"` (never
touches or upgrades an existing entry). Wired into `crt-console.sh` as a new
`stttrain` background window (`--loop` mode). **Honest scope note, read the
script's own header before assuming this changes live behavior**:
`stt-fixups.json` today has exactly one consumer — `crt-stt-solo.py`'s
wake-word gate — and only entries whose `intent == "claude"` do anything there.
A book-game-derived entry like `"friction" -> "fiction"` is real, correct
plumbing for whenever that file gets a broader consumer, not a claim that
book-game answer accuracy improves the moment this runs. It DOES matter
immediately if a genuine wake-word mishear variant ever repeats. 10 new tests,
`tests/test_stt_training_merge.py`, full suite green (100+ tests).

Color/width/idle-movement hard rules from the same message are documented in
`BOOK-GAME-STYLE.md`, not duplicated here.

### Gradual move to longer canned trivia responses, DONE 2026-07-21

Closed the last open item from that message: `generate_template_question()`
now takes a `tier` param (`"short"`, the default/unchanged behavior, or
`"long"`). Each existing template's options get rephrased into a full
canned sentence carrying the same choice instead of a single word --
`"before"/"after"` becomes `"it was published before {year}"/"...after
{year}"`, a bare first name becomes `"the author's first name is
{name}"`, `"fiction"/"nonfiction"` becomes `"it's a work of
fiction"/"...nonfiction"`, the no-facts fallback becomes `"yes, I have
read it"/"no, I haven't read it"`. Same 2-option/exact-match grading
mechanics throughout, no rendering changes needed --
`render_question_screen()` already truncates the joined options line to
`MAX_CONTENT_WIDTH` (30), so this is purely more spoken content per
round, not a new render risk.

New pure function `pick_response_tier(total_rounds, stt_accuracy,
min_samples=8, threshold=0.7)` makes the gradual part real: stays
`"short"` until at least `CRT_BOOK_GAME_LONGFORM_MIN_SAMPLES` (default 8)
graded rounds exist AND measured `stt_accuracy` over those rounds is at
least `CRT_BOOK_GAME_LONGFORM_ACCURACY_THRESHOLD` (default 0.7) --
matches Zach's own framing exactly ("as you notice more success... move
towards longer responses"), never flips to long-form while the room/mic
setup is still struggling with one-word answers, and never flips off a
lucky short streak right after a fresh install. A new local helper
`_recent_training_stats()` reads `book-game-training.jsonl` directly for
this -- deliberately NOT importing `crt-book-game-stats.py` back into
this file (that module already imports this one via
`importlib.util.spec_from_file_location`, which execs a fresh copy;
importing the other way would recurse forever), so the count-and-average
is duplicated in miniature rather than restructuring either file's
import pattern. Wired into the CLI (`crt-book-game.py --isbn ...`) as the
tier decision for every fresh scan. 13 new tests across
`TestQuestionGeneration`/new `TestResponseTier` in
`tests/test_book_game.py`, full suite green.

Wired into BOTH question-generation call sites: the standalone CLI
(`crt-book-game.py --isbn ...`) and `crt-book-console.py`'s
`handle_scan()` (the live `book` tmux window's real scan path) --
each computes its own tier via the same `_recent_training_stats()` +
`pick_response_tier()` pair before calling
`generate_template_question()`, so the live path and the CLI path can
never silently diverge on this.

### Happy-path bug found and fixed: voice commands mid-window got misgraded as trivia answers (2026-07-21)

Another audit pass, same technique as the earlier stdin-death/unknown-ISBN/
sqlite-concurrency finds: `crt-book-answer-listen.py`'s `grade_pending_answer()`
graded ANY STT utterance inside `CRT_BOOK_ANSWER_WINDOW_SECS` (default 20s)
of a scan as the trivia answer, with no check for whether it was actually a
voice **command**. Saying "book game stats" or "back to the book game"
shortly after scanning -- an entirely ordinary thing to say before getting
around to answering -- would have been logged as a garbage training row
(`"expected": "fiction", "heard": "book game stats"`) and announced as a
misleading "nope, it was fiction" verdict for a question the user never
tried to answer. Not hypothetical: 20 seconds is a normal amount of time to
say something else first (ask for stats, ask to leave book mode) after a
scan lands.

Fixed by importing `crt-secretary.py`'s own `find_playbook()` (loaded via
the same `importlib.util.spec_from_file_location` cross-script pattern
everything else here uses -- confirmed `crt-secretary.py` has no
module-level side effects, safe to import purely for this pure-function
reuse) and skipping grading entirely when the utterance matches any known
command, exactly the same way `crt-secretary.py` itself would have routed
it. This can never drift out of sync with what actually counts as a
command elsewhere in the project, since it's the same dispatch table, not
a duplicated/guessed trigger list. Checked every existing playbook's
trigger list against plausible trivia answers (including the new
long-form phrasings from the tier system above, e.g. "it's a work of
fiction") to confirm no real answer could ever collide with a command and
get wrongly skipped -- none do (all triggers are either exact-phrase
control words or "book"/"catalog"/"calibrate"/"morning report"-shaped,
nothing overlapping "fiction"/"before"/"after"/a name/"yes"). 4 new tests
(2 confirming the fix, 2 confirming ordinary answers still grade normally),
full suite green.

## Cross-project ask: locate prior demucs work on dexter (2026-07-20)

`wtul` (the CD-ripper project) needs Demucs for ROADMAP #5 (instrumental
intro/outro detection) and Zach says he already tried installing/running
Demucs on dexter once before, with leftover files somewhere on that
machine. This project runs on dexter/crt-vm and is the thing already
reaching dexter over the network (see `dexter-whisper-server.py`), so it's
the natural place to leave this note for whoever/whatever next has hands
or a session on dexter.
%%ACTION next time there's a live session on dexter (not the isolated
nightly-batch clone — this needs the real machine), look for prior Demucs
install/model-download artifacts (check pip/conda envs, `~/.cache`,
anywhere resembling a `demucs` venv or downloaded checkpoints). Report
findings back — either the path to reuse, or confirmation there's nothing
to reuse — to `wtul`'s `ROADMAP.md` #5 / `.claude/QUESTIONS.md` (the
cross-project scheduler `BLOCKERS.md` has the `## wtul` heading if a
quicker landing spot is wanted instead).

## DONE (offline-safe, no VM/dexter needed) — registered 2026-07-20, completed 2026-07-20

Every item here is buildable and testable with `tests/run_tests.sh` alone
— no VM, no dexter, no real audio hardware. Each MUST land with its own
test coverage added to `tests/`, and any behavior change to an existing
default pipeline (stt-feed.sh, crt-stt-solo.py) MUST be opt-in via an env
flag, default off, exactly like `CRT_PREDICT_FLASH` already is — none of
this should change what the live console does today until a human can
watch it run. Do NOT claim anything "sounds good," "feels right," or is
hardware-verified — that bar still needs a real ear/eye, see the
acceptance-bar note in `.claude/commands/nightly-batch.md`.

1. **Wire `crt-secretary.py` into `stt-feed.sh`**, opt-in
   (`CRT_SECRETARY=1`, default off — the raw send-keys path stays the
   default). Test with a mocked tmux, same pattern as
   `tests/test_secretary.py`. See `SECRETARY.md`/`SUPERVISOR.md`.
2. **Consume the calibration margin**: `crt-pager.py`/`crt-monologue.sh`
   don't read `~/.crt/display.conf` yet — subtract the saved margins from
   the auto-detected WIDTH/HEIGHT. See `DISPLAY-CALIBRATION.md`'s "not
   done this session" note.
3. **Extend `crt-earcon.sh`'s pitch contours** — most registers are still
   plain note sequences, not the glissando/sweep shapes `oops` already
   uses. See `EXPRESSIVE-TONE.md`'s "explicitly not doing (yet)" list.
4. **ANSI color-per-register** in `crt-idle-teaser.sh`/`crt-monologue.sh`
   output — the color dimension `EXPRESSIVE-TONE.md` named but didn't
   reach. `CLAUDE.md` explicitly grants ANSI control of the screen.
5. **Per-call TTS prosody overrides** in `crt-tts.py` — pitch/rate/volume
   currently only come from flat `tts.conf`/env config, not per-call, so
   the register taxonomy can't actually vary spoken delivery yet. See
   `EXPRESSIVE-TONE.md`.
6. **Wire sideband state transitions**, opt-in — `crt-stt-solo.py` (VAD
   start/stop -> listening/idle), `crt-secretary.py`/`crt-tts.py`/
   `crt-earcon.sh` (mute-duck around their own playback via
   `~/.crt/sideband.mute`). See `SIDEBAND.md`'s "not done this session."
7. **A `calibrate` playbook** in `crt-secretary.py` — voice trigger runs
   `crt-calibrate-display.py show`. Named as the natural next playbook in
   `SUPERVISOR.md`.
8. **Fallthrough-logging** in the supervisor — log any request that
   matches no playbook (to a file, not acted on) so a future session can
   see which requests keep escalating to Claude and are worth a new
   playbook. `SUPERVISOR.md`'s open item.

Stop-by-report-time applies as usual (see nightly-batch.md step 3's
budget). If only some of these fit in one pass, do them in the order
listed — earlier items unblock/inform later ones (2 and 7 are related;
6 depends on nothing else here).

## Now (core STT)

- **2026-07-20: Approach B (single-reader `crt-stt-solo.py`) is now live and
  promoted into `bin/crt-console.sh`'s actual boot default** — see
  `AUDIO-DEBUG.md` and `HANDOFF.md`. The dsnoop-staleness class of bug (A/C/D
  below) is now moot for the default boot path since there's only one reader;
  those approaches stay documented in `AUDIO-DEBUG.md` in case `stt-feed.sh`'s
  debug/secretary modes need them later, but aren't the active priority.
- Ongoing calibration: `CRT_VAD_THRESHOLD`, Windows mic boost, normalization.
  **Needs the VM** — not urgent, current defaults are working.

### STT gate — don't call Claude on room noise/ambient conversation (2026-07-20, Zach)

Right now every utterance `crt-stt-solo.py`'s VAD cuts gets typed straight
into the Claude pane — **every** clip that clears the VAD threshold and
produces non-empty whisper text becomes a live Claude Code turn, including
room chatter never meant for the console (`CLAUDE.md`'s whole premise is a
noisy room). That's a real cost/privacy problem, not just noise: the console
is currently "always listening AND always escalating."

**Zach's direction (2026-07-20):** build a simple gate now; the long-term
target is bigger than a gate:
1. **Near-term (this item): a simple gate.** Before an utterance reaches
   Claude, decide locally whether it's actually addressed to the console.
   Candidates (pick one or layer them, this is a real design decision for
   whoever picks this up, not a spec):
   - **Wake word**: require "claude" (or another trigger word) to appear in
     the utterance before typing it in; otherwise just log to `stt.log`/
     `thoughts.log` and drop it. `bin/stt-fixups.json` already has a
     confirmed mis-hear entry for this exact word ("slide" → "claude"),
     which a wake-word gate makes load-bearing rather than cosmetic — get
     the fixup lookup wired into whatever does the gating.
   - Keyword/intent filter (per the very first FOCUS.md vision entry at the
     top of this file, 2026-07-20 15:57: "language tree does its best to
     navigate without API calls, calls out to API when unsure").
   All of the *logic* here (string/keyword matching against a transcribed
   utterance) is offline-testable — no VM needed to build and unit-test the
   gate itself, only to verify it live against real room noise once written.
2. **Long-term (do NOT build this now, just keep the shape in mind so the
   near-term gate doesn't paint it into a corner)**: replace "gate then type
   into Claude" with a real local text-handling service — non-AI, handles
   known commands/patterns directly, and *escalates* to Claude only when it
   doesn't know what to do. This is a bigger rewrite of the stt→claude
   pipeline (`crt-stt-solo.py`'s `CRT_STT_SINK=claude` path), not a
   follow-up to the gate — flagging so the near-term gate is built as a
   clean layer that a future service can slot in front of, not a
   Claude-specific hack.

**Parked for the nightly batch** — this is Zach's explicit call ("we'll park
that for the nightly runs"), not urgent for this session.

## Deferred (not in current focus — do not pull these into an STT session)

**Moved 2026-07-20**: the hands-on-hardware items that used to live here
(MIDI controller, physical hookswitch, OctoPrint, Benchy print, USB
phone-interface module, the VM-hardware-check install) now live in the
scheduler's cross-project `BLOCKERS.md`, under `## crt` — that file is the
one-glance human-owned surface across every project; this one stays
scoped to code-shaped backlog. Still deliberately **not** in current
focus, still branch around anything needing hands on hardware or a live
VM if it resurfaces here by mistake.

1. **Stretch: video-call wrapper** (Zoom/WhatsApp) over the handset/CRT —
   not a blocker (nothing needed from a human to start), just genuinely
   unstarted backlog, lowest priority.

## Secretary reframing (2026-07-19) — see SECRETARY.md
The real goal is a phone-secretary service, not a raw STT->Claude terminal.
Printer = long output, CRT = short status + slow-scroll (`bin/crt-pager.py`,
built), TTS = spoken confirmation through the phone (`bin/crt-tts.py` +
`bin/crt-tts-calibrate.py`, built + espeak-ng deployed to crt-vm), TV
announcements for Chris rate-limited to 1/15min (`bin/crt-announce.sh`, code
done, cross-VM-boundary bridge to actually reach the TV output NOT built --
see AUDIO-ROUTING.md). `bin/crt-stt-speakback.sh` runs STT in debug mode
(stdout, NOT wired to Claude) and speaks "heard: ..." back through the phone
so a person can debug the mic by ear -- running live on crt-vm's `stt` window
as of 2026-07-19. The actual secretary wrapper (structured request -> Claude
-> route response to printer/CRT/TTS) is still design-only, next concrete step.

## MIDI passthrough — parked, see PARKING-LOT.md (2026-07-20)
Root cause of the original failure is known (fixed) but `VBoxManage
usbattach` still fails on a stuck VBoxSVC host-proxy state, needs a
process restart on dexter that wants a human's direct OK first. Full
status, next step, and portability direction moved to
`PARKING-LOT.md`'s "MIDI controller pass-through" section — not on the
critical path for the core voice console, don't pull it back into an
unattended batch's scope.

## faster-whisper network service on dexter (2026-07-19, DONE, live)
`bin/dexter-whisper-server.py` runs faster-whisper natively on dexter's Ryzen
(port 8991, `/health` + `/transcribe`) so transcription isn't CPU-capped by
the VM. `crt-stt-solo.py` uses it when `CRT_WHISPER_SERVER=http://192.168.0.22:8991/transcribe`
is set — verified working live. Not auto-starting yet (manual
`Start-Process` on dexter); add a Scheduled Task next. See project memory for
the VPN/huggingface.co gotcha and how the model got there.

## Ring/pickup detection (2026-07-19, smoke-tested)
`bin/crt-ring.sh <n>` rings the phone via `crt-stt-solo.py` (the sole mic
reader) — warble tone in bursts, checks for voice only in the silent gaps
(avoids the tone false-triggering), stops on pickup, prints a timeout
message on the active screen if unanswered. No physical hookswitch yet, so
"pickup" is inferred from voice activity alone.

## Inner monologue / on-screen narration (2026-07-19, DONE, live)
`bin/crt-think.sh "text"` appends a timestamped line to `~/.crt/thoughts.log`;
`bin/crt-monologue.sh` tails it on-screen, word-wrapped, in first person as
the machine narrating itself ("i'm a crt, i have a handset..."). This is now
the CRT's active tmux window (STT moved to a background window, still
running/speaking, just not what's displayed). **Ongoing practice going
forward: narrate real work into this log in-character as it happens** (via
`crt-think.sh` over SSH) rather than only reporting after the fact — it
doubles as a durable append-only context record for later sessions.

## Offline test suite now exists (2026-07-19)
`tests/run_tests.sh` — shell syntax checks, `crt-pager.py`/`crt-monologue.sh`
width logic, `crt-predict.py` model logic. Zero VM/hardware needed. Any
future nightly-batch pass should run this before claiming a code-shaped
change "done" — it's real regression coverage now, not just an acceptance-
bar reminder.

## Idle-bait / beeps / sidetone / philosophy design pass (2026-07-19)
Design session, no VM access. Full detail in `.claude/SESSION-STATE.md`
(read that first next session) and the new top-level docs it lists
(`IDLE-BAIT.md`, `SIDETONE.md`, `PHILOSOPHY.md`, `RFP-GALLERY.md`,
`RFP-PAYPHONE.md`, `cad/CAD-BACKLOG.md`). New scripts, all code-shaped and
therefore fair game for an unattended nightly pass to extend/harden
(but NOT to mark "verified" — none of this has touched real audio
hardware yet, see the acceptance-bar note in `.claude/commands/
nightly-batch.md`):
- `bin/crt-earcon.sh`, `bin/crt-report.sh`, `bin/crt-idle-teaser.sh` — new,
  untested by ear/against live traffic. Safe unattended work: dry-run them
  (syntax, obvious logic bugs), NOT claiming they sound good or that the
  teaser cadence feels right — those need a human on the handset.
- `bin/crt-announce.sh` — bugfixed (stale TV device string). Low-risk to
  re-verify against `crt-tts.py`'s current `DEXTER_DEVICES` if that file
  changes again.
- Two open questions logged in `.claude/QUESTIONS.md` need Chris, not a
  guess: handset audio guest-vs-host routing (blocks sidetone), and
  idle-bait quiet hours.

## Parking lot: deep end-state vision — see PARKING-LOT.md
RF power-on-TV-when-handset-lifts, HDMI-to-RF multi-channel personas, hidden
transcription (blinking cursor only), predictive-typing-then-overwrite
aesthetic, two core jobs (morning reports + media playback), start on
dexter/Ryzen natively while the Compute Stick waits on a DAC. Not being
built yet — captured so the direction survives.

## Compute stick (still blocked, physical)
No progress possible remotely -- flashing/booting the actual Intel Compute
Stick STK1AW32SC needs hands on the physical device. The Ubuntu Server ISO
noted as "downloaded on mandark" in a prior session's scratchpad could not be
found this session (scratchpad from that session no longer exists) -- if
still needed, redownload before the next hands-on session.

## Autonomous overnight batch (enabled 2026-07-19)

crt is now a git repo pushed to a LOCAL bare remote (`~/git-remotes/crt.git`),
and registered with the scheduler's Tier 2 batch (`schedule/crt.conf`), 3
passes/night (01:45/03:45/05:45), 30-day auto-sunset. Each run reads this file
+ `AUDIO-DEBUG.md` and advances the code-shaped backlog (audio approaches, STT
watchdog/single-reader, USB firmware, video wrapper), branching around anything
physical. Reports land in `~/reports/crt/`. A GitHub mirror is optional later
(deploy key `~/.ssh/crt_deploy_key` is ready; swap `REPO_URL` in the conf).

## Fable review (2026-07-25)

<!-- Appended by realisateur/fable-like/inject-suggestions.sh. Full context: fable-like/FABLE_REPORT.md. Triage these like any dated entries; delete freely. -->

- **2026-07-25 (fable-review):** mandark's paced-runner log shows crt dispatches 2026-07-24 23:58/23:59 despite `_paced.conf` enabled=0 and dexter ownership — verify (stale log vs real double-dispatch), then make single-host dispatch a runner-enforced invariant, not a two-config-file implication
- **2026-07-25 (fable-review):** resolve the bibliothecaire name collision (your parked Book-Game catalog split vs realisateur's new inbox "page 92" idea) before either scaffolds