# Development workflow: the vision, tied together

Index doc, not a new design — everything here was built/decided across
this session's docs; this just states the shape of the whole system in
one place. Read the linked doc for depth on any one piece.

## Three tiers of autonomy
1. **Mandark disposable-clone batch** (existing, working) —
   `nightly-batch.md`, registered in `schedule/crt.conf`, code-shaped work
   only, explicitly cannot touch the VM or dexter. **It also cannot write
   `.claude/`** — refused as a sensitive path on four consecutive cycles
   (2026-07-24 through 2026-07-25), which makes the skill's own
   "keep `.claude/FOCUS.md` current" instruction unsatisfiable from this
   tier. `BATCH-NOTES.md` (repo root, 2026-07-25) is where it stages
   entries bound for `.claude/QUESTIONS.md`/`FOCUS.md` instead; fold them
   in from an interactive session and delete them from there.
2. **VM-resident hardware check** (new, `VM-JOBS.md`) — a systemd timer
   running `claude -p` directly on crt-vm, real mic/display/printer
   access, narrow scope: verify what can be mechanically verified, report
   honestly on what still needs a human. Not installed yet.
3. **Interactive sessions** (this one, and future ones like it) — design,
   judgment calls, anything needing a human's ear/eye/decision. Also
   where the **supervisor** (`SUPERVISOR.md`) increasingly takes over the
   routine 90% of what used to require a full interactive Claude Code
   turn — the playbook registry in `crt-secretary.py` is the seed of
   that; every playbook added shrinks how much of "interactive" actually
   needs a real Claude Code call at all.

## Scheduler wiring done this session
`schedule/crt.conf` now has a `DEPLOY_FRESH_CMD`/`DEPLOY_CMD` pair
(reusing the existing generic staleness-probe hook `morning-report.sh`
already had for other projects) that surfaces a stale/missing
VM-report-sync in the daily aggregate. This does **not** run the sync
automatically — it makes the need visible, same as every other project's
use of that hook. Actually running `bin/crt-sync-vm-reports.sh` on a
schedule (vs. surfacing that it's needed) is a separate, not-yet-made
decision — see `VM-JOBS.md`'s open item on how the VM's report content
should actually merge into what `morning-report.sh` shows.

## The graphics/interface thread
- **Terminal rendering** (mic meter, text, layout) — auto-detects real
  terminal size now instead of assuming 40x15 (this session's fix,
  covered by `tests/test_pager.py`).
- **Physical overscan** (VM output overshoots the CRT bezel, 800x600
  undershoots) — `DISPLAY-CALIBRATION.md`'s two-lever answer: a real
  VBox resolution fix (needs dexter access) plus a software safe-margin
  inset that works regardless (`crt-calibrate-display.py`, built +
  tested, not yet wired into what it's supposed to protect — see that
  doc's "not done" section).
- **Tone as a presentation dimension** — `EXPRESSIVE-TONE.md`'s register
  taxonomy (fade length + pitch contour + line brevity as one shared
  emotional dial), `SIDEBAND.md`'s continuous ambient-state channel, both
  extending the existing `crt-earcon.sh`/`SIDETONE.md` audio work.

## Ritual modes (the "ask for my morning report" shape)
`IDLE-BAIT.md` (teaser -> pickup -> secretary payoff) and
`PERSONA-CHANNEL.md` (a real knob as the channel-switch ritual) are both
instances of the same underlying idea: **an interaction should feel like
a small game with a physical verb, not a menu**. The calibration flow
above is a third instance of the same shape, not a one-off — worth
treating "ritual game" as a real design pattern to reach for whenever a
new interaction is being designed, not just a one-time trick.

## Later goals, named but not designed deeply this session
- **Cast video to the CRT from another device.** No design work done —
  flagging the shape of the problem for whenever it's picked up: this is
  a receiver problem (something on the dexter/VM side needs to accept an
  incoming stream), likely orthogonal to everything else in this repo
  (STT/TTS/hookswitch), probably its own small service rather than
  something woven through the existing scripts. Worth scoping properly
  once it's actually next, not guessed at now.
- **Intel Compute Stick migration.** Already tracked (`README.md`'s
  bare-metal section, `FOCUS.md`), unchanged this session — blocked on a
  DAC and physical access, nothing new to add.

## What actually needs a human next (the real punch list)
Everything below needs either VM/hardware access or a judgment call —
nothing further is buildable purely offline right now:
1. Install + run the VM-resident hardware check once (`VM-JOBS.md`).
2. Decide the report-merge question (`VM-JOBS.md`'s open item).
3. Hear the earcons, sidetone, and sideband tones with an actual ear.
4. Play the calibration game for real (`DISPLAY-CALIBRATION.md`).
5. Answer the two open `.claude/QUESTIONS.md` items (handset audio
   routing, idle-bait quiet hours) — the hardware check job is written to
   attempt the first one itself, see `vm-hardware-check.md` step 3.
