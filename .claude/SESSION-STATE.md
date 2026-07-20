# Session state (read this first, before STT-MECHANISM.md)

Last updated: 2026-07-19 evening, by a design-focused session (no live VM/
mic access — no new STT transcriptions came in, so no new error-pattern
learning this session; see `STT-MECHANISM.md` + `~/.crt/stt.log` for that
work, still the standing top priority per `CLAUDE.md`).

## What this session did
Chris asked for: (1) an "idle bait" workflow — job reports/blockers
surfaced through the day as cute, low-friction hooks, never naggy enough
he'd turn the TV off, interacted with by picking up the handset; (2)
continued STT refinement (none to do this session — no live traffic);
(3) more expressive earpiece/computer beeps; (4) sidetone investigation;
(5) deeper philosophy digging; (6) keep generating tasks/CAD/RFPs, don't
run dry. All design + scaffolding, **nothing hardware-verified** (no VM
access this session).

## New docs (read these for the actual designs)
- `IDLE-BAIT.md` — the core workflow: report/question sources -> on-screen
  teaser -> earcon (rate-limited, one-shot per item, no nagging) -> pickup
  -> secretary answers by voice. This is the design Chris's mid-session
  note ("cute idle bait... never annoying... he'd turn the TV off")
  directly shaped — that line is close to load-bearing, re-read it if a
  future change threatens to make this feel like a notification badge.
- `SIDETONE.md` — what sidetone is, why it's actually an STT-accuracy
  lever (not cosmetic — ties to VAD-clipping/denoise-distortion failure
  modes in `STT-MECHANISM.md`), and a real open question it surfaced (see
  below).
- `PHILOSOPHY.md` — seven named principles (answer-first-be-right-later,
  cost-of-ignoring-near-zero, restraint-as-trust, verbs-not-menus,
  one-body-several-selves, imperfection-as-character, local-first) plus
  open threads at the bottom worth revisiting.
- `RFP-GALLERY.md`, `RFP-PAYPHONE.md` — design briefs for the two
  gallery/art installation ideas in `PARKING-LOT.md`, fleshed out enough
  to hand to a collaborator. **Payphone brief has a real legal-risk
  section** (real-money payout = gambling device in most jurisdictions) —
  read that before anyone gets excited about the coin mechanism.
- `cad/CAD-BACKLOG.md` — full inventory of printed parts, existing +
  speculative, with what's blocked on what.

## New scripts (all untested against real hardware/audio)
- `bin/crt-earcon.sh` — five tones (bait/question/success/ack/oops) via
  sox synth, routed through the same device logic as `crt-tts.py`
  (dexter bridge for tv/handset, local aplay otherwise).
- `bin/crt-report.sh` — writes `~/reports/crt/LATEST.md` in the
  scheduler's exact shape (see `Project Archive/scheduler`) from inside
  this interactive session, so idle-bait has real content before crt's
  registered-but-dormant nightly Tier 2 batch ever runs. **Already used
  once this session** — `~/reports/crt/2026-07-19.md` has a real entry.
- `bin/crt-idle-teaser.sh` — polling watcher, turns new report/question
  lines into one `crt-think.sh` teaser + (judgment calls only) one earcon.
  Deliberately a separate process from `crt-monologue.sh`, not merged in —
  see `PHILOSOPHY.md`'s open thread on narration vs. restraint.
- `bin/crt-announce.sh` — **bugfix**: was still passing an old `plughw:*`
  guess as the TV device; `crt-tts.py`'s dexter bridge (confirmed working
  via live human test per its own header) expects the literal string
  `"tv"`. Fixed.
- `cad/ir_blaster_mount.scad`, `cad/earcon_grille.scad` — new speculative
  parts, no measurements, see `cad/CAD-BACKLOG.md`.

## Open questions logged (`.claude/QUESTIONS.md`, need Chris)
1. **Is the handset earpiece guest-local ALSA or only host-bridged via
   dexter?** Blocks whether software sidetone is even possible — see
   `SIDETONE.md`. `crt-tts.py`'s `DEXTER_DEVICES` now includes `"handset"`
   alongside `"tv"`, which is a real architecture drift from
   `AUDIO-ROUTING.md`'s original assumption (handset stays guest-local).
   Worth resolving early since it also affects the hardware-sidetone
   recommendation (design the mic/earpiece wiring with a passive tap from
   the start, per `SIDETONE.md` option 1).
2. **Idle-bait quiet hours** — what hours should the earcon go silent?

## Not done / explicitly out of scope this session
- Nothing hardware-verified (no VM/mic/audio access this session at all —
  pure design + scaffolding).
- The secretary wrapper itself (`SECRETARY.md` steps 1-4) — still the
  actual next concrete build once someone's back on the VM; idle-bait is
  the lure toward it, not a replacement for it.
- No STT error-pattern learning (no live transcriptions this session).

## Pick up next, in order
1. Get back on `crt-vm` and answer question #1 above — it gates both
   sidetone and whether `crt-idle-teaser.sh`'s earcon calls will even
   reach the handset correctly.
2. Smoke-test `crt-earcon.sh`'s five tones by ear (nobody has heard them).
3. Run `crt-report.sh` + `crt-idle-teaser.sh` live for a day, see if the
   teaser cadence actually feels like bait or like a nag — this is a
   judgment call only a live test can settle, not more design.
4. Keep building the secretary wrapper (`SECRETARY.md`) — the actual
   payoff once idle-bait gets someone to pick up.
