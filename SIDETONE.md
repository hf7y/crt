# Sidetone

## What it is
On a real telephone, "sidetone" is a small deliberate leak of your own
mic signal back into your own earpiece, so the line doesn't feel dead.
Two effects that matter to us specifically:
1. **Confidence the line is live** — without it, people (subconsciously)
   assume the mic isn't working and either repeat themselves or raise
   their voice.
2. **Natural volume self-regulation** — hearing yourself lets you match
   your voice to the room without thinking about it. Too little sidetone
   and people shout; too much and they whisper. Real phone engineering
   targets a specific *loss* (sidetone is deliberately quieter than your
   real voice, not 1:1) for exactly this reason.

## Why this is an STT-accuracy lever, not just a nice-to-have
Per `CLAUDE.md`, improving STT inference is this console's top priority,
and per `STT-MECHANISM.md`, a chunk of garbling here is plausibly
**VAD clipping quiet speech** and **denoise distorting sibilants** — both
of which get *worse* the quieter/more hesitant someone talks. A noisy
room with no sidetone is exactly the condition that produces the
worst-case input for this pipeline: someone unsure if they're being heard,
talking too quietly (VAD/denoise struggle) or too loud (clipping,
distortion). Sidetone isn't cosmetic here — it's upstream of the actual
transcription-quality problem this project is already trying to solve.

## The complication: where does the handset earpiece actually live?
`AUDIO-ROUTING.md` (written before the dexter bridge existed) assumed the
handset earpiece stays a **guest-local** ALSA device while only the TV
output moves to the host. But `bin/crt-tts.py`'s current `DEXTER_DEVICES`
tuple is `("tv", "handset")` — **both** now route through
`dexter-audio-server.py` over HTTP. That's fine for short TTS clips (a
network POST per phrase is imperceptible), but it's fatal for sidetone,
which needs near-zero latency (a few ms) to feel like your own voice
rather than a laggy echo. A round-trip through dexter would be the worst
possible way to implement this.

**Open question logged to `.claude/QUESTIONS.md`**: is the handset
earpiece physically wired to `crt-vm` (guest-local ALSA, sidetone-feasible
purely in software) or only reachable via dexter's host-side bridge (in
which case software sidetone as described here isn't viable at all,
independent of round-trip cost)? This needs a real answer once the VM/
hardware is reachable, not a guess — `aplay -L` on the guest and physically
tracing the earpiece cable both settle it.

## Recommended approach, in priority order

### 1. Passive hardware sidetone (best: zero latency, zero software)
This is how real phones have always done it — a resistor or small
transformer tap between the mic and earpiece wires, physically upstream
of any USB/VM boundary. If the handset's mic and earpiece are wired
through a simple audio interface (not yet designed — see the hookswitch/
cad work), adding a passive tap here is cheap (~$1 of parts) and has
**zero** latency because it never touches software at all. This is the
right answer if the handset's electrical path is still being designed
(it is — see `cad/` for the mechanical side, no audio wiring plan exists
yet). Worth deciding the mic/earpiece wiring **with sidetone in mind from
the start** rather than retrofitting later.

### 2. Local-only software loopback (fallback, guest-side only)
Only viable if the answer to the open question above is "guest-local
device." A persistent low-level passthrough **inside `crt-vm`**, never
touching the network:
- Cheapest form: a standing `sox -t alsa crtmic -t alsa <earpiece-dev>
  vol 0.15` pipe (or equivalent `arecord | sox ... | aplay` chain),
  started alongside `crt-stt-solo.py`.
- Since `crt-stt-solo.py` already owns the sole mic reader (see
  AUDIO-DEBUG.md — two readers starve each other), sidetone should tap
  the **same** stream it already reads rather than opening a second ALSA
  capture handle. Practically: a low-volume raw (pre-denoise, to keep
  latency minimal — denoise is not free) write-through to the earpiece
  device inside its existing read loop.
- **Must duck automatically** whenever TTS or an earcon is about to play
  on the same device, or the two will fight over a single ALSA sink (and
  briefly, sidetone-of-the-TTS-itself would be an unpleasant echo). A
  simple mute flag set for the duration of `crt-tts.py`/`crt-earcon.sh`
  calls is enough; exact mechanism TBD once device ownership (see above)
  is settled.
- Volume: start around **10-15%** (matches real telephone engineering's
  "quieter than your real voice" target) — pure guess, needs a human ear
  to tune, same caveat as `crt-tts-calibrate.py`.

### 3. Not recommended: routing sidetone through the dexter bridge
Explicitly ruled out above (latency). Noted only so a future session
doesn't reinvent it and rediscover the same problem.

## Status
Design only — nothing built. Next concrete step is the open question
(guest-local vs. host-bridged handset audio), which determines whether
option 1 or 2 is even on the table; option 1 is preferable regardless and
should be decided before any more handset audio wiring happens.
