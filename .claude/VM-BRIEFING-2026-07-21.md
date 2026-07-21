# Briefing from the mandark session, 2026-07-21 ~03:05

You're the crt-vm-resident Claude (separate account from the mandark dev
session). Zach asked mandark to "wire up STT durability in tandem with
you" — here's what already landed so you don't redo it, and what's left
for you specifically because you have real hardware/local access mandark
doesn't.

## Just installed on this VM (verify, don't redo)
- `bin/crt-vm-watchdog.sh` + `systemd/crt-vm-watchdog.{service,timer}` —
  checks every 5 min that windows `stt`/`mono`/`bridge` in this tmux
  session have their expected process alive (crt-stt-solo.py /
  crt-monologue.py / crt-claude-bridge.py); respawns just that window if
  dead, recreates it if the window itself vanished. Deliberately does NOT
  touch window 0 (this Claude Code pane) — only logs if it's gone, so a
  crash stays visibly a crash on-screen rather than getting silently
  papered over. Log: `~/.crt/watchdog.log` (only writes on a heal, empty
  = healthy). `systemctl status crt-vm-watchdog.timer` to check it's
  running. Please spot-check it's actually ticking (has run at least once
  more since install) and that `~/.crt/watchdog.log` still doesn't exist
  or is empty (meaning nothing's broken) — if it DOES have entries,
  something's crash-looping, worth digging into before anything else.
- Confirmed already durable and NOT touched: tty1 autologin
  (`/etc/systemd/system/getty@tty1.service.d/autologin.conf`) →
  `~/.bash_profile` → `bin/crt-console.sh`. This is the existing
  reboot-survival path; the new watchdog only covers the gap where the
  tmux session survives but a window's process silently died without a
  reboot.

## What you can do that mandark can't (you have the real mic/tmux/audio)
Please work through as much of this as you can, in order, and update
`HANDOFF.md`'s "What's actually running right now" + `.claude/
SESSION-STATE.md` as you go (both already exist, read them for full
context/history before starting — they're kept honest, not aspirational):

1. Confirm the watchdog is actually healthy per above.
2. `HANDOFF.md`'s priority #2: "get a human to actually listen to the TTS
   and calibrate it by ear" — you can't literally listen, but you CAN run
   `bin/crt-tts-calibrate.py` and check it exits clean / produces
   plausible output, then flag it as ready-for-a-human-ear rather than
   leaving it in limbo.
3. `HANDOFF.md`'s "not yet built" item: a visual signal of the USER's own
   speech (not just claude's replies) in the `mono` window — right now
   window 1 only shows your dialogue side. Real UX gap, real code, you
   have the display to check it against.
4. Anything else in `FOCUS.md` / `PARKING-LOT.md` marked blocked-on-VM
   that's now actually unblocked since you're live.

## What you can NOT do — leave these for mandark/dexter, don't attempt
- Anything on `dexter` itself (the Windows host) — you have no path
  there beyond the whisper-server HTTP endpoint you already call.
  Specifically: `dexter-whisper-server.py` auto-start durability
  (currently manual `Start-Process`, no service wrapper) is dexter-side
  Windows work, mandark is handling it directly over SSH right now in
  parallel with you.
- `AUDIO-ROUTING.md`'s TV audio bridge (priority #1 in HANDOFF.md) needs
  either a native-dexter listener or a Windows COM/nircmd approach —
  flagged there as needing Zach's OK to fetch a third-party binary, not
  something to just do.
- MIDI passthrough — needs a VBoxSVC restart mandark can't do remotely
  either; stays parked.

Work at your own pace, this isn't urgent-urgent, just "don't sit idle
when there's real backlog only you can touch." If anything's ambiguous,
leave a note in SESSION-STATE.md rather than guessing big — you're
talking to Zach live over voice too, feel free to just ask him.
