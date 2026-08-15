# FOCUS -- retired 2026-08-14, migrated to GitHub issues

**The backlog now lives at https://github.com/hf7y/crt/issues.** This is the
ecosystem-wide policy as of 2026-08-07 (`hf7y/scheduler#66`, swept by
`hf7y/realisateur#230`, root cause `hf7y/realisateur#187`); this file is a
pointer, not a second source of truth. Do not add work items here -- file an
issue. `.claude/commands/nightly-batch.md` was re-pointed in the same commit,
so nothing writes this file any more.

## Where the stability milestone went

**The bar, unchanged:** the core voice loop (wake word -> STT -> Claude reply
-> spoken response, with a sticky follow-up window and no handset
play-while-capture interference) is reliable on real potato hardware, AND the
Book Game funnel runs end to end on potato's current layout.

| Bar item | Now |
|---|---|
| Sticky-conversation / arm window | [#9](https://github.com/hf7y/crt/issues/9) -- code done, live result still missing |
| Handset play-while-capture | **done**, live-verified 2026-07-28: the USB adapter genuinely cannot play+record at once, dmix/dsnoop does not fix it, and the CTL-file duck does (24 clean mute/unmute cycles observed) |
| Capture device resolved by NAME | **done**, live-verified 2026-07-28 against potato's real `arecord -l` |
| Book Game funnel end to end | [#11](https://github.com/hf7y/crt/issues/11) -- offline half passes, live scan needs a human and a book |

## Where the ranked backlog went

| Was | Now |
|---|---|
| 1. Refactor sweep / config consolidation | mostly **done** (dead VM+dexter code deleted, `:8992` gone, the 8993 port collision resolved); the missing shell-side config half is [#20](https://github.com/hf7y/crt/issues/20) |
| 2. Docs consolidation | [#19](https://github.com/hf7y/crt/issues/19) |
| 3. Pi-without-mandark standalone jobs | [#21](https://github.com/hf7y/crt/issues/21) |
| 4. Book Game reboot audit | folded into [#11](https://github.com/hf7y/crt/issues/11) |
| 5. Interface / interaction streamlining | [#22](https://github.com/hf7y/crt/issues/22) |
| 5b. Screensaver CRT-margin depth | [#23](https://github.com/hf7y/crt/issues/23) -- the wrap bug and `potato_large.txt` are already resolved |
| 5c. Test-coverage gaps | **done** 2026-07-24 (`550b70c`, `e8d6aba`) |
| 6. Calibration suite as first-class checks | [#24](https://github.com/hf7y/crt/issues/24) |
| 7. Handset 3-pin switch writeup | **done** 2026-07-24 (`9cc07a1`) -- same switch `HOOKSWITCH.md` already specs, writeup landed there |
| 8. Wake supervisor | [#25](https://github.com/hf7y/crt/issues/25) |
| 9. Sticky wake window / dormant wake judge | [#9](https://github.com/hf7y/crt/issues/9) and [#10](https://github.com/hf7y/crt/issues/10) |
| 10. Streaming STT for wake-spotting | [#26](https://github.com/hf7y/crt/issues/26) |
| `scheduler -i`: potato game as boot mode | [#28](https://github.com/hf7y/crt/issues/28) |
| `scheduler -i`: text column constraints | folded into [#23](https://github.com/hf7y/crt/issues/23) |
| `scheduler -i`: passwordless sudo on potato | [#27](https://github.com/hf7y/crt/issues/27) |
| `scheduler -i`: textart.sh potato scrape | [#29](https://github.com/hf7y/crt/issues/29) |
| bibliothecaire quotes in idle-bait | [#31](https://github.com/hf7y/crt/issues/31) (waiting on that file) |
| Hookswitch debounce test flake | [#30](https://github.com/hf7y/crt/issues/30) |
| "The ears did not move" -- whisper still on mandark | [#13](https://github.com/hf7y/crt/issues/13) |

## What was NOT migrated, and why

- **The 2026-07-21 through 2026-07-29 session log -- roughly 1,100 of this
  file's 1,608 lines.** Landed work, narrated: the stdin-scan pivot, the Book
  Game training-data stats, the Claude-escalation window switch, the trivia
  response work, the compute-stick preseed inventory, the whisper service, the
  inner monologue, the offline test suite. It is a changelog, and git already
  is one.
- **Four separate 2026-07-25/07-28 entries about crt not dispatching on
  dexter.** Diagnosed at the time (a monthly spend limit stopped the runner on
  07-25, and the burn-rate gate held every 5 minutes after) and stale now --
  this repo has dispatched since. The `sweep.lock` candidate was explicitly
  disproven as a red herring; the dead-man `expires_at` was 2026-08-01 and has
  passed. What remains of that thread is scheduler's, not crt's.
- **The false-DARK crt readings (2026-07-27 and 2026-07-28)** -- a survey
  reading only mandark's `_paced.conf` and never `_paced.dexter.conf`. Not a
  crt bug, filed to scheduler at the time, and the pre-verb architecture it
  described is retired.
- **The bibliothecaire catalog-split fork.** Resolved 2026-07-26: Zach chose
  split-scope-only, a separate greenfield project. Nothing moves out of crt's
  tree. Only the quotes-file hook (#31) touches this repo.
- **Parked-by-the-bar ideas**, named here so they are findable: dual-tier
  local+offsite STT (folded into #26), compute-stick / bare-metal migration
  (excluded from this bar by Zach 2026-07-24, see
  `COMPUTE-STICK-MIGRATION.md`), Gemini-before-Claude fallthrough, and dexter
  NPU tooling. Cost and performance optimizations on a loop that is not
  reliable yet.

Full history -- every dated entry, every falsified prediction, and the
reasoning behind each decision above -- is in git before this commit.
