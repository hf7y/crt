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

## 2026-07-21 late session: the dexter-side capture path is a dead end

Everything above in "Pieces" #1 describes the *intent* of
`dexter-scanner-forward.ps1`; several of the "confirmed working" claims
turned out to be false positives from earlier in the day (the process
looked alive and error-free but was actually hung on an `Add-Type`
compile error -- `Environment.TickCount64` doesn't exist in this
dexter's Windows PowerShell 5.1 Add-Type target -- filling a
`Start-Process`-redirected pipe nobody was draining; fixed by switching
to `Environment.TickCount`, see that commit). After fixing the actual
bug and testing again with real scans, live end to end, multiple times:

- **The raw scanner keystrokes reliably reach crt-vm's currently-focused
  tmux window every time** (confirmed repeatedly -- ISBNs landing as
  literal typed text in the live `claude` pane, once even triggering a
  real web-search tool call on the ISBN, burning an API turn on garbage).
  This part of the architecture works, just not through the intended path.
- **The dexter-side capture/suppression NEVER once saw a real scan**,
  across several different launch mechanisms tried:
  - `Start-Process` over an interactive SSH command -- processes
    launched this way get killed when the SSH session/job closes, even
    detached-looking ones (Windows job-object containment tied to the
    console session). Looked "running" in `Get-CimInstance` checks made
    *within* the same SSH invocation, but were gone by the next
    independent check.
  - Windows Task Scheduler (`LogonType: Interactive`, the account
    logged in) -- process persisted correctly this time, but a live
    `-DebugAll` scan test still logged **zero** raw-input events, not
    even from real keyboard activity, suggesting it may not actually be
    attached to the interactive window station (`WinSta0\Default`) the
    physical scanner's HID events arrive on -- unconfirmed, investigation
    stopped here.
  - Also tried disabling VirtualBox's own keyboard auto-capture
    (`VBoxManage setextradata crt-vm GUI/AutoCaptureKeyboard false`,
    still set) on the theory that VBox grabs input at a level below
    normal Windows RawInput/hooks when its guest window has focus. Did
    not fix it either (or didn't apply without an already-open capture
    being released -- not isolated which).
  - **Declared a dead end 2026-07-21** rather than continue burning time
    on Windows session/window-station internals neither of us can fully
    see into from here.

### The actual plan going forward (not yet implemented)

Stop trying to intercept/suppress on the Windows side. The keystrokes
**reliably** reach the guest's focused tmux window regardless -- use
that instead of fighting it:

1. Change `bin/crt-book-console.py` to read scan input **directly off
   its own stdin** (it's the foreground program in the `book` tmux
   window, so raw typed/scanned lines land there directly, no
   dexter-side forwarder or HTTP hop needed at all) -- detect an
   ISBN-shaped line the same way `parse_scanner_log_line()` already does
   for `scanner.log`, and feed it through the same `handle_scan()` path.
   Keep the `scanner.log`-tailing behavior too (harmless, and still
   useful if the dexter forwarder ever does get fixed later) -- add
   stdin as a second input source, not a replacement.
2. Make the `book` window crt-console.sh's **default selected window**
   on boot (instead of window 0/`claude`) -- since a physical scan's
   keystrokes go wherever tmux's active window is, and this appliance's
   more common physical interaction is probably "pick up scanner, scan
   book" rather than "type at claude directly" (voice/STT already covers
   the claude-facing interaction; the keyboard-wedge scanner was never
   going to reach claude usefully anyway, only ever as page-of-numbers
   garbage). `claude` stays one `prefix+0` away.
3. This drops `bin/dexter-scanner-forward.ps1`, the NAT port-forward,
   and `bin/crt-scanner-feed.py`'s systemd service down to "nice to have,
   not load-bearing" -- leave them in place (harmless, and the
   TickCount64 fix + suppression logic may be worth revisiting once
   there's time to actually attach a debugger/interactive session to
   dexter directly, rather than fighting it blind over SSH), but the
   book-scanning feature's correctness should not depend on them working.
4. **Not yet implemented** -- decided and written up 2026-07-21 to leave
   a clean handoff, but out of time this session. Next session: implement
   `crt-book-console.py`'s stdin-reading, flip the default window, test
   with a real scan, update this doc's status once actually verified
   (not just "should work" -- this doc has already been burned once today
   by an unverified "confirmed working" claim, see above).

## 2026-07-21, later: dead `deliver()` removed (input-routing cleanup)

Point 3 above called the `tmux send-keys` delivery in `bin/crt-scanner-
feed.py` "nice to have, not load-bearing" and left it in place. Revisited
as part of a broader pass on how STT/scanner streams get routed: that
send-keys call was a second, uncontrolled path for a scan to land as
literal keystrokes in whatever window had focus -- including window 0's
live Claude pane, exactly the kind of unrouted escalation the STT side
already has a wake-word gate (`STT-GATE.md`) to prevent. Since nothing
still depends on it (`crt-book-console.py` tails `scanner.log` directly,
per the pivot above), removed outright rather than left dormant --
`crt-scanner-feed.py` is now log-only. See `tests/test_scanner_feed.py`.

## 2026-07-21, later still: `bin/dexter-scanner-forward.ps1` retired (compute-stick prep)

The whole dexter->crt-vm scanner bridge described in "Pieces" #1/#2 above
(`dexter-scanner-forward.ps1`, its Windows Task Scheduler entry, the
`crt-vm` NAT port-forward) exists for exactly one reason: the scanner is
physically plugged into `dexter` (Windows), a DIFFERENT machine than the
console (`crt-vm`, a guest on that same host). On the Intel Compute
Stick target (README's "Bare-metal deployment" section, Debian 13.6
amd64), there is only ONE machine -- the scanner plugs directly into the
stick's own USB port, and (per this doc's own "2026-07-21 late session"
finding, already proven live) types like a real keyboard into whatever
tmux window has focus. `bin/crt-book-console.py`'s stdin-reading path
(the primary scan path already, see that file's header) picks it up with
zero forwarding, zero network hop, zero second machine involved.

`bin/dexter-scanner-forward.ps1` is removed from the repo (still in git
history, `git log -- bin/dexter-scanner-forward.ps1`, if `crt-vm`-behind-
dexter is ever a live target again). `crt-scanner-feed.py`'s HTTP
listener is left in place (still useful if a scanner is ever on a
different machine than the console again) but is NOT part of the
compute-stick install path -- nothing in `install.sh` starts it. The
`scanner.log` audit trail that listener used to be the only writer of is
now also written directly by `crt-book-console.py`'s stdin path itself
(`format_scan_log_line()`), so the log stays complete with or without
that listener running -- see `tests/test_book_console.py`'s
`TestFormatScanLogLine`.
