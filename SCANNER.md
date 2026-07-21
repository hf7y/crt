# USB 1D barcode scanner: dexter -> crt-vm forwarding

A USB 1D barcode scanner is plugged into `dexter` (not the VM -- dexter's
USB passthrough to `crt-vm` was never set up for this device, and the
scanner enumerates as a keyboard, which passthrough would make worse, not
better). It forwards scans to `crt-vm` over the network instead, arriving
in the tmux Claude Code pane the same way STT transcriptions do -- see
`STT-MECHANISM.md` for that parallel pipeline.

## Why the crossing is this way round
Every other host/guest bridge in this repo (`dexter-whisper-server.py`,
`dexter-audio-server.py`) has the **guest calling dexter**. This one is
backwards: the hardware is on dexter, so dexter has to push to the guest.
That needed a new inbound NAT rule (guest calls out through NAT for free;
nothing could reach IN to the guest before this for a new port).

## Pieces
1. **`bin/dexter-scanner-forward.ps1`** (runs on dexter, native Windows
   PowerShell). Confirmed the scanner is a generic HID-keyboard-emulation
   device, `HID\VID_0145&PID_0012` (checked via `Get-PnpDevice -PresentOnly
   | Where Class -eq HIDClass`, 2026-07-21) -- it types like a real
   keyboard wherever focus happens to be (confirmed the hard way: an early
   real scan landed as literal keystrokes in crt-vm's tmux pane because the
   VirtualBox GUI window happened to have focus on dexter's desktop --
   not a reliable path). Instead this script uses the Win32 RawInput API
   (`RegisterRawInputDevices` + `RIDEV_INPUTSINK` via an `IMessageFilter`)
   to read raw keyboard input system-wide and filters by device handle to
   just this VID/PID, so a human typing at dexter's real keyboard is never
   captured. Assembles characters into a line, and on Enter (end of
   barcode) POSTs `{"text": "..."}` to crt-vm.
   - Everything (raw-input interop, the message filter, the HTTP POST)
     lives in a single `Add-Type` C# block. An earlier version split the
     message filter into a PowerShell `class` deriving from a type loaded
     via `Add-Type` in the same script -- PowerShell parses the whole
     script, including class definitions, before any statement (including
     the `Add-Type` call) runs, so the base type wasn't resolvable yet and
     every such class failed to parse. Doing it all in C# sidesteps that.
   - **STATUS: load-tested and confirmed working live, 2026-07-21.**
   - Installed to autostart via Windows Task Scheduler, task
     `CrtScannerForward`, trigger "at logon" (`Register-ScheduledTask`,
     confirmed `State: Ready`). Runs
     `powershell -ExecutionPolicy Bypass -NoProfile -File
     C:\Users\Zach\dexter-scanner-forward.ps1`. Note the deployed copy
     lives flat in `C:\Users\Zach\` (dexter has no `crt\` subdirectory
     structure like crt-vm does -- `dexter-audio-server.py` and
     `dexter-whisper-server.py` are deployed the same flat way) -- keep
     that copy in sync by hand when this script changes in the repo, `scp`
     doesn't work against dexter's OpenSSH (see HANDOFF.md), redeploy via
     base64-over-ssh instead.
2. **NAT port forward on dexter** (VirtualBox), `scanner,tcp,,8993,,8993`
   -- added live via `VBoxManage controlvm crt-vm natpf1
   "scanner,tcp,,8993,,8993"` 2026-07-21, confirmed present in
   `showvminfo crt-vm --machinereadable`. This does NOT survive across
   `VBoxManage modifyvm` calls that reset NAT config, but does survive
   normal VM power cycles (it's stored in the VM's own settings, same as
   the `ssh` forward). If it ever goes missing, re-add with that same
   command from dexter.
3. **`bin/crt-scanner-feed.py`** (runs on crt-vm, plain stdlib
   `http.server`, no new dependency). Listens on `0.0.0.0:8993`, `POST
   /scan {"text": "..."}`. Logs every scan unfiltered to
   `~/.crt/scanner.log` (mirrors `~/.crt/stt.log`'s "log first, judge
   later" pattern), then delivers into the tmux pane via `tmux send-keys`
   prefixed `[scan] ` so it reads distinctly from spoken/typed text.
   - **Confirmed working live 2026-07-21**, both via synthetic POST
     end-to-end and a real scan through `dexter-scanner-forward.ps1`.
   - Installed as a persistent `systemd` service on crt-vm:
     `systemctl enable --now crt-scanner-feed.service`, confirmed
     `enabled`/`active`. Survives reboot.
   - **Port-conflict gotcha hit and fixed during install**: an earlier ad
     hoc `nohup python3 bin/crt-scanner-feed.py &` (from initial testing)
     was still holding port 8993 when the systemd unit was enabled, so the
     systemd-managed process crash-looped on `OSError: [Errno 98] Address
     already in use` while `systemctl status` still showed "active
     (auto-restart)" -- looked superficially fine at a glance. Always
     check `ss -ltnp | grep 8993` (which PID actually holds the port)
     when standing up the persistent service after any ad hoc test run,
     not just `systemctl is-active`.

## Open items / next steps
- No de-dup/rate-limit on repeated scans of the same barcode yet (e.g. a
  scan left in the beam re-triggering) -- add if that turns out to be a
  real nuisance in practice, not preemptively.
- If the scanner is ever swapped for different hardware, re-check its
  VID/PID with `Get-PnpDevice -PresentOnly | Where Class -eq HIDClass` on
  dexter and update `-DeviceMatch` (default baked into
  `dexter-scanner-forward.ps1` and the Scheduled Task).
