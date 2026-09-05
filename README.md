# crt

Landline handset + CRT monitor as a voice-driven front end for Claude Code,
autobooting on potato, a Raspberry Pi.

## Signal path

```
handset mic (TRRS) --> potato audio in --> whisper (dexter's container, VAD-segmented)
                                                    |
                                                    v
                                        tmux send-keys into `claude` pane
                                                    |
                                                    v
                                          Claude Code CLI on CRT (HDMI->RCA)

hookswitch (mechanical, printed) --> USB keyboard-encoder --> evdev listener
                                                                     |
                                              pause/resume the STT loop
```

## One-time setup (on the console)

```
./install.sh
sudo reboot
```

This installs whisper.cpp + a base.en model, Claude Code CLI, and configures
tty1 to auto-login and drop straight into `bin/crt-console.sh`, which opens a
tmux session: Claude Code in the main pane, `stt-feed.sh` listening in a
lower pane. After reboot, no keyboard interaction is needed to reach the
Claude Code prompt.

First boot: `claude` will need a one-time interactive login (network
required). Do that once before relying on unattended autoboot.

## Manual test (no reboot)

```
bash bin/crt-console.sh
```

## Audio capture troubleshooting

Getting the mic to work took several non-obvious fixes; if a fresh deploy
captures silence, check these in order:

1. **User must be in the `audio` group.** Without a desktop/logind seat (i.e.
   over SSH, or on a stripped console-only box), `/dev/snd/*` is only reachable
   via the `audio` group. `install.sh` adds the user; a re-login/reboot applies
   it. Symptom: `arecord -l` says "no soundcards found" though the kernel shows
   the card in `/proc/asound/cards`.

2. **Capture from the hardware device, not ALSA `default`.** `default` can be
   silently re-routed to a dead PulseAudio/PipeWire by leftover config
   drop-ins. `stt-feed.sh` uses `plughw:0,0` via `CRT_AUDIO_DEV` for this reason.

3. **VAD threshold.** A quiet capture path (speech RMS ~1%) never trips the
   default 3% silence gate; lower it with
   `CRT_VAD_THRESHOLD`. Symptom: `rec` runs forever
   on `utt_1` and never emits a `[stt-feed] ->` line. Verify capture works at
   all by recording directly and transcribing:
   ```
   arecord -D plughw:0,0 -f S16_LE -c1 -r16000 -d 5 /tmp/t.wav
   ~/whisper.cpp/build/bin/whisper-cli -m ~/whisper.cpp/models/ggml-base.en.bin -f /tmp/t.wav -nt -np
   ```

## Hookswitch (physical on/off)

The mechanical hookswitch is **not wired to any analog phone line** — no PBX,
so no relay. It's a plain logic-level contact: wire the microswitch (via
`cad/switch_mount.scad`) to a cheap USB arcade-button/keyboard-encoder
board, configured to emit one key while the switch is closed (handset
resting on the hook).

Setup:
```
evtest                       # find the encoder's device path and confirm the key it sends
export CRT_HOOK_DEVICE=/dev/input/by-id/usb-...-event-kbd
export CRT_HOOK_KEY=KEY_F13  # match whatever the encoder actually sends
```
Add both exports to `.bash_profile` above the `crt autoboot` block (installer
leaves a marker) so they're set before `crt-console.sh` runs. With
`CRT_HOOK_DEVICE` set, autostart opens a third pane running
`hookswitch-listen.sh`, which SIGSTOPs/SIGCONTs `stt-feed.sh` as the handset
is placed down / picked up.

## 3D-printed handset assembly (`cad/`)

Four parametric OpenSCAD parts, one assembly:

- `phone_saddle.scad` — cup the handset barrel rests in ("phone" contact piece)
- `hook_lever.scad` — see-saw lever; handset weight presses it onto the switch
- `switch_mount.scad` — bracket holding the microswitch under the lever
- `cradle.scad` — base body with pivot-pin bosses and switch mount pocket

**Edit `cad/params.scad` first** — measure your actual handset barrel
diameter and your microswitch's real dimensions/hole spacing; the shipped
values are generic placeholders, not measurements of your hardware.

Render all STLs:
```
./cad/export_stl.sh
```
Outputs to `cad/stl/`. Assemble with a steel pin/M4 bolt through the pivot
bosses, then screw the switch into `switch_mount.scad` and tune
`switch_mount_h` in `params.scad` until the lever fully depresses the
plunger only when the handset is resting (not lifted).

## Bare-metal deployment (e.g. Intel Compute Stick)

Everything in `bin/` and `install.sh` targets any Debian/Ubuntu machine, and
the console settled on a Raspberry Pi (potato) rather than a hypervisor guest.

**Confirmed target (2026-07-21): Debian 13.6, amd64.** `install.sh`'s
package list (`build-essential cmake git tmux sox alsa-utils curl
openscad evtest`) is all present in Debian 13's repos under those exact
names — nothing to substitute. If the actual stick's CPU turns out to be
more capable than a Celeron (amd64 covers a wide range), test `base.en`
before defaulting to `tiny.en` below; the tradeoff is real either way,
this isn't a hard requirement, just the safe assumption for the weakest
hardware this doc originally targeted.

**Barcode scanner needs no forwarding at all on a single-box deployment**
(2026-07-21, see `SCANNER.md`'s "compute-stick prep" section) — the whole
`dexter-scanner-forward.ps1` / NAT-forward / `crt-scanner-feed.py`-HTTP
bridge exists only because the VM path splits the scanner (on Windows)
from the console (in the guest). Bare metal has one machine: plug the
USB scanner directly into the stick, and `crt-book-console.py`'s stdin
path (already the primary scan path, `install.sh` wires nothing extra
for it) picks it up with zero network hop.

Differences from the VM path:

- **Whisper model**: `base.en` is too heavy for a Celeron in real time.
  Use the smaller/faster `tiny.en` instead:
  ```
  CRT_WHISPER_MODEL_NAME=tiny.en ./install.sh
  ```
  (`install.sh` downloads whichever model name you pass and wires
  `CRT_WHISPER_MODEL` automatically if it isn't the default `base.en`.)
  Expect a noticeable accuracy drop vs `base.en` — worth testing both if
  the stick can keep up with `base.en` at all before committing to `tiny.en`.
- **Audio input**: most compute sticks expose only HDMI audio out (or a
  single combo headphone/mic jack, sometimes output-only). Check
  `arecord -l` after boot — if there's no capture device, or capture is a
  garbled combo-jack signal, add a cheap USB audio adapter for the TRRS
  handset mic rather than relying on onboard audio in.
- **Video out**: HDMI is typically native on these sticks, so the same
  HDMI→RCA path to the CRT applies unchanged.
- **Everything else** (autologin, tmux wiring, hookswitch evdev listener,
  `crt-console.sh`) is identical — `install.sh` + reboot is the whole setup.
- **Finding it on the network** (2026-07-21): `install.sh` installs
  `avahi-daemon` and sets the hostname (`CRT_HOSTNAME`, default
  `crt-console`), so it's reachable as `crt-console.local` from any
  device on the same LAN segment — no static IP, no router config
  (mDNS/multicast, same mechanism that makes `dexter.local` work).
  Doesn't cross routers/VLANs, though — `crt-console.sh` also flashes
  the box's actual IP on the physical screen for a few seconds at boot
  (`CRT_IP_FLASH_SECS`, default 4, `0` to disable) as a fallback that
  works regardless of network topology.
- **First-boot setup, unattended**: `install.sh` now supports both
  editing its own `CONFIG` block at the top (WiFi SSID/password,
  hostname, Gemini key, Claude credentials path) and answering
  interactive prompts for the same values — including pasting a
  `.credentials.json` directly at the prompt to skip Claude Code's
  one-time login entirely. See that file's own header.

## Porting to native Windows later

The STT/tmux/Claude Code pieces (`bin/`) are Linux-specific (evdev, ALSA,
tmux). Porting means: swap `sox`/`rec` for a Windows-native audio capture,
swap `evtest`/evdev for a Windows raw-HID or keyboard-hook listener for the
hookswitch encoder, and replace tmux + autologin with a Windows Task
Scheduler entry running at logon that opens a terminal into the same
`claude` + STT-feed pair. The whisper.cpp binary and model are portable
as-is (Windows build exists upstream).

## Why this repo is public

Decided 2026-09-05 (hf7y/crt#148): public keeps Actions free for the images
dexter runs, and exposes topology only, never access. The `gitleaks` PR
check is what keeps that true by construction, not by care.
