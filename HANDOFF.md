# crt — current state & handoff

Voice-driven secretary console: a landline handset + CRT TV as the human
interface, backed by a Debian VM (`crt-vm`) on a Windows mini-PC (`dexter`),
with the CPU-heavy transcription now offloaded to `dexter` itself. This doc
is the pick-up-where-we-left-off summary — read this first, then follow the
pointers below for depth on any one piece.

**Read next, depending on what you're doing:**
- `README.md` — the how-and-why of each original piece, incl. detailed audio
  troubleshooting.
- `.claude/FOCUS.md` — current backlog/status, kept up to date per session.
- `SECRETARY.md` — the actual product vision (phone secretary, not a raw STT
  terminal) and what's built vs. still design-only.
- `AUDIO-DEBUG.md` — mic capture staleness debugging (5 parallel approaches).
- `AUDIO-ROUTING.md` — TV vs. phone-earpiece audio output separation (still
  unsolved — this is the active priority, see below).
- `PARKING-LOT.md` — the deep end-state vision (RF power-on, hidden
  transcription, predictive-text feel, morning-reports + media-playback as
  the two core jobs). Not built, captured so it isn't lost.

## Where it runs

- **`dexter`** — Windows 11 Pro mini-PC (Minisforum/Ryzen). Host, and now also
  runs the transcription service natively (see below).
  - SSH: `ssh dexter.local` (key auth; drops into PowerShell).
  - **If SSH pubkey auth ever silently breaks** (host reachable, key
    unchanged, clean handshake then rejected): check
    `C:\ProgramData\ssh\administrators_authorized_keys` — Windows OpenSSH
    ignores the per-user `authorized_keys` for admin accounts and only reads
    this file. Hit this exact issue 2026-07-19; fixed by writing the key
    there directly (paste corruption is a real risk over a remote shell —
    split long tokens into short chunks and concatenate in PowerShell rather
    than pasting one long line).
  - `scp`/`sftp` do **not** work against this Windows OpenSSH setup (fails
    with "dest open ... Failure"). For binary transfers, base64-encode and
    pipe through `ssh '...' | python decode.py'` instead.
  - VirtualBox 7.2.12 + Extension Pack installed. `VBoxManage` at
    `C:\Program Files\Oracle\VirtualBox\VBoxManage.exe` (call via `& "..."`).
  - Has a Surfshark VPN active — this specifically resets connections to
    `huggingface.co` (other HTTPS is fine) — watch for this if anything ever
    needs to download from the HF Hub directly on dexter again.
- **`crt-vm`** — Debian 13 guest on dexter. The console itself (mic capture,
  VAD, tmux/CRT display).
  - SSH: `ssh -p 2222 zach@dexter.local` (NAT port-forward 2222→22, key auth).
  - Password `kw0kWXESrKQpNvuKXiU8`; passwordless sudo enabled.
  - To see its screen: at dexter's KVM, open **VirtualBox Manager** and
    double-click `crt-vm` (GUI mode). Do NOT use "Show" on a headless VM
    (hangs), and do NOT `startvm --type gui` over SSH (no window appears
    unless someone is already logged into dexter's local interactive
    session).
- **`mandark`** — this Linux laptop. Dev box; the repo's origin of truth,
  pushed to a local bare remote (`~/git-remotes/crt.git`) that the VM does
  *not* pull from directly (no git link VM→mandark — files are copied over
  SSH by hand/script when deploying).

## What's actually running right now (2026-07-20 night, current)

On `crt-vm`, tmux session `claude`, launched by `bin/crt-console.sh` on
tty1 autologin (**never** `tmux kill-session` this casually — it's safe
(autologin respawns everything correctly), but it's a real interruption;
prefer `tmux respawn-pane`/`respawn-window` for a targeted fix):
- **window 0** (`claude`) — full-screen Claude Code pane. Voice is typed
  straight into this window's input by window "stt" below.
- **window 1** (`mono`, visible, prefix+1) — `bin/crt-monologue.py`:
  claude's own DIALOGUE replies (not its thinking), pretty-printed,
  ephemeral (fades/drops old lines). Fed by window "bridge" below, not by
  window "mono" itself.
- **window "bridge"** (background) — `bin/crt-claude-bridge.py`: tails
  claude's own JSONL session transcript, extracts assistant text replies,
  appends them to `~/.crt/thoughts.log`, which window "mono" renders.
- **window "stt"** (background) — `bin/crt-stt-solo.py`
  (`CRT_STT_SINK=claude`): the SOLE mic reader (metering + VAD + whisper +
  typing into window 0), replacing the older `stt-feed.sh` +
  `crt-levels.sh` dsnoop-meter pair (see AUDIO-DEBUG.md Approach B for
  why single-reader avoids that pair's staleness bugs). Its own meter/HUD
  writes to this window's own pane, not visible unless you switch to it.

**Incident, for the record** (2026-07-20): this exact layout was first
hand-assembled in extra tmux windows during a 2026-07-19 live session and
ran well for a full evening — but was never wired into `crt-console.sh`
itself. A routine VM reboot the next night respawned autologin ->
`crt-console.sh` -> the OLD default (`stt-feed.sh` + a separate meter
split), and the better setup was gone with no record beyond
`ps aux` archaeology. It's now wired directly into `crt-console.sh`'s
code (see that file's own comments) rather than only described here,
specifically so a future respawn can't silently regress it again — a doc
is easy to skip, code that runs on every boot isn't.

**Also found and fixed the same night**: `stt-feed.sh` (still used for
`CRT_SECRETARY`/stdout debug modes, just no longer the default boot path)
had a real bug where `set -o pipefail` + `arecord`'s expected SIGPIPE
(when `sox` closes the pipe at a VAD cutoff) made the whole
`arecord | sox` pipeline register as "failed" on literally every
utterance, even though `sox` itself always succeeded — silently
discarding every utterance before whisper ever ran, no error output
anywhere. Fixed by checking `sox`'s own exit status via `PIPESTATUS`
instead of the pipeline's combined status.

**Not yet built** (so it doesn't get assumed-done next time): a visual
signal of the USER's own speech in the "mono" window — right now it only
shows claude's side of the conversation, not the raw/interim STT text or
a level indicator.

On `dexter` (native Windows, not the VM): `dexter-whisper-server.py`
(faster-whisper, int8, full Ryzen cores) listening on `0.0.0.0:8991`
(`/health`, `/transcribe`). `crt-stt-solo.py` on the VM calls it via
`CRT_WHISPER_SERVER=http://192.168.0.22:8991/transcribe` instead of local
whisper.cpp. **Not auto-starting** — currently launched manually via
`Start-Process`; needs a Scheduled Task or service wrapper to survive a
dexter reboot.

## Core pieces (bin/), what each does

- `crt-stt-solo.py` — the sole mic reader (single-consumer by design, see
  AUDIO-DEBUG.md Approach B). VAD, denoise, whisper (local or network),
  live-tunable via a control file (`~/.crt/ctl`, byte-offset tailed), on-screen
  HUD flash, and now: **ring/pickup detection** (`bin/crt-ring.sh <n>` rings a
  warble tone, listens for voice only in the silent gaps so the tone can't
  self-trigger, stops on pickup, prints a timeout message if unanswered — no
  physical hookswitch exists yet, so "pickup" is inferred from voice alone).
- `crt-tts.py` + `crt-tts-calibrate.py` — espeak-ng/piper TTS, calibrated
  profile in `~/.crt/tts.conf`. Deployed + smoke-tested (exit 0) on crt-vm;
  **not yet confirmed audible/good by a human ear**.
- `crt-announce.sh` — rate-limited (1/15min) TV-facing TTS for Chris. Code
  done; the actual bridge to reach the TV's audio device from inside the VM
  does not exist yet (VirtualBox maps only one host audio device per VM) —
  **this is the current top priority**, see AUDIO-ROUTING.md.
- `crt-pager.py` — slow auto-scroll pager for long text on the CRT
  (control-file driven, same channel as the knob HUD). Not wired to anything
  real yet.
- `crt-think.sh` / `crt-monologue.sh` — the append-only thought log + its
  on-screen narration. **Ongoing practice: narrate real work into this log
  in-character as it happens**, not just after the fact.
- `dexter-whisper-server.py` — see above.
- `crt-midi-knobs.py` — MIDI CC/notes → the control file. Blocked, see MIDI
  status below.
- `cad/wall_hook.scad` — simple hang-up hook with a reserved hole for a later
  hanging switch (distinct from `cradle.scad`/`hook_lever.scad`, the fuller
  see-saw switch assembly).

## Current priorities (in order)

1. **TV audio bridge** (promoted 2026-07-19 evening; MIDI explicitly parked
   in favor of this). VirtualBox only maps one host audio device per VM —
   getting `crt-announce.sh` to actually reach the TV (not just whatever
   device the VM happens to be mapped to) needs either a small always-on
   listener on dexter that the guest posts to, or moving TTS-for-Chris
   entirely to a native-dexter process. See AUDIO-ROUTING.md for the
   options and the dead-end already tried (raw COM PolicyConfig from
   PowerShell reproducibly fails QueryInterface; `nircmd.exe` would work but
   needs the user's OK to fetch a third-party binary).
2. Get a human to actually listen to the TTS and calibrate it by ear
   (`crt-tts-calibrate.py`) — nothing audio-output has been human-verified
   yet, only exit-code-verified.
3. Build the real secretary wrapper (SECRETARY.md steps 1-4) instead of raw
   STT→Claude keystrokes — decide printer vs. CRT vs. TTS per response,
   structured requests instead of typing everything verbatim.
4. **MIDI passthrough — parked.** Root cause found (Windows had the
   MiniLab's interface Device-Manager-disabled; fixed via `Enable-PnpDevice`)
   but `VBoxManage usbattach` still errors "busy with a previous request"
   even after that + a full VM power-cycle. Needs a VBoxSVC/VirtualBox host
   service restart (a process-kill action the harness blocks without the
   user doing it directly). Pick back up once the TV bridge is done.
5. Compute stick — blocked on a DAC arriving (no analog audio in on the
   stick); also physically can't be advanced remotely regardless.

## Autonomous overnight batch (scheduler)

Registered in `~/Documents/Project Archive/scheduler/schedule/crt.conf`.
REPO_URL points at the local bare remote. **Tier 2 batch enable is staged but
not applied** — the harness classifier blocks writing the
`BATCH_JOB_NAME`+`claude -p` prompt that stands up recurring autonomous
execution. Ready-to-paste block: `scratchpad/crt.conf.batch-block` (from a
prior session — verify it still exists/is current before using). Batch scope
is CODE-shaped work only; it can't reach the VM or dexter's Windows side.
