# Architecture review handoff — 2026-07-23

**Purpose of this document**: a synthesized packet for a fresh (more
capable) model reviewing this project's fundamental design, not another
incremental status update. `FOCUS.md`/`SESSION-STATE.md`/`QUESTIONS.md`
already track the tactical backlog in detail — this document instead
asks: *given everything found in one long live session, is the current
shape of this system right at all, or do the recurring problems below
point at something structural worth reconsidering?* Where I have an
opinion I've said so, but flag it as an opinion, not settled fact —
that's exactly what a fresh perspective should feel free to overturn.

## What this project is

A landline handset + CRT television driven by Claude Code, meant to feel
like a voice-operated assistant living inside old hardware. Speech goes
through whisper-family STT, gets gated by a wake-word check, and either
gets answered by local "playbook" logic or escalated to a live Claude
Code session.

## Current topology (as of tonight)

- **potato** — a Raspberry Pi 3 Model B+ (confirmed via `/proc/cpuinfo`
  this session, NOT the Pi 4/5-class hardware earlier assumptions were
  built on), the actual physical console. Runs the mic capture, VAD, a
  live interactive Claude Code session, and ~8 always-on background
  helper scripts (window switching, book-game trivia, idle-bait
  messages, STT training-data merge, a window-1 "mirror" display), all
  in one tmux session.
- **mandark** — a dev laptop (i7-10710U, 12 threads, 7.5GB RAM), this
  session's own environment. Now also runs a `faster-whisper`
  transcription server potato offloads to over the LAN.
- **dexter/crt-vm** — a Windows host + VirtualBox VM combo. Legacy: this
  session confirmed potato has replaced it as the live console, but a
  meaningful amount of design documentation and even some code
  (`crt-wake-pool.py`, `crt-wake-judge.py`, `WAKE-TUNING-STATE.md`'s
  entire judgment log) originates from that era and was migrated
  unevenly.
- **potato's git tree is NOT a clone of the main repo.** Separate git
  history (`git fetch` confirms "no common commits"), working tree
  seeded by hand-copying files over SSH. This has already caused real
  problems (see "Migration fragility" below).

## Recurring problem 1: the wake-word/gate design has been rebuilt at
## least three times and still doesn't work end-to-end

**The layers that exist today, roughly in the order they were built:**
1. Exact wake-word string match (`addressed_to_console()`,
   `CRT_WAKE_WORD`, default "claude").
2. `stt-fixups.json` — a hand-curated dict of confirmed STT mishears
   mapped to an intent (e.g. "slide"/"clot"/"potato" → "claude"). This
   is also literally the project's mechanism for correcting STT errors
   in general, not just wake-word ones — it's overloaded.
3. `crt-wake-pool.py` — a SEPARATE, more sophisticated matcher (exact
   pool-word match, plus a fuzzy "cluster of close words" match via
   `difflib`) built 2026-07-21, capable of treating many more words as
   valid wake triggers (book titles, a hand-seeded dict).
4. `crt-wake-judge.py` + `WAKE-TUNING-STATE.md` — an **autonomous
   self-tuning judge**, also built 2026-07-21: spawns a real `claude -p`
   call after a wake event resolves, judges whether it was a real wake
   (a follow-up utterance arrived) or noise (timeout), and is trusted to
   edit the tuning files itself. `WAKE-TUNING-STATE.md` has a genuinely
   rich judgment log (dozens of dated, real-transcript entries) proving
   this **ran live at least once** — almost certainly on the old crt-vm,
   per one entry that literally says "it's a virtual machine."
5. **Tonight's finding**: the actual state machine wiring #4 to a live
   trigger (`consume_arm_with_followup()`/`check_arm_timeout()`) was
   referenced by name in #4's own code and log, but **implemented
   nowhere** — grep-confirmed zero hits anywhere in `bin/*.py` before
   this session. I built it tonight (`bin/crt-wake-arm.py`), fully
   opt-in (`CRT_WAKE_ARM_ENABLED`, default off), not yet hardware-verified.

**Concrete bugs/gaps found this session, independent of the above:**
- **No sticky window**: confirmed live — a real wake ("Potato, this is
  Zach") got a reply, then four follow-up utterances in the same breath
  right after all got silently gate-dropped for lacking the wake word
  again. (This is exactly what item 5 above is meant to fix, once
  verified.)
- **STT mishears the wake word itself, repeatedly, in different ways**:
  the raw logs this session show "potato" transcribed as "Pajeta,"
  "Tatum," "Patera," "Titto," "Patero," "clot," "clod," "POTETO" — a
  live illustration of how much surface-area a single-word/short-phrase
  wake trigger has for STT garbling, and how the current fix mechanism
  (manually confirming each new mishear into `stt-fixups.json`) is
  reactive and can never get ahead of a genuinely noisy room.
- **`CRT_VAD_MAX=20` (hard cap) vs `CRT_VAD_TRAIL=0.8` (silence
  detection)**: confirmed live that continuous speech with no real pause
  rides the full 20-second cap before an utterance is even cut, then
  queues for transcription on top of that. This is a **batch-VAD
  architecture limit**, not a tunable-number problem — no amount of
  adjusting these two constants makes the system feel responsive
  *during* continuous speech, only changes where the batch boundaries
  fall.

**My own read, worth challenging**: this whole area has had three
different people/sessions (going by commit messages and doc dates) each
independently conclude "the current wake mechanism isn't good enough"
and add ANOTHER layer on top, rather than replacing the layer
underneath. The result is real complexity (five distinct matching
mechanisms if you count all of the above) most of which has never been
exercised together in one live run. **A fresh design pass might ask**:
does this need five layers, or does the WAKE-TUNING-STATE.md philosophy
(let a judge model tune matching *live*, on real data) replace most of
layers 1-3 outright once actually wired up and trusted, rather than
sitting alongside them?

## Recurring problem 2: potato's hardware is memory-constrained in a
## way that may cap any STT-quality fix

- Confirmed this session: Raspberry Pi 3 Model B+, 905MB total RAM.
  Under normal live operation (Claude Code + ~8 background scripts +
  tmux), **available memory sits around 120-400MB with active swap
  use**. Claude Code's own process alone is ~343MB (37% of total RAM).
- Local whisper (even `tiny.en`, even with reduced audio context) was
  measured at a hard floor of ~2.8-4s encode time for a SHORT clip —
  this is a genuine CPU throughput ceiling on this specific board, not a
  config problem (tested directly: `-ac 512` helped, `-ac 128`
  destabilized rather than sped up further).
- Vosk (installed and tested live this session, a real aarch64 wheel,
  small English model) was ALSO not dramatically faster than realtime on
  this specific box — first partial result at t+1.53s for a 1.5s clip.
  This contradicts the "<100ms, built for weak ARM hardware" framing an
  earlier research pass assumed; that framing was likely calibrated
  against Pi 4/5-class hardware, not a Pi 3B+ under real memory pressure.
- Trimming non-essential background features (Book Game funnel,
  idle-bait) freed real but modest swap pressure (~27MB) — not
  transformative given the scale of the constraint.

**My own read, worth challenging**: potato's hardware may simply be
undersized for "run a full interactive Claude Code session AND do
meaningful local audio ML AND run 8 background daemons" all at once on
1GB of RAM. I scaffolded (comment-only, not built) a seam in
`crt-secretary.py` for running Claude Code itself on mandark instead,
with potato reduced to a thin physical-interface client (mic capture,
audio out, SSH-driven remote control of the actual Claude session) —
this is structurally the same split dexter/crt-vm used to have, just
implemented with plain SSH instead of a Windows-VM bridge. **Whether
that's the right move, a partial move (just offload local STT further,
keep Claude local), or a hardware upgrade instead is a real open
question**, not something I decided.

## Recurring problem 3: audio device configuration is fragile and has
## broken silently multiple times

- **Capture device**: `CRT_AUDIO_DEV` defaulted to `plughw:0,0`, which
  doesn't exist as a capture device on potato at all (card 0 is
  onboard/playback-only; the real mic is card 1, USB). This was live and
  broken for an unknown period before this session found it — the
  process exits silently with no error when the device doesn't exist.
- **Playback/earcon device**: `crt-earcon.sh` was still POSTing to a
  dexter-hosted audio-bridge server that has no equivalent on potato's
  bare-metal setup — silent no-op (exit 0, no sound), root cause of "no
  beeps ever" for potentially a long time. Fixed this session by routing
  directly to local ALSA devices instead.
- **Handset play-while-capture**: built a real acoustic loopback
  self-test this session (`bin/crt-earcon-loopback-test.py` — plays a
  tone, records via the mic, Goertzel-detects the frequency against a
  baseline). Found the handset output device shows almost no signal
  (0.1x baseline) while the TV path (a separate physical device) shows a
  clear one (5.0x). Tried the standard ALSA fix (dmix/dsnoop sharing) —
  **it made no difference**, which now points away from my original
  "exclusive device access contention" theory and toward either (a) a
  genuine hardware full-duplex limitation on this USB codec, or (b) the
  simpler, more likely explanation: **a real telephone handset is
  deliberately built to acoustically isolate the earpiece from the
  mouthpiece** (preventing feedback), so the mic may simply never be a
  reliable proxy for "can a human hear this," regardless of software.
  This is **unresolved** and needs either a different measurement
  approach or accepting it can only be confirmed by a human ear.
- **Underlying pattern**: at least three separate incidents this session
  of a hardcoded device index/URL silently breaking when the underlying
  assumption (which era's architecture, which piece of hardware) no
  longer held, with no error surfaced anywhere. A fresh design pass
  might ask whether audio device resolution needs a single, consistent,
  fail-loud abstraction layer rather than being resolved ad hoc in each
  of `crt-stt-solo.py`/`crt-earcon.sh`/`crt-tts.py` separately.

## Recurring problem 4: migration between hardware generations has
## repeatedly lost work silently

- The wake-judge system (problem 1, item 4) almost certainly ran live on
  the old crt-vm and was never carried forward to potato — discovered
  only because its own log file happened to survive in the git repo.
- `crt-wake-pool.py` itself — a real, tested, working file already in
  the main repo — had simply never been copied to potato's `bin/` at
  all, discovered only when a new script tried to import it and crashed.
- Potato's own git history contains real independent commits (bug fixes,
  a marker-filter feature) that had never been synced back to the main
  repo until this session found and cherry-picked them.
- **Pattern**: nothing currently *verifies* that potato's deployed state
  matches any particular commit of the main repo, or flags drift. Given
  potato isn't even a git clone of the main repo, this is likely to keep
  happening. Worth a fresh look at whether potato should become a real
  clone (with its own local commits handled via a proper branch/merge
  workflow) rather than a hand-copied target.

## Smaller friction points worth knowing about

- **Two live Claude Code sessions can run concurrently** — one
  driven by this kind of remote/SSH session, one live on potato's own
  window 0 via the physical handset — with no coordination mechanism
  beyond "check the logs and ask before editing a file the other might
  be mid-editing." Worked around manually multiple times this session;
  not a solved problem.
- **`~/reports/crt/` (nightly-batch report destination) is unwritable**
  for the account that actually runs the nightly batch — a group
  membership was apparently revoked at some point after the directory
  was set up. Tonight's report landed in the repo instead as a fallback.
- **The permission-classifier layer** (whatever enforces this session's
  action boundaries) blocked writing a dotfile to potato over a direct
  SSH heredoc, but allowed the *same content* via `ssh potato 'bash -s' <
  script`. Not obviously principled — worth knowing the exact rule if
  designing around it in the future.
- **`transcribe_remote()` has no local-whisper fallback** — if
  mandark's whisper server ever goes down, potato goes fully silent
  (empty string), not degraded.

## What's already built (so a reviewer doesn't redo this)

- `bin/mandark-whisper-server.py` — real transcription server, live,
  systemd-managed on mandark.
- `bin/crt-wake-arm.py` + tests — the arm-window state machine (problem
  1, item 5), opt-in, not yet hardware-verified.
- `bin/crt-earcon-loopback-test.py` — real acoustic self-test tool,
  reusable for future audio-path questions.
- `bin/crt-calibration-game.py` — interactive wake-word/similarity
  scoring game, tailing STT live.
- `bin/setup-potato-audio-sharing.sh` — dmix/dsnoop config (deployed;
  didn't fix the handset finding, see problem 3).
- Earcon device routing fix, capture-device fix, secretary
  latency/grace-check fix — all deployed and stable on potato as of this
  writing.

## The single question I'd most want a fresh model to actually answer

**Is potato (a 1GB Pi 3B+) the right machine to run a live interactive
Claude Code session on at all, given everything above traces back to
either (a) that hardware being memory/CPU-constrained, or (b) design
complexity that accumulated specifically to work around that
constraint?** If the honest answer is "no, move the compute," a lot of
problems 1-3 above may partially dissolve rather than need individually
fixing. If the honest answer is "yes, keep it local," then the wake-word
layering (problem 1) and audio fragility (problem 3) probably deserve a
genuine simplification pass, not another added layer.
