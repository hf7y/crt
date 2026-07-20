# Video cast to CRT

Later goal, named in `DEVELOPMENT-WORKFLOW.md` without a design; scoped
2026-07-20.

## One-line pitch
Cast video to the CRT from another device on the network, easily —
"play the thing" extended beyond the two original PARKING-LOT.md jobs
(morning reports, media playback) to include an arbitrary other-device
source, not just local files/streams crt already owns.

## Confirmed direction (2026-07-20)
- **Source device**: something else on the network, not crt/dexter/the VM
  themselves — this is about receiving a cast, not originating one.
- **Playback engine**: likely VLC-based on the receiving end (matches
  `PARKING-LOT.md`'s existing "play media" job, which already assumed
  VLC/ffmpeg-class tooling).
- **Two delivery shapes, both worth having, picked by whichever's better
  for the moment's latency needs**:
  1. **Shared-file access** — crt/the VM reaches into a shared drive/
     network location and plays a file directly (higher latency-tolerant,
     simpler, works for "cast this recording").
  2. **Live streaming** — the source device streams to crt in real time
     (lower latency, needed for "watch this live," more moving parts).
  Not an either/or — both should exist as options, chosen per use case.
- **Priority: medium.** Not urgent relative to the rest of the backlog,
  but real enough to design properly once picked up, not a stretch/maybe.

## Open (not designed yet)
- Which network protocol/mechanism actually carries the stream (DLNA/
  UPnP casting, a simple VLC-to-VLC stream, a Chromecast-alike receiver,
  or something simpler like `cvlc` pulling an SMB/NFS share) — needs a
  real technical scoping pass once this is actually picked up, not
  guessed here.
- How this interacts with the persona-channel idea (`PERSONA-CHANNEL.md`)
  — is "watch a cast" its own channel position, or does it live outside
  that taxonomy entirely (more like an OS-level mode than a persona)?
- Whether crt's own display (the CRT itself, at whatever resolution
  `DISPLAY-CALIBRATION.md`'s overscan work settles on) needs any special
  handling for video vs. its usual text/graphics use, or whether it's a
  clean handoff (video takes the whole screen, crt's own UI pauses).

## Status
Scoped, not designed in technical detail, not started. Medium priority —
revisit with a real technical pass once it's actually next in line.
