# USB 1D barcode scanner

Retired 2026-07-21, the same day it was built: originally a USB 1D barcode
scanner plugged into `dexter` forwarded scans to `crt-vm` over the network
(Pieces #1-3 below), arriving in the tmux Claude Code pane the same way STT
transcriptions do. Live path now: the scanner types like a real keyboard
directly into whatever tmux window has focus on the single machine that
hosts the console (`potato` today) -- `bin/crt-book-console.py` reads it
off its own stdin (see "2026-07-21, later still" below). `crt-vm`, named
throughout the history below, no longer exists (`hf7y/crt#162`).

## History

The dexter->crt-vm bridge (a PowerShell Win32-RawInput forwarder on
dexter, a VirtualBox NAT port-forward, a systemd HTTP listener on the
guest) was built 2026-07-21, hit a real dead end the same day -- across
three different launch mechanisms the dexter-side capture never once saw
a live scan, while the raw keystrokes reliably reached the guest's
focused tmux window regardless -- and was retired in favor of that direct
path. Full investigation and the intermediate "nice to have, not
load-bearing" step: `git log -p -- SCANNER.md`.

`bin/dexter-scanner-forward.ps1` is removed from the repo (still in git
history, `git log -- bin/dexter-scanner-forward.ps1`, if a
different-machine scanner is ever a live target again). `crt-scanner-
feed.py`'s HTTP listener stays in the tree for that same case but isn't
part of the current install path -- nothing in `install.sh` starts it;
`crt-book-console.py`'s stdin path writes `scanner.log` directly now
(`format_scan_log_line()`, `tests/test_book_console.py`).

**Not yet cleaned up (2026-07-24 finding, still true):** the deployed
`dexter-scanner-forward.ps1`, `dexter-scanner-debug-wrapper.ps1`, and
`update_task.ps1` are still sitting in `C:\Users\Zach\` on dexter, and
its Windows Scheduled Task firing them was found still enabled 3+ days
after retirement (deleted then; re-check if dexter is ever touched for
this again).

## Open items / next steps
- No de-dup/rate-limit on repeated scans of the same barcode yet -- add if
  that turns out to be a real nuisance in practice, not preemptively.
- If the scanner is ever swapped for different hardware, re-check its
  VID/PID (`Get-PnpDevice -PresentOnly | Where Class -eq HIDClass` on
  whichever machine it's plugged into).
