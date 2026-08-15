# Parking lot -- retired 2026-08-14, migrated to GitHub issues

**Parked ideas now live at https://github.com/hf7y/crt/issues.** Same
migration as `.scheduler/FOCUS.md` and `.scheduler/QUESTIONS.md`
(`hf7y/scheduler#66`, `hf7y/realisateur#230`, root cause
`hf7y/realisateur#187`). This file is a pointer, not a second source of
truth. Do not park anything here -- file an issue and say in it that it is
parked.

Parked is a real state and it is worth keeping: this file existed so that a
direction not being built now would not be lost. An issue holds that just as
well, and unlike this file it surfaces when someone lists the backlog.

## Where the ideas went

| Was | Now |
|---|---|
| IR blaster: TV power-on, persona-as-channel, channel-confirmation loop | [#32](https://github.com/hf7y/crt/issues/32) -- includes the HDMI-to-RF multi-channel half, whose remaining blocker is mounting, not sourcing |
| Interface philosophy: blinking cursor, hide the raw transcript | [#33](https://github.com/hf7y/crt/issues/33) |
| "next" meaning skip-the-song per persona | [#34](https://github.com/hf7y/crt/issues/34) -- the concrete word collision was already mitigated; the design question is what is open |
| crt as a delivery surface for scheduler reports and questions | [#35](https://github.com/hf7y/crt/issues/35) |
| Speculative/optimistic response (v1 built, still off by default) | [#36](https://github.com/hf7y/crt/issues/36) |
| IR blaster mount (`cad/CAD-BACKLOG.md`) | folded into [#32](https://github.com/hf7y/crt/issues/32) |

## What was NOT migrated, and why

- **Local-first STT routing (`CRT_STT_SINK=secretary`).** The entry says
  "deliberately NOT the default." It **is** the default now --
  `bin/crt-console.sh` launches the engine with `CRT_STT_SINK=secretary`
  (Zach's direct call, 2026-07-21). Built, adopted, done.
- **Media playback, one of the two declared primary jobs.**
  `bin/crt-media-player.py` v1 is built, tested and wired into
  `crt-secretary.py` as a `media` playbook. Only the persona question (#34)
  survives.
- **MIDI controller pass-through.** Parked against `crt-vm` and a stuck
  `VBoxUSB`/`VBoxSVC` state on a Windows VM that no longer exists -- the
  console is bare-metal potato. `bin/crt-midi-knobs.py` is still here; if the
  MiniLab is ever wanted again, that is a fresh problem on Linux, not this
  one. `PARKING-LOT.md` itself recorded MIDI as deprioritized twice.
- **Code consolidation across dexter / the VM / mandark.** Done by the
  refactor sweep: `bin/dexter-*.py`, `bin/crt-sync-vm*.sh`, `bin/crt-vm-*.sh`
  and `systemd/crt-vm-*` are all gone, and this repo is the single source.
- **Deployment sequencing (dexter first, then the Intel Compute Stick once a
  DAC arrives).** Overtaken by events -- the console runs on potato. Whether
  that box stays is [#12](https://github.com/hf7y/crt/issues/12);
  `COMPUTE-STICK-MIGRATION.md` still holds the stick's own notes.
- **Gallery answering machines and the coin-operated payphone.** Both have
  their own live briefs, `RFP-GALLERY.md` and `RFP-PAYPHONE.md`, which are
  where the direction actually lives. Distinct installations, not this
  console's backlog.
- **Video cast to the CRT.** Scoped in `VIDEO-CAST.md`, and
  `bin/crt-cast-sink.py` is built.
- **The scheduler/aedile relationship status check (2026-07-21).** A snapshot
  of what existed then, and stale in both halves: crt is a dispatching
  participant now, and "crt interfaces with aedile" still has no plumbing --
  which was the entry's own conclusion. The live half of the idea is #35.
- **The handset-and-hookswitch-are-primary statement.** Not a work item; it is
  the project's interaction model, and it belongs with `HOOKSWITCH.md` and
  `SECRETARY.md`, which say it.

Full history -- the original 286 lines, including the RF-vs-IR correction, the
rotary-switch supersession, and the VBoxSVC debugging trail -- is in git
before this commit. The vault holds an archived snapshot at
`crt/PARKING-LOT.md`.
