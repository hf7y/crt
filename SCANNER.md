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
   keyboard wherever focus happens to be, which is useless/unsafe to rely
   on. Instead this script uses the Win32 RawInput API
   (`RegisterRawInputDevices` + `RIDEV_INPUTSINK`) to read raw keyboard
   input system-wide and filters by device handle to just this VID/PID, so
   a human typing at dexter's real keyboard is never captured. Assembles
   characters into a line, and on Enter (end of barcode) POSTs
   `{"text": "..."}` to crt-vm.
   - **STATUS: written but NOT yet load-tested against a real scan** --
     RawInput device filtering is the standard technique but hasn't been
     exercised on this exact PowerShell/Windows combo. Run with
     `-DebugAll` first to confirm raw input reaches the window at all
     before suspecting the VID/PID filter if scans don't arrive.
   - Not yet wired to autostart (no Task Scheduler entry) -- run manually
     for now: `powershell -ExecutionPolicy Bypass -File
     dexter-scanner-forward.ps1`.
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
   - **Confirmed working live 2026-07-21**: started via
     `nohup python3 bin/crt-scanner-feed.py &` on crt-vm, `/health`
     returns `{"ok":true}`, a synthetic POST from dexter through the NAT
     forward landed in `~/.crt/scanner.log` end to end.
   - Started ad hoc for that test, not yet installed as a persistent
     service -- `systemd/crt-scanner-feed.service` is written and ready
     (same manual-install pattern as `crt-vm-watchdog.service`) but not
     yet `systemctl enable`'d, so it will NOT survive the next VM reboot
     until that's done.

## Open items / next steps
- Load-test `dexter-scanner-forward.ps1` against a real scan (only a
  synthetic curl-equivalent POST has been verified so far, exercising the
  guest-side listener but not the actual RawInput capture path on dexter).
- Install `systemd/crt-scanner-feed.service` on crt-vm so the listener
  survives reboots.
- Set up Task Scheduler ("At log on") for `dexter-scanner-forward.ps1` on
  dexter so it doesn't need a manual foreground launch each session.
- No de-dup/rate-limit on repeated scans of the same barcode yet (e.g. a
  scan left in the beam re-triggering) -- add if that turns out to be a
  real nuisance in practice, not preemptively.
