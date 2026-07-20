# Questions for the user

Running log, appended to (never overwritten or trimmed) by `/bug-sweep`
and `/nightly-batch` whenever something bigger than a routine tracker note
comes up. Clear an entry by deleting its line once you've actually read
and dealt with it; that's the only thing that should ever remove
something from this file.

- **2026-07-19 (design session): is the handset earpiece wired to `crt-vm`
  (guest-local ALSA) or only reachable via dexter's host-side audio
  bridge?** `crt-tts.py`'s `DEXTER_DEVICES` now includes `"handset"`
  alongside `"tv"`, meaning both currently route through
  `dexter-audio-server.py` over HTTP. That's fine for short TTS clips but
  rules out software sidetone (needs near-zero latency — see
  `SIDETONE.md`). Settle by checking `aplay -L` on the guest and tracing
  the earpiece cable once the VM is reachable.
  > (answer inline here)

- **2026-07-19 (design session): idle-bait quiet hours?** What hours
  should idle-bait audio cues (`IDLE-BAIT.md`) go silent? Screen teaser
  can still update; only the earcon needs a curfew.
  > (answer inline here)
