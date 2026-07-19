# Separating TV audio vs handset earpiece output

Goal: TTS meant for **Chris** (spoken through the room, e.g. a job needs his
input) should come out the **TV speakers**; TTS meant for the **phone user**
(secretary replies, confirmations) should come out the **handset earpiece**
only. Two different audio sinks, chosen per-message, playing at the same time
potentially.

**Not yet hardware-verified — this is a design + script scaffold** written
without VM/dexter access. Confirm every device name below with `aplay -L`
once the VM is reachable.

## Why this is probably a host (Windows/dexter), not guest (VM), problem

VirtualBox gives a guest **one** virtual audio controller (HDA or AC97) that
maps to **one** host output device at a time (set in VM Settings -> Audio, or
`VBoxManage modifyvm --audioout`). The guest's ALSA layer can see multiple
*virtual* PCM devices, but they all ultimately go out that single host sink.
So two genuinely separate physical destinations (TV HDMI audio vs a USB/3.5mm
handset earpiece) most likely can't both be reached from *inside* the guest
at once with stock VBox audio.

Two ways to actually get two destinations:

### Option 1 (likely correct): earpiece audio stays in the guest, TV audio moves to the host
- The handset earpiece is presumably USB or routed through the VM's existing
  capture/playback path already used for STT -> keep secretary replies going
  out the guest's normal ALSA device as today.
- For the TV: don't play it from inside the VM at all. Have the **host**
  (dexter, Windows) speak it directly to the TV's HDMI audio device. This
  sidesteps VBox's single-audio-sink limit entirely, and Windows already
  supports multiple simultaneous output devices (TV over HDMI, headset over
  USB/3.5mm) independently.
- Mechanism: the guest can't reach Windows directly for this without a
  network hop. Options, cheapest first:
  1. **SSH back to dexter from inside the guest** and run a Windows TTS
     command targeting the TV's audio device (PowerShell `Add-Type` +
     `System.Speech.Synthesis.SpeechSynthesizer`, or `SetAudioDevice`-style
     tools). Requires a passwordless key from guest -> host (currently we
     only have host -> guest and mandark -> host).
  2. **A tiny TCP/HTTP listener on dexter** (PowerShell or a small Python
     service) that the guest posts short strings to; the listener speaks them
     via Windows TTS to a hard-coded TV output device. Lower latency, no SSH
     round-trip, no new host credentials for the guest.
  3. **Shared file + polling** (simplest, ugliest): guest writes the message
     to a file on a shared/mounted path; a small watcher script on dexter
     tails it and speaks new lines. No network code at all, but adds latency
     and a moving part (the watcher must be running / autostarted on dexter).
- `crt-announce.sh` (this repo, `bin/`) already implements the rate limiting
  and calls `crt-tts.py --device <TV device>` — today that only works if run
  *on a machine that can reach the TV output directly*. Until one of the
  above bridges exists, treat `crt-announce.sh` as ready-but-inert for the
  cross-VM-boundary case; it works fine today for two different *guest-side*
  ALSA devices if the hardware ever supports that (e.g. bare-metal compute
  stick with two independent outputs).

### Option 2: VirtualBox multi-controller trick (probably not supported)
VBox does not support attaching two independent audio controllers with
different host device targets to one VM through the normal UI/CLI. Not worth
pursuing over Option 1.

## Dead end tried (2026-07-19): PowerShell + raw COM PolicyConfig
Attempted to switch Windows' default playback device from PowerShell using the
well-known undocumented `IPolicyConfig`/`IMMDeviceEnumerator` COM interfaces
(no module install needed, in theory). `Add-Type`-compiled the interfaces,
created the coclasses via `[Activator]::CreateInstance([Type]::GetTypeFromCLSID(...))`,
then cast to the interface — the cast (`-as` and explicit `[Interface]$obj`)
**reproducibly fails** ("Cannot convert System.__ComObject ... to type
IMMDeviceEnumerator"), even in `-STA` mode, with GUIDs verified correct against
the Windows SDK headers. Not worth further time here. Two more promising
options if this is revisited: (1) a real compiled C# EXE (`csc.exe` or
`dotnet build`) instead of dynamic in-session `Add-Type` — QueryInterface
sometimes behaves differently for dynamically compiled vs. statically compiled
interop assemblies; (2) `nircmd.exe` (NirSoft), a ~200KB single EXE with a
`setdefaultsounddevice` command — trivial and known-reliable, just needs the
user's OK to fetch a third-party binary onto their machine.

`Install-Module AudioDeviceCmdlets` also failed here (`Install-NuGetClientBinaries`
null-ref — PowerShellGet's bundled NuGet provider is broken/missing on this
Windows install, independent of the COM issue above).

## Recommended next step once dexter is reachable
1. `aplay -L` on the guest — confirm what's currently available (likely just
   one device).
2. On dexter: `Get-AudioDevice -List` (AudioDeviceCmdlets module, or just
   Windows Sound settings) to enumerate the TV's HDMI output name and the
   headset/handset's device name.
3. Pick bridge mechanism 1 or 2 above (2 — small always-on Windows listener —
   is probably least fragile since it doesn't need new SSH credentials or a
   shared filesystem). Prototype as `dexter-tts-listener.ps1` (not yet
   written; do this once we can test against the real device list).
4. Wire `crt-announce.sh`'s TV path to post to that listener instead of
   `aplay` directly when running inside the guest.

## Ringing the TV (attention chime before a spoken announcement)
Simplest: from dexter, play a short WAV/tone via
`[System.Media.SoundPlayer]` or `(New-Object Media.SoundPlayer 'chime.wav').PlaySync()`
targeted at the TV's HDMI output (set as Windows default device, or via
AudioDeviceCmdlets' per-app override) immediately before the TTS line, so
Chris hears a chime -> then the spoken request. Needs the same host-side
listener from Option 1 mechanism 2 to be triggerable from the guest.
