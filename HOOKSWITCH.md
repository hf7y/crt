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
- **Persona-channel knob interaction** (`PERSONA-CHANNEL.md`) — the
  hookswitch and the channel knob are two independent physical inputs;
  worth deciding whether turning the channel knob while on-hook should do
  anything (probably not — picking up is still the actual "begin"
  gesture) versus off-hook (switching persona mid-call).

## Status
Debounce logic added to `hookswitch-listen.sh` this session (2026-07-19),
covered by a synthetic bounce-sequence test in `tests/`. Everything else
above is unbuilt/unverified — no physical switch to test bounce timing
against in reality, 50ms is a reasoned guess, not a measurement.
