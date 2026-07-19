# Audio capture debugging — the "stops detecting" bug

The recurring failure: STT works, then mid-session the mic signal goes quiet
with the ALSA mixer still correct — VirtualBox's emulated capture goes **stale**
when the capture device is opened/closed repeatedly (per-utterance) or when a
second reader (the dsnoop meter) starves the primary. Symptoms and the two
already-shipped mitigations are documented in `README.md` and `HANDOFF.md`.

This file tracks **multiple independent angles of attack** so they can be built
and tested in parallel (interactive sessions on the VM, plus overnight batches
that advance the code). Each approach is opt-in and does not disturb the working
pipeline. **None of these are hardware-verified yet** — they were written on the
dev box (mandark), which has no handset/VM. Each needs a run on `crt-vm`.

## Status legend
`[code]` implemented, needs VM test · `[partial]` scaffolded · `[idea]` sketch only

---

## Approach A — capture watchdog (auto re-open) `[code]`
`bin/crt-capture-watchdog.sh`

The narrowest fix for the exact reported symptom. A background daemon holds one
continuous reader on the mic and computes a rolling level. If the signal stays
**flat** (near-zero peak variance) for `CRT_WD_FLAT_SECS` — i.e. the capture has
gone stale, not merely silent — it declares the device dead and **recovers**:
kills stale `arecord`/`sox` holders, re-asserts the mixer (Input Source=Line,
Capture 100%), and (opt-in) restarts the `stt` tmux window so `stt-feed.sh`
re-opens a fresh capture. Logs every event to `~/.crt/watchdog.log` so the
failure cadence can be characterized.

Test: run alongside the normal console; force staleness (let it idle, or toggle
the VBox audio controller) and confirm it recovers within a few seconds.

## Approach B — single-reader console (eliminate dsnoop) `[code]`
`bin/crt-stt-solo.py` extended with `CRT_STT_SINK=claude` + `bin/crt-console-solo.sh`

Root-cause structural fix: the staleness class that comes from *multiple readers*
(meter + stt-feed both on dsnoop) simply cannot happen if exactly **one** process
ever touches the mic. `crt-stt-solo.py` already is that one process for STT-only;
extending it to also type into the Claude tmux pane (and mirror the meter to a
side pane via a fifo) makes it a drop-in replacement for the whole
stt-feed + dsnoop-meter stack. `bin/crt-console-solo.sh` wires it up.

Test: boot with `CRT_CONSOLE=solo` (or run `bin/crt-console-solo.sh`); confirm
voice still types into Claude and the meter still shows, with no dsnoop in play.

## Approach C — proactive keep-alive heartbeat `[code]`
Built into Approach A's watchdog as `CRT_WD_KEEPALIVE=1`

Rather than only reacting to staleness, periodically nudge the emulated ADC so it
never goes cold: the watchdog's single always-open stream is itself a keep-warm;
with keepalive on it additionally re-asserts the mixer every `CRT_WD_KEEPALIVE_SECS`
even when the signal looks fine. Cheap insurance; may make A's reactive path rare.

## Approach D — audio doctor / liveness telemetry `[code]`
`bin/crt-audio-doctor.sh`

Research instrument, not a fix. Two modes: `check` (one-shot health report — lists
cards, the Input Source/Capture mixer state, and a 3 s live RMS/peak sample, exit
non-zero if dead) and `monitor` (append a timestamped RMS/peak sample every N s to
a CSV, so a whole session's capture behaviour can be plotted afterwards). The goal
is to answer the open question: does staleness correlate with idle time, with
utterance boundaries, or with a fixed interval? That determines which of A/B/C is
the real fix vs a band-aid.

Test: `bin/crt-audio-doctor.sh check`; `bin/crt-audio-doctor.sh monitor` during a
session, then inspect `~/.crt/liveness.csv`.

## Approach E — capture-backend variants `[idea]`
Config-only alternatives to try when A–D don't fully settle it:
- **arecord buffer tuning**: `--buffer-size`/`--period-size`/`-F` to avoid xruns
  that may trigger the VBox stall; try larger buffers.
- **Different PCM path**: `hw:0,0` vs `plughw:0,0` vs a fresh `dsnoop`/`dmix`
  rate-matched to 16 kHz to avoid the plug plugin's resample churn.
- **PipeWire/`parecord`** as the capture source instead of raw ALSA, letting the
  guest audio server own the device lifecycle.
- **VirtualBox audio backend**: try `--audiocontroller hda` vs `ac97`, and the
  host audio driver, from the dexter side (VBoxManage). Host-side, needs dexter.

These are enumerated so an overnight job (or a VM session) can pick one, wire a
toggle, and measure with Approach D — not to be all built blindly.

---

## How the overnight batch should use this
Advance approaches marked `[idea]`/`[partial]` toward `[code]`, or harden the
`[code]` ones (edge cases, logging, a test harness). Do **not** claim any of them
hardware-verified — that requires a human on the VM. Prefer breadth across
approaches over depth on one.
