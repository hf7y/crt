# Hookswitch: behavior spec

The physical embodiment of `PHILOSOPHY.md` #4 (verbs, not menus) — per
`PARKING-LOT.md`, this is the **primary** interface hardware, ahead of the
CRT or any knob. Formalizing the intended behavior here so
`bin/hookswitch-listen.sh` has a spec to be checked against, not just
whatever the first draft happened to do.

## States
- **On-hook** (handset resting, switch closed): STT paused. This is the
  console's resting state — inert, not listening, matching
  `PARKING-LOT.md`'s RF-power-on vision where resting = actually off/idle,
  not silently-still-recording standby.
- **Off-hook** (handset lifted, switch open): STT active, listening.
- **Transition (bounce)**: a mechanical switch does not move cleanly
  between states — it chatters for a few milliseconds. Untreated, this
  looks like a rapid sequence of on/off events to software.

## The bug this session found (no hardware needed to find it)
`hookswitch-listen.sh` currently maps the encoder's raw key-value events
straight to `pkill -STOP`/`pkill -CONT` with **no debounce**. A single
physical pickup/hangup can plausibly emit several bounced transitions
within a few milliseconds — each one now fires a real STOP/CONT signal at
`stt-feed.sh`. Best case this is just wasted signals; worst case a STOP
lands after the matching CONT (reordered by process scheduling) and the
STT process ends up stopped when the handset is actually off-hook, i.e.
**the console silently stops listening while looking like it's on**. This
is a genuine correctness bug reachable and fixable without any hardware —
software debounce is pure logic.

## Fix: debounce
Only act on a transition once the new state has held steady for a short
window (`CRT_HOOK_DEBOUNCE_MS`, default 50ms — mechanical switch bounce
is typically single-digit milliseconds, 50ms leaves comfortable margin
without adding perceptible lag to a real pickup). Implementation: track
the last-applied state and a pending-since timestamp; only call
`pkill -STOP`/`-CONT` when the raw signal has been consistent for the
full debounce window, collapsing any bounce train into exactly one action.

## Future states (not built, no hardware to build against yet)
- **Long off-hook, no speech** (idle timeout while lifted) — should this
  eventually re-mute STT and treat it like on-hook again, or stay
  listening indefinitely? Real question, no answer yet — flagging so it's
  not silently decided by whatever `crt-stt-solo.py`'s VAD timeout happens
  to do.
- **Quick on-hook/off-hook/on-hook** ("hang up, immediately pick back up")
  — is this a meaningful gesture (e.g. "never mind, restart") or just
  noise? Real telephones don't assign it meaning either; probably fine to
  leave unassigned, noting it here so it's a decision, not an oversight.
- **Persona-channel knob interaction** (`vault:crt/PERSONA-CHANNEL.md`) — the
  hookswitch and the channel knob are two independent physical inputs;
  worth deciding whether turning the channel knob while on-hook should do
  anything (probably not — picking up is still the actual "begin"
  gesture) versus off-hook (switching persona mid-call).

## Status
Debounce logic added to `hookswitch-listen.sh` this session (2026-07-19),
covered by a synthetic bounce-sequence test in `tests/`. Everything else
above is unbuilt/unverified — no physical switch to test bounce timing
against in reality, 50ms is a reasoned guess, not a measurement.

**2026-09-06:** option 3's software half (`CRT_HOOK_TRANSPORT=gpio`) is built and
tested against a fake sysfs tree; real wiring and option 1's hard-kill remain hardware-only.

## Wiring/kill options for the physical switch (design writeup, 2026-07-24)

Filed originally in scheduler's `BLOCKERS.md` as "the handset's 3-pin
switch" once `cad/HANDSET-MEASUREMENTS.md`'s handset part was confirmed
function-complete; routed here after a process correction (BLOCKERS.md
is human-only blockers, not a work queue this project's batch reads —
see that file's own crt entry). **Confirmed same mechanism, not a
distinct one**: `cad/params.scad`'s "Microswitch (measured: 3-pin lever
subminiature microswitch)" block and `cad/switch_mount.scad` ("bracket
holding a mini SPST/SPDT microswitch") are the switch `hook_lever.scad`
presses and `bin/hookswitch-listen.sh` already reads — this doc is that
switch's software/hardware wiring question, not a second hookswitch.

A 3-pin lever microswitch is a single-pole double-throw (SPDT): one COM
pin, plus NO (normally-open) and NC (normally-closed) pins relative to
the lever's rest position. Which pole gets wired, and what it's wired
*to*, is the actual decision — three real options:

**1. Hard-kill audio (electrical cut in the analog/USB audio path).**
Wire the switch inline with the handset mic's power or signal line
itself (e.g. cutting the USB audio interface's mic-in conductor, or a
relay/analog switch gated by the mechanical switch) so on-hook
physically silences capture with no software involved.
- Makes possible: the strongest privacy guarantee in the whole project —
  on-hook means the mic is physically incapable of picking up audio, not
  just "software chose not to record it." Directly matches
  `HOOKSWITCH.md`'s own on-hook framing ("resting = actually off/idle,
  not silently-still-recording standby") at the hardware level instead
  of trusting a process.
- Costs: needs real analog work (identifying which conductor to cut on
  the specific USB audio interface in use, possibly adding a small relay
  or FET switch and its own power), is the least reversible/most fiddly
  to prototype, and gives no soft states — there's no way to build the
  "future states" HOOKSWITCH.md already flags (long-off-hook idle
  timeout, quick-cycle gesture) on top of a hard electrical cut, since
  software never sees the transition at all past the initial event.

**2. Software mute on switch-close (extends the existing path).**
`bin/hookswitch-listen.sh` already does a version of this today — the
switch is wired to a cheap USB HID encoder board (logic-level signal,
not a load), and on-hook sends `pkill -STOP` to `stt-feed.sh` /
off-hook sends `-CONT`, with the debounce logic above. This option is
"keep that architecture," just naming it explicitly as a chosen
destination rather than a placeholder.
- Makes possible: everything already built stays valid (debounce test,
  `apply_state()`/`debounce_loop()` split for testability) with zero new
  hardware. It's also the only option that can cleanly grow into the
  "Future states" section above (idle-timeout re-mute, gesture handling)
  since software already sees every transition, not just an on/off edge.
- Costs: on-hook silence is a promise from a running process, not a
  physical fact — a hung/crashed `hookswitch-listen.sh`, or a race with
  `stt-feed.sh` restarting, could leave capture running while the
  handset looks safely hung up. This is exactly the class of bug
  `HOOKSWITCH.md`'s "bug this session found" section already found once
  (bounce reordering STOP-after-CONT) — software mute is provably
  correct only as far as its own test coverage reaches, not by
  construction.

**3. Pi GPIO signal into existing logic (bypass the USB HID encoder).**
Wire the switch's COM+NO (or NC) pins directly to two Pi GPIO pins
(one ground-referenced, with the Pi's internal pull-up/pull-down),
read the transition via `gpiozero`/`RPi.GPIO`/sysfs instead of an
`evtest`-parsed HID key stream, but keep the same debounce +
`apply_state()` shape.
- Makes possible: removes a whole hardware link (the USB HID encoder
  board) some cost/reliability, and unlocks reading the switch as a
  clean digital GPIO edge with the Pi's own hardware debounce
  primitives available as a second line of defense alongside the
  existing software debounce. Also opens the door to GPIO doing more
  than just this one switch later (e.g. the same board could host other
  buttons) without adding more USB HID hardware per input.
- Costs: swaps a `evtest`/HID-parsing bug class for a GPIO-wiring bug
  class (pull-up/pull-down direction, 3.3V logic level compatibility if
  the switch/board isn't already 3.3V-safe, physical wiring to header
  pins instead of a plug-and-play USB board) — real rework of
  `hookswitch-listen.sh`'s input layer, though `apply_state()`/
  `debounce_loop()`'s core logic and its existing test
  (`tests/test_hookswitch_debounce.sh`) can very likely be reused
  mostly as-is since they already operate on abstract "on"/"off" pending
  values, not HID-specific parsing.

**No recommendation made here on purpose** (Zach's call, same posture
`vault:crt/RFP-GALLERY.md`'s architecture writeup used) — options 2 and 3 are not
mutually exclusive with each other (3 is really "how option 2 gets its
raw signal"), while option 1 is a genuinely different, stronger-but-
costlier guarantee that could also be layered *underneath* either 2 or 3
later (hard-kill as a fail-safe, software mute as the primary/testable
path) rather than picked instead of them. No hardware access was needed
or used for this writeup — a live session is what's needed to actually
test switch-body pinout (COM/NO/NC continuity with a multimeter) before
any of these can be wired for real.
