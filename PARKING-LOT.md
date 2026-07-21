# Parking lot: deep crt end-state ideas (2026-07-19)

Not being implemented now — captured so the direction isn't lost. Revisit
once the core secretary loop (SECRETARY.md) and a working transcription
backend are solid.

## Physical/RF concept
- Handset rests on a hook; **lifting it sends IR to power the TV on**
  (like an old-school remote-control power trigger), rather than the TV
  being always-on. Micro computer hidden inside a re-purposed shell
  (candidate: gut an old phone/answering machine chassis).
  **Corrected 2026-07-20** (was "RF" in the original note — an error,
  per direct correction: "IR transmitter should work"): TV power-on is
  the same IR mechanism as the channel-change idea below, not a separate
  RF trigger — one IR blaster likely covers both jobs. See
  `BLOCKERS.md`'s crt deep-vision section for the sourced part
  (`cad/ir_blaster_mount.scad` already has a placeholder mount).
- **HDMI-to-RF modulation** could carry up to 4 channels — different
  "streams"/personas or modes could live on different TV channels.
  **Update 2026-07-20**: the modulator itself is already owned (supports
  this multi-channel/daisy-chain feature) — the remaining blocker is
  housing/mounting/wiring integration, not sourcing. See
  `cad/CAD-BACKLOG.md`.
- Each channel/persona could reinforce its identity by **beaming IR remote
  codes** (channel-change, power) as part of its own behavior — e.g.
  switching mode = actually changing the TV's channel via IR blaster.

### Channel-confirmation loop (2026-07-21, Chris) — replaces the rotary-switch idea
Supersedes `PERSONA-CHANNEL.md`'s rotary-switch decision. Persona/mode is
the CRT's **actual TV channel**, not a separate commodity switch:
1. System decides (or Chris decides, TBD) which persona/channel should be
   active.
2. **IR blaster emits that channel's code** to the TV, reinforcing/
   setting the channel — the same blaster already planned for TV
   power-on above, no new hardware.
3. **TV's own built-in speaker beeps a confirmation tone** specific to
   that channel.
4. **The handset mic picks up that beep** (it's in the room, TV speaker
   is audible) — the system uses it to confirm the channel actually
   landed where it meant to, closing the loop without any dedicated
   sensor or physical switch position to read.
This removes the rotary switch (and its faceplate CAD) entirely — no
knob part to source, no shaft/bushing dimensions to measure. Still needs
a real design pass (which channel = which persona, what the confirmation
tone sounds like/how it's distinguished from room noise) before it's
buildable; captured here so the direction survives, not started yet.

## Interface philosophy
- On-screen: as close to nothing as possible. A **blinking cursor**, not a
  transcript. **Hide the STT transcription entirely once past debugging** —
  today's `crt-stt-speakback.sh`/debug view is explicitly a *debugging*
  tool, not the end state. Transcription errors get silently absorbed by
  the response being elegant/charitable about intent, never shown raw.
- End result reads as a **chatbot that runs as locally as possible**, with
  occasional callouts to Claude Code / a hosted service only when needed
  (e.g. genuinely open-ended requests) — most turns should be answerable
  locally and fast.
- **Aesthetic: the bot starts typing/responding first** using a cheap local
  autocomplete/predictive-response guess (instant, no perceptible latency),
  then **overwrites with the real answer** once a slower callout (Claude
  Code or similar) returns — gives an immediate "it's alive" feel while
  hiding real latency. (Conceptually similar to speculative decoding /
  optimistic UI patterns — cheap local model guesses, authoritative source
  corrects.)

## Two primary jobs (the actual product surface)
1. **Morning reports** — spoken/printed summary on request or schedule.
2. **Play media** — voice-driven local media playback (VLC/ffmpeg-class
   tooling), i.e. "play the thing", "next", "pause" via handset voice.
   **v1 built, 2026-07-21**: `bin/crt-media-player.py` — command parsing
   (`parse_media_command`) is pure and tested; a pluggable `Backend`
   (`FakeBackend` for tests, `VlcBackend` sketched but never run against
   a real `cvlc`/media library) dispatches play/pause/resume/next/stop.
   Wired into `crt-secretary.py` as a `media` playbook. **Conflict
   narrowed and pragmatically mitigated, 2026-07-21**: re-examined
   exactly which words collide — `crt-stt-solo.py`'s `is_control` check
   only ever fires for a single-word, no-space utterance, so the actual
   collision was narrower than first flagged: only bare "next" (not
   "pause"/"resume"/"stop", not any multi-word phrasing like "next
   song"). Dropped bare "next" from `crt-media-player.py`'s triggers —
   "skip" (never claimed by `CONTROL`) and the multi-word phrasings
   remain fully reachable. This is a one-line, easily reversible
   mitigation of the CONCRETE bug (a word that could never route here),
   **not** an answer to the broader cross-persona question
   `PERSONA-CHANNEL.md`'s channel-switch idea exists to resolve (should
   "next" ever mean "skip the song" depending on active mode/persona) —
   that design decision is still genuinely open for Zach.

Everything else (MIDI knobs, TV announcements, pager, etc.) is in service
of these two jobs and the general secretary loop, not separate features.

## Interface hardware priority
**Handset + hookswitch are primary.** Not CRT-as-display, not MIDI knobs —
those are debug/nice-to-have. The hookswitch (off-hook = start listening,
on-hook = stop/power down) is the fundamental interaction model, closer to
an actual telephone than a computer terminal.

## Multiple phone installations (2026-07-19, gallery/art concept)
Two separate installation ideas, distinct from the personal-secretary crt.
Both got real direction 2026-07-20 — see `RFP-GALLERY.md` and
`RFP-PAYPHONE.md` for the full updated briefs:
1. **Distributed answering machines for a gallery** — visitors can leave
   messages or receive them; phones that physically ring when there's
   something waiting. Multiple units, presumably networked to a shared
   backend (or independent per-phone). **Direction given 2026-07-20**:
   leaning toward either autonomous networked Pis (one per unit, can
   interact with each other) or a POTS-wiring hack — see `RFP-GALLERY.md`
   for the possibilities writeup comparing them.
2. **A payphone people actually pay quarters into** — coin mechanism routes
   to a TTS/AI backend that "does something" (answers questions, has a
   conversation). Stretch idea: a token economy — sometimes it gives more
   tokens back than were inserted, turning it into more of a game/gamble
   than a straightforward vending transaction. **Resolved 2026-07-20**:
   quarters used as the test-phase token, real coin mechanism throughout
   (not a separate token-only build), never deployed for real money — see
   `RFP-PAYPHONE.md`, the earlier legal-check blocker no longer applies
   under this framing.

## Video cast to CRT (2026-07-20, scoped)
Later goal, now has real shape — see `VIDEO-CAST.md`.

## Deployment sequencing
- **Start on the Minisforum Ryzen (dexter)** as the primary/first working
  target — full native speed, no VM/compute-stick constraints, matches the
  faster-whisper-network-service direction already in progress.
- **Intel Compute Stick is next**, once a DAC arrives (needed since the
  stick has no analog audio in — see README's bare-metal notes). Until the
  DAC shows up, the stick work is blocked/waiting, not actively pursued.

## Scheduler integration (2026-07-19, user)
Look into hooking crt itself into the scheduler ecosystem beyond just being
a registered nightly-batch participant (already done, see
`schedule/crt.conf` in the scheduler repo) — e.g. the phone/secretary
interface (SECRETARY.md) as an actual delivery surface for scheduler
reports/questions (spoken/printed morning reports, ring for an open
QUESTIONS.md item), not just crt's own code getting nightly attention.
Needs a concrete design pass, not scoped yet.

## Code consolidation across dexter / the VM / mandark (2026-07-19, user)
Project code is currently scattered across multiple machines (dexter's
native Ryzen work e.g. `bin/dexter-whisper-server.py`, the Windows VM guest
side, and mandark as the batch host). Consolidate into one place (this repo
is presumably the target, since it's what's git-managed and scheduler-
registered) so there's a single source of truth instead of code living
wherever it happened to be written. Needs an inventory pass first: what
exists on each machine, what's already mirrored here vs. only local.

## MIDI controller pass-through (parked 2026-07-20)
Goal: pass the Arturia MiniLab through to `crt-vm` so its pads/knobs can
drive the console (control-file writes, same channel as other HUD input —
see `crt-midi-knobs.py`). **Status when parked**: root cause of the original
failure was found and fixed (Windows had the MiniLab's MIDI interface
disabled, `CM_PROB_DISABLED` in Device Manager — fixed via
`Enable-PnpDevice`), but `VBoxManage usbattach` still fails ("busy with a
previous request") even after that fix and a full VM power-cycle
(`controlvm poweroff` + `startvm`, done live 2026-07-20 for an unrelated
audio issue — didn't clear this either). Points to a stuck VBoxUSB/VBoxSVC
host-proxy state, independent of the PnP fix. **Next step, whenever this is
picked back up**: kill/restart the `VBoxSVC.exe` process tree on dexter (a
process-kill action that needs a human's direct OK — the live VM depends on
it, don't do this mid-session without checking first) and retry
`usbattach`, or fall back to a full dexter reboot if VBoxSVC restart alone
doesn't clear it.

**Direction** (from `BLOCKERS.md`, 2026-07-20): develop this on the
dexter/Windows side for now, but with the explicit long-term intent it
merges back into the bare-metal Linux distro eventually (see README's
"Bare-metal deployment" / "Porting to native Windows later" sections) — so
design/wiring choices made here should stay portable, not lean on anything
Windows-only that would need re-solving on the eventual Linux target.

Deprioritized twice now (2026-07-19 "abandon midi, pick it up later"; parked
again 2026-07-20 to keep this session's live-access time on blockers that
actually cleared) — not on the critical path for the core voice console.

## Local-first STT routing: the actual shape (2026-07-21) — BUILT

Three previously-separate threads turn out to be one architecture, now
that `crt-secretary.py`'s confidence wiring exists (`STT-CONFIDENCE.md`):
`CRT_STT_GATE` decides *whether* an utterance is addressed to the console
at all, `crt-secretary.py`'s playbooks decide whether it can be answered
*without* Claude, and `crt-stt-confidence.py` decides how much to *trust*
a playbook's answer without checking it against Claude every time.

**Chained, 2026-07-21**: `CRT_STT_SINK=secretary` (parallel to the
existing `claude`/`stdout` modes) now routes each gated utterance to
`send_to_secretary()` — a fire-and-forget `Popen` of `crt-secretary.py
<text>`, never blocking the capture loop on a Claude round-trip. Control
keystrokes (yes/no/enter/etc.) still go straight to tmux unchanged, same
as the `claude` sink always did. `SINK` still defaults to `claude` —
this is opt-in, not the new boot default, until a human has run
`secretary` mode live and confirmed playbooks actually fire correctly
against real (not synthetic) transcriptions. 5 new tests
(`tests/test_stt_secretary_sink.py`), full suite green.

Original plan, kept below for reference (now implemented as described):

- Add `CRT_STT_SINK=secretary` to `crt-stt-solo.py`, parallel to the
  existing `claude`/`stdout` modes: same wake-word gate check as today,
  but instead of `send_to_claude(text, key)`, fire-and-forget (`Popen`,
  not `run` — must never block the capture loop on a Claude round-trip)
  a call to `crt-secretary.py <text>`. Control keystrokes (yes/no/enter/
  etc.) still go straight to the tmux pane as today, unchanged — those
  are meta-interactions with whatever's on screen, not routable
  utterances.
- This alone (without any Claude-skipping) makes the STT gate's
  "escalate only when unsure" promise literally true for the first time
  — most matched playbooks answer via TTS/print without ever touching
  the Claude pane, and the confidence wiring above quietly builds
  confirmation data on the ones that do escalate.
- Deliberately NOT the default — `CRT_STT_SINK` stays `claude` until a
  human has run `secretary` mode live and confirmed playbooks actually
  fire correctly against real (not synthetic) transcriptions.

## Speculative/optimistic response — BUILT (v1), 2026-07-21

The "bot starts typing a cheap local guess, then overwrites with the real
answer" idea (see "Interface philosophy" above), distinct from
`crt-predict.py` (which predicts what was *said*) — this predicts
nothing about the response's content, just acknowledges instantly while
the real one is on its way.

**v1 shipped**: `bin/crt-speculate.py`'s `pick_filler_line()` — a random
warm/curious-register filler ("let me think on that...", "one sec,
working on it...", etc.), not yet the per-category buckets the original
sketch floated ("looking that up..." vs. "checking reports..." — a real
simplification, not a broken promise: variety alone already avoids the
single-canned-phrase problem, category-specific fillers are a fine
follow-up, not a requirement). Wired into `crt-secretary.py`'s
Claude-escalation branch (`handle()`, right before `send_to_claude`/
`wait_for_claude_reply`'s real round-trip) via `show_filler_line()`,
which shells to `crt-think.sh` — no true in-place overwrite needed,
`crt-monologue.sh` already only shows the most recent few lines, so the
filler naturally scrolls/fades once the real answer lands after it.
Opt-in (`CRT_SECRETARY_SPECULATE`, default off) — never fires for a
locally-answered playbook, only the genuinely-slow Claude path. 8 new
tests (`tests/test_speculate.py` + `TestSpeculativeFiller` in
`test_secretary.py`), full suite green.

**Not yet live-verified**: nothing types into Claude except by hand/test
today (`CRT_STT_SINK` still defaults to `claude`, not `secretary`), so
this has never been watched against a real Claude round-trip on the
actual screen.

## Relationship to scheduler and aedile — status check (2026-07-21)

Clarifying a framing that's been stated informally but wasn't written down
anywhere: "crt will eventually be a main platform of interfacing with
scheduler, and also aedile." Checked what actually exists today —

- **scheduler**: real but unapplied. crt is registered in scheduler's Tier
  2 nightly batch via `~/Documents/Project Archive/scheduler/schedule/crt.conf`
  (pointed at a local bare git remote), but the classifier still blocks
  writing the `BATCH_JOB_NAME`+`claude -p` line that would actually turn it
  on — see HANDOFF.md's "Autonomous overnight batch" section. Separately,
  `VM-JOBS.md`'s "Wiring the pull into the scheduler" section is about
  hooking crt's VM-side jobs into scheduler's shared infra
  (`morning-report.sh`) — a second, distinct integration point from the
  Tier 2 batch registration above.
- **aedile**: currently zero — no mention of "aedile" anywhere in crt's
  docs or code (`grep -rn aedile *.md .claude/*.md` returns nothing). The
  "interfacing with aedile" idea has no design or code yet; it's an
  intention stated outside crt's own files, not something crt has started
  building toward.
- Scheduler itself now runs a chunk of overnight batch work (aedile's,
  vkv-inventory's) under a separate service account, `svc-vaporwave`
  (`~/Documents/Project Archive/scheduler`'s `.scheduler/FOCUS.md`), on its
  own crontab outside scheduler's normal `schedule/*.conf` dispatch, and
  drops dated markdown status reports in `/srv/vaporwave-reports/<project>/`
  (group-readable by zach). If crt's own Tier 2 batch is ever turned on, it
  would presumably follow the same disposable-clone + report pattern
  rather than the older worktree approach — worth deciding explicitly when
  that happens, not assuming it inherits the pattern by default.

Bottom line: don't treat "crt interfaces with aedile" as a load-bearing
design assumption anywhere yet — it's a stated future direction with no
current plumbing.

## IR blaster mount (cad/CAD-BACKLOG.md)
Parked 2026-07-21 — **updated same day**: the IR blaster itself is still
wanted (it's now load-bearing for the "Channel-confirmation loop" idea
above, replacing the rotary switch), but Chris is explicitly not building
the physical case/mount right now. LED is sourced
(https://www.amazon.com/dp/B099ZJ6555); TV sensor position still not
measured either way. Revisit the case once the channel-confirmation
design is real enough to need physical placement.
