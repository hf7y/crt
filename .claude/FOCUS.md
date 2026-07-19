# crt — focus & backlog

**Current focus: the core STT pipeline.** Everything below the line is
deliberately parked so interactive sessions stay on getting voice→text→Claude
reliable. See `../HANDOFF.md` for full state and access.

## Now (core STT)

- Reliability of detection: confirm the shared-capture + always-on level meter
  fixed the intermittent "stops detecting" (VirtualBox capture going stale).
  If the meter goes flat mid-speech, add a watchdog that re-opens capture.
- The standalone STT view (`bin/crt-stt.sh`) — verify it runs and is useful for
  watching/tuning transcription, decoupled from Claude.
- Ongoing calibration: `CRT_VAD_THRESHOLD`, Windows mic boost, normalization.

## Deferred (not in current focus — do not pull these into an STT session)

These are tracked here so they're not lost. Most are **physical/hardware** and
cannot be done by an autonomous agent — hence this project registers with the
scheduler with autonomous tiers OFF (see `schedule/crt.conf` in the scheduler).

1. **MIDI controller** (Arturia MiniLab mkII, USB 1c75:0289). USB2/EHCI
   passthrough enabled; device was "Captured" by VBox but not enumerating in
   guest ALSA. Goal: pads → Enter/Esc/arrows for prompt control, knobs → scroll.
2. **Physical hookswitch** — handset on-hook/off-hook detection; pads/reed
   switch → mute + pause STT + (stretch) TV power. See `cad/` and README.
3. **OctoPrint** on a spare Raspberry Pi (OctoPi SD already flashed on mandark).
4. **Benchy calibration print** once the Ender 3 SD path is verified (3DBenchy
   STL downloaded on mandark).
5. **USB phone-interface module** — for the bare-metal Intel Compute Stick
   target (no 1/8" jack; audio must go over USB). Composite USB device:
   audio + HID for hookswitch. Ubuntu Server ISO downloaded (32-bit-UEFI quirk).
6. **Stretch: video-call wrapper** (Zoom/WhatsApp) over the handset/CRT.

## To enable autonomous work later

If/when the code-shaped deferred items (e.g. USB-module firmware, a video
wrapper) warrant nightly batches: make this a git repo with a deploy remote,
set `REPO_URL` + a `BATCH_*` tier in `schedule/crt.conf`, and
`bin/sync-crontab.sh --apply`.
