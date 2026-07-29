**Unrelated side task in progress, not STT work**: an Intel Compute Stick
(STK1AW32SC) migration — flashing/preseeding a USB installer for Debian.
Full details, current status, and next steps in
`COMPUTE-STICK-MIGRATION.md` (project root). If a diagnostic/install boot
was mid-flight when this session ended, that doc says exactly where to
pick up.

# Session state (read this first, before STT-MECHANISM.md)

## LATEST (2026-07-29, early hours) — the console's config had three
## silent holes; all found by restarting capture by hand

Zach: "potato can't reach its brain." It could. What follows is three
separate silent-wrong-default bugs stacked on each other, none of which
produced an error anywhere.

1. **Stale process, not a broken path.** potato's `~/.crt/brain.conf`
   correctly said `CRT_CLAUDE_SSH_HOST=dexter`, but the running
   `crt-stt-supervisor.sh` had been up ~22h — since before that file was
   written — still carrying `CRT_CLAUDE_REMOTE_PORT=8993`, the retired
   mandark tunnel. Every utterance since logged `NOT DELIVERED [no
   response from the bridge on port 8993]` to
   `~/.crt/brain-unreachable.log`. Verified the real path works first:
   `ssh potato 'echo CAPTURE | ssh dexter'` returns dexter's live pane.
   **Lesson: nothing asserts the running console matches its conf files.
   A config edit is inert until someone restarts, with no drift signal.**

2. **My own restart made it worse, which is how the real bug surfaced.**
   `ssh potato tmux new-window ...` is a NON-LOGIN shell. potato's
   console identity lived only in `~/.bash_profile`, so capture came back
   with `CRT_EARCON_DEVICE` unset (code default `handset` —
   `crt-stt-solo.py:279`) and `CRT_WAKE_WORD` unset (default `claude` —
   `:737`). Mic live, meter moving, `gate.log` filling. Beeping into an
   earpiece nobody held, listening for a name nobody says.

3. **Worse and older: the tty1 boot path never had them either.** On
   potato, `CRT_CLAUDE_ARGS`, `CRT_WAKE_WORD` and `CRT_EARCON_DEVICE`
   sat BELOW the `exec crt-console.sh` line in `~/.bash_profile`. A cold
   autologin boot never reached them. The documented `potato` wake word
   had therefore never actually been in force on a real boot since it was
   set on 2026-07-28 — it only worked when a human started the console by
   hand from an ssh login shell.

**Fix shipped**: `bin/crt-conf.sh` (new, sourced-not-executed loader) reads
`~/.crt/console.conf` then `~/.crt/brain.conf` (last, so runtime brain
routing still wins), legacy `mandark.conf` fallback unchanged.
`crt-console.sh` and `crt-stt-supervisor.sh` both source it; the supervisor
in particular, because it is the restart point for capture and gets rerun
by hand. `crt-console.sh` no longer retypes console-wide env into the stt
window command. Template: `console.conf.example`. Test:
`tests/test_console_conf.sh` (7 assertions, in `run_tests.sh`) — the
load-bearing one runs the supervisor under `env -i` and asserts the child
still comes up configured.

**Still true, NOT fixed**: `CRT_WHISPER_SERVER=http://192.168.0.27:8991`
— that IP is **mandark**, the intermittent laptop the dexter move exists
to escape. dexter is `192.168.0.22` and has **no whisper install at all**
(no `~/whisper.cpp`, nothing listening on 8991). realisateur flagged this
from mandark and was right about the gap, but wrong on one detail:
`bin/dexter-whisper-server.py` does **not** exist — deleted in `3dee2d5`,
surviving only as a stale comment in `mandark-whisper-server.py:5`. The
good news: `mandark-whisper-server.py` is already host-agnostic (all
`CRT_WHISPER_*` env, binds `0.0.0.0`), so it is a copy + venv + repoint,
and the repoint is now one line in `~/.crt/console.conf`.

**Room/audio facts confirmed live**: potato's ALSA — card 0 `bcm2835
Headphones` (playback only), card 1 `KT USB Audio` (the mic, capture),
card 2 `vc4hdmi`. Earcons sound on all three; `tv` = `plughw:2,0` (HDMI).

## LATEST-2 (2026-07-28) — potato's brain wired, then handed to gardien

**Potato's nightly self-repair is LIVE.** `/etc/systemd/system/crt-self-repair.{service,timer}`
installed and `enabled --now` on potato (Zach ran the sudo half; the
permission classifier blocks remote sudo from this session — hand the
command over, don't retry it). First fire 04:15 local, randomized +10min.
Filed with senechal.

**Potato's repo was never a real clone.** `origin` is
`/home/zach/git-remotes/crt.git` — a path that exists only on mandark, so
potato could never fetch, ever. Its 10 modified + 7 untracked files turned
out byte-identical to origin/main (a file-level copy on a stale HEAD, not
local work). Synced via `git bundle` + scp + `git stash push -u` +
`merge --ff-only`; potato is clean on the current HEAD. `stash@{0}` and
`/tmp/crt-pretree-backup.tgz` remain on potato as redundant safety nets.
Direction that DOES work: this checkout has a `potato` remote
(`ssh://potato/home/vkv/crt`) and `git fetch potato` succeeds — that is how
the nightly pass's commits come back until the move lands.

**Two enforcers were contradicting each other.** `test_crt_safe_colors.sh`
flagged `test_screensaver.py` — its documented "nothing here uses
256-color" over-match died when the screensaver adopted `\x1b[38;5;94m`.
Fixed with a `;5;` lookbehind + probes both directions + a per-line
`crt-safe-colors: verbatim` opt-out. Suite green otherwise. **Known flake,
not fixed:** `test_hookswitch_debounce.sh`'s separated-transitions case has
a fixed 0.35s wall-clock budget — passes standalone, fails under full-suite
load.

**New mechanism: `bin/crt-senechal-guard.sh`** — PostToolUse(Bash) hook
(project `.claude/settings.json`) that reminds when a command touches
machine-scoped config. It reminds rather than auto-filing on purpose; the
reasoning is in the script header, don't "improve" it into an auto-filer.
Also asked senechal to SWEEP for unregistered config rather than only
receiving pushes.

**Handed off:** Zach is moving crt off mandark onto always-on dexter with
gardien. `DEXTER-MOVE.md` (new, project root) has the probed inventory and
the plan — read it before touching hosts. Headline finding:
`crt-whisper-server.service` is ACTIVE on mandark on `0.0.0.0:8991`, i.e.
live STT depends on a laptop staying awake. `crt-vm_claude_creds.json`
deleted (Zach's call), not migrated.

## LATEST-3 (2026-07-27) — ecosystem reconciliation: potato/dexter, both fine

Zach asked to survey the crt ecosystem for drift after a router change.
Findings, in case anything here gets re-assumed wrong later:

- **potato is still 192.168.0.45** (not .43 — that's an unrelated
  Octoprint box, confirmed by Zach mid-session; don't chase that IP
  again). `vkv_deploy_key` access works fine.
- **dexter is still 192.168.0.22 / dexter.local**, host key unchanged —
  an earlier "host key verification failed" was a transient mDNS/DNS
  blip from the router swap, not an actual key change. No ssh auth
  configured for `zach@dexter` from this box (pubkey rejected) — separate,
  pre-existing gap, not investigated further this session.
- **Fixed for real: potato's `~/crt` had no relationship to `origin`.**
  It was a standalone repo from the original tar-over-ssh deploy
  (2026-07-22), never `git clone`d from anywhere, with a completely
  disjoint commit history (4 local-only commits, no common ancestor with
  `origin/main`) and ~140 files sitting on disk untracked. Diffed
  potato's tracked tree against this dev checkout byte-for-byte first —
  confirmed potato had nothing unique (its 4 orphan commits were an
  earlier, less-complete version of the same window-1-marker/staleness
  work already in `origin/main`'s history under different hashes; its
  uncommitted `stt-fixups.json` edits were already fully present here
  too). With Zach's go-ahead: backed up potato's old repo to
  `~/crt.bak-2026-07-28` (still there, untouched), then replaced
  `~/crt` with a clean `git clone` built from a bundle of this repo's
  `main`, `origin` remote pointed at `/home/zach/git-remotes/crt.git`.
  Potato's HEAD now matches this repo's exactly (`21fe8ef` at the time).
  **Caveat:** that `origin` path is local to this dev workstation, not
  network-reachable from potato — potato still can't `git pull` live;
  future deploys need the same bundle/tar/scp approach used this
  session, not a bare `git pull origin main` on potato itself. Filed via
  `notify-senechal` (repo/remote config change on potato).
- Everything else in LATEST-2 below (mandark brain-routing, screensaver,
  wake-arm) wasn't touched or re-verified this session — still whatever
  state LATEST-2 says, not re-confirmed live.

## LATEST-2 (2026-07-23, evening) — idle-lean brain placement + potato screensaver

Built + deployed live to potato this session (see POTATO.md):
- **Screensaver is LIVE** on potato — `bin/crt-screensaver.py` renders
  `potato-small.txt` (braille potato) in a tmux window named `saver`,
  currently selected on the CRT. NOTE: `saver` is a hand-created window,
  NOT durable — a reboot loses it. To make it the boot idle-face, set
  `CRT_NO_IDLE_CLAUDE=1` (crt-console.sh now supports that layout: window
  0 becomes the screensaver instead of a resident Claude). NOT yet
  persisted in potato's `~/.bash_profile` — do that to survive reboot.
- **`bin/crt-mandark.sh on|off|status`** — the toggle for routing the
  brain to mandark. Ran `on` live; wrote potato's `~/.crt/mandark.conf`
  (CRT_CLAUDE_REMOTE_PORT=8993); bridge probe = reachable.
- **`bin/crt-wake-router.py`** — pure remote/local/none decision brain
  (offline-tested). The live wake SUPERVISOR that acts on it (on-demand
  local-brain spin-up + screensaver↔brain window swap) is NOT built —
  the one remaining [hw] piece (POTATO.md "remaining live wiring").
- **Scanner feed RETIRED** (commit de37a06): `bin/crt-scanner-feed.py` +
  its systemd unit + test removed — dexter-era HTTP receiver that bound
  0.0.0.0:8993, colliding with the Claude bridge tunnel. Was inactive on
  potato, no live impact. scanner.log now written by crt-book-console.py.
- Commits 806ba31 (brain-placement scaffolding + POTATO.md +
  REFACTOR-ASSESSMENT.md + FOCUS.md batch backlog) and de37a06 pushed.
- **`bin/crt-mandark-serve.sh {on|off|status}`** (MANDARK side) — toggles
  the whole remote path (whisper + bridge + reverse tunnel). Prefers
  systemd, falls back to ad-hoc. whisper on/off needs sudo. Committed
  dca5bb5.

**POST-REBOOT, VERIFIED LIVE 2026-07-23 evening:** potato was rebooted
into the idle-lean layout and it works end-to-end. Persisted in potato's
`~/.bash_profile` (before the tty1 `exec crt-console.sh`; original backed
up to `~/.bash_profile.bak-idlelean`): `CRT_NO_IDLE_CLAUDE=1` +
`CRT_WAKE_ARM_ENABLED=1`. Confirmed after reboot: window 0 = screensaver
(selected idle face), NO resident Claude, **560MB free (was 98MB)**, stt
window has CRT_CLAUDE_REMOTE_PORT=8993 + CRT_WAKE_ARM_ENABLED=1, bridge
reachable from potato, sshfs mount healthy.

**DURABILITY GAP (the one remaining):** mandark's bridge + reverse tunnel
are still ad-hoc `nohup`, NOT systemd — a mandark reboot OR a potato
reboot drops the tunnel and it does NOT auto-reconnect (must re-run
`crt-mandark-serve.sh on` on mandark). Fix: run
`bin/setup-mandark-remote-claude-persistence.sh` on mandark (needs sudo)
to install the systemd units. Until then, after any reboot, restore with
`crt-mandark-serve.sh on`.

STILL OPEN / next: (1) window 0 still holds a redundant live local Claude
eating RAM (98MB free) — kill it or restart into CRT_NO_IDLE_CLAUDE to
reclaim. (2) STICKY WAKE WINDOW: `crt-wake-arm.py` is built+wired+tested
but disabled (CRT_WAKE_ARM_ENABLED=0) — enabling it (restart stt window
with the env set) fixes the follow-up-gate-drop bug; needs live ARM_SECS
tuning. (3) A mid-session slip: mis-read window 0 as idle bash and
accidentally submitted a prompt into its live Claude; classifier blocked
the Escape cleanup. Don't send-keys into window 0.

INCIDENT NOTE for whoever's next: `tmux list-windows` showing "0: bash"
did NOT mean window 0 was an idle shell — a live Claude Code TUI was
running there. Capture-pane before assuming a window is safe to write to.

---

## LATEST (2026-07-23, afternoon/evening) — Claude Code itself now runs
## on mandark, not potato. This supersedes anything below that assumes
## Claude runs locally on potato's window 0.

**The single biggest architecture change of the whole day.** Following
the morning's `ARCHITECTURE-REVIEW-2026-07-23.md` finding (potato is a
1GB Pi 3B+, memory-constrained, Claude Code itself was 37% of its RAM),
Zach asked what moving Claude off potato would look like — this session
built and live-tested it, and it's **currently live**:

- **`bin/crt-remote-claude-bridge.py`** — a tiny server on mandark,
  binds `127.0.0.1:8993` ONLY (never LAN-reachable), speaks a 2-command
  protocol (`CAPTURE`, `SEND <text>`) against one named tmux session
  (`potato-claude`) — not a shell, not SSH, nothing else possible over
  this socket.
- **Reverse tunnel, mandark-initiated**: `ssh -N -R 8993:localhost:8993
  potato` — deliberately NOT the other direction. mandark has no SSH
  server at all (only ever the client); Zach flagged potato having any
  network path INTO mandark as a real vulnerability, so this was
  rejected in favor of mandark dialing OUT (the direction that already
  works/is trusted). Potato ends up talking to its own `localhost:8993`,
  never to mandark directly.
- **`crt-secretary.py`'s `capture_pane()`/`send_to_claude()`** swap to
  this bridge when `CRT_CLAUDE_REMOTE_PORT` is set (unset = old local
  behavior, byte-identical). **Currently set live** on potato's `stt`
  tmux window (`CRT_CLAUDE_REMOTE_PORT=8993`, wired into
  `crt-console.sh`'s launch line too, so it survives a full restart).
- **The actual Claude session** lives in a mandark-local tmux session
  named `potato-claude`, working directory `~/potato-crt` — an
  **sshfs mount of potato's real `~/crt`** (`sshfs potato:/home/vkv/crt
  ~/potato-crt`, NOT mandark's own git checkout at
  `~/Documents/Projects/crt` — these are two different directories on
  mandark, don't confuse them). This is how Claude-on-mandark reads/
  writes potato's real files (books.db, logs, stt-fixups.json) — tool
  calls operate on the mount, which is really potato's disk over SFTP.

**Live-tested this session, multiple real exchanges, all worked**:
wake-word trigger → secretary fallthrough → bridge → mandark's Claude →
reply with the `» ` marker convention → back to potato's window 1.
Confirmed Claude-on-mandark can actually run tool calls against the
sshfs-mounted files (asked to list top-level files, got the real
answer). No failures observed, but only tested for a few minutes, not a
full session's worth of tunnel-stability/idle-detection-over-network
questions — see the FOCUS.md cleanup-flags entry from this session.

**NOT yet durable**: the bridge server and tunnel are still the
original ad-hoc `nohup` background processes on mandark (PIDs will not
survive a mandark reboot/logout). `bin/setup-mandark-remote-claude-
persistence.sh` (systemd units for both, same password-needed-so-hand-
Zach-a-script pattern as `setup-mandark-whisper-persistence.sh`) is
written and committed but **has NOT been run yet** — check `systemctl
is-active crt-remote-claude-bridge.service crt-potato-tunnel.service` on
mandark; if both say "inactive" or "could not be found", the ad-hoc
processes are still what's actually running (check `ps aux | grep
crt-remote-claude-bridge` on mandark) — don't assume the systemd units
are live just because the setup script exists in the repo.

**To resume/verify this is still working**: on mandark, confirm the
bridge + tunnel are running (systemd or ad-hoc, per above); on potato,
confirm the `stt` tmux window has `CRT_CLAUDE_REMOTE_PORT=8993` in its
environment (`ps eww <pid>` on the `crt-stt-solo.py` process); the real
Claude session is `tmux capture-pane -t potato-claude` on mandark, not
anything on potato's own window 0 anymore (window 0 on potato is now a
SEPARATE, no-longer-primary Claude session — don't confuse the two if
debugging a reply that doesn't show up where expected).

**Reconciled same session**: potato's `bin/stt-fixups.json` had 4 new
STT-mishear entries (clod, wonder one, gal wah, cloud text) accumulated
live that hadn't been pulled into the main repo yet — done, pushed.
Potato's git tree otherwise unchanged since the morning's 4-commit
cherry-pick (no new potato-side commits to reconcile this time).

---

Last updated: 2026-07-23 (early morning BST) — a long live-tuning session
with Zach on the mic, direct interactive access to BOTH mandark (this
dev box) and potato (the real console hardware, a Raspberry Pi). This
supersedes everything below it (2026-07-20 and earlier) as the current
accurate picture -- read this section fully before touching STT/audio
code, then check `.claude/FOCUS.md`'s 2026-07-23-dated entries for full
detail/reasoning on any item below.

## Current real topology (2026-07-23) -- dexter/crt-vm is legacy

**potato is the actual console now.** A Raspberry Pi, `ssh potato` (key
auth, alias in mandark's `~/.ssh/config`), user `vkv`, real ALSA
hardware (not VirtualBox emulation). It runs a live tmux session named
`claude` with windows: 0=main Claude session, 1=mono (window-1 display),
2=bridge, 3=stt (the sole mic reader), 4=book, 5=bookidle, 6=bookanswer,
7=windowswitch, 8=stttrain, 9=game (new tonight, the calibration game).

**IMPORTANT: potato's `~/crt` is NOT a git clone of this repo.** It has
its OWN separate git history (no common ancestor -- confirmed via
`git fetch potato; git log potato/master`, "no common commits") and its
working tree has ~127 files that show as untracked relative to ITS OWN
git state, meaning it was seeded by copying files in, not a real clone.
Files move mandark<->potato by hand (`scp bin/whatever.py potato:~/crt/bin/`),
same posture HANDOFF.md already documented for mandark<->dexter<->crt-vm.
**Always diff after scp'ing to confirm it landed** (`diff <(cat) ~/crt/bin/X.py < X.py` over ssh),
and always `git status`/read `WAKE-TUNING-STATE.md`-style files on potato
BEFORE overwriting -- potato had real historical work (4 real commits,
cherry-picked into mandark's main earlier tonight, see git log
`38607bd`/`3a352b2`/`2eb253c`/`739172a`) that would have been lost if
overwritten carelessly.

**A live, human-operated Claude Code session runs in potato's window 0**
-- Zach talks to it directly via the physical handset/CRT, independent of
whatever this (mandark) session is doing. Same "don't clobber a live
session" caution HANDOFF.md already established for crt-vm now applies
to potato too -- check `~/.crt/thoughts.log` on potato for recent activity
and ask before editing a file that session might be mid-editing.

**mandark now runs a real transcription server**: `bin/mandark-whisper-server.py`,
systemd service `crt-whisper-server.service`, faster-whisper base.en,
port 8991, `http://192.168.0.27:8991/transcribe` (POST WAV -> `{"text":...}`).
potato's `crt-stt-solo.py` offloads transcription here via
`CRT_WHISPER_SERVER` (wired into `crt-console.sh`'s stt window tonight).

**dexter/crt-vm (the old Windows-host+VirtualBox setup) is now legacy** --
`bin/dexter-whisper-server.py` and any `CRT_AUDIO_OUT_URL`/dexter-bridge
reference is from that era and does NOT apply to potato's real hardware.
Tonight's earcon fix (below) is the concrete example of this era-mismatch
causing a real silent bug -- expect more like it if anything else still
assumes the old dexter-bridge exists.

## What's built, fixed, and VERIFIED LIVE tonight (2026-07-23)

- **STT offload**: potato -> mandark-whisper-server, confirmed working
  end-to-end (curl test from potato succeeded, real transcriptions
  observed in stt.log going through the remote path).
- **`CRT_AUDIO_DEV` fixed**: potato's mic capture is ONLY valid on
  `plughw:1,0` (card 1, "KT USB Audio") -- card 0 (bcm2835 onboard) is
  playback-only, has no capture subdevice at all. The old default
  (`plughw:0,0`) silently exits the whole sole-reader process with no
  error if used. Pinned in `crt-console.sh`'s stt launch line. Real fix
  (resolve by device NAME, not a hardcoded index) still open --
  see FOCUS.md, and keep the hardcoded override available alongside
  any name-resolution path, don't replace it outright (Zach's explicit
  instruction).
- **`crt-earcon.sh` device routing fixed**: used to POST to a
  dexter-hosted audio bridge that doesn't exist on potato's bare-metal
  setup -- silent no-op, the root cause of "no beeps on TV or handset"
  for potentially a while. Now plays directly via `plughw:2,0` (HDMI/TV)
  and `plughw:1,0` (USB/handset) -- BOTH confirmed audible live, in
  order, by Zach on the actual hardware.
- **New earcons wired into the live pipeline**: `heard` (VAD threshold
  crossed, default OFF -- fires on all room chatter, would be constant
  noise on by default), `addressed` (STT wake-gate passed, default ON),
  `control` (CONTROL keystroke recognized, default ON), `thinking`
  (fires the instant `crt-secretary.py` escalates to Claude, before the
  real wait). All fire-and-forget (Popen), never block the sole mic
  reader or the secretary's routing.
- **Secretary escalation latency cut**: `CLAUDE_IDLE_SECS` 3->1.5 in
  `crt-secretary.py`, with a grace-check hardening so a lower threshold
  can't silently truncate a reply mid-thought (re-verifies idle before
  finalizing rather than needing to re-open/append to an already-spoken
  reply). Root cause of the felt ~6s round-trip was THIS fixed wait, not
  STT/whisper (measured 1-3s).
- **`bin/crt-calibration-game.py` built and deployed** (potato tmux
  window 9, "game"). Interactive: tails `stt.log` continuously in a
  background thread (fixed tonight -- the first version's tailer only
  ran during a fixed round window and went dead during blocking
  `input()` prompts between rounds, silently dropping speech in the
  gaps), splashes recognized words around Zach's own braille-art potato
  scored by `crt-wake-pool.py`'s `difflib`-based similarity, offers to
  save recurring near-misses into `stt-fixups.json` as confirmed
  aliases, plus an earcon device-confirmation round. Verified with an
  offline synthetic-log test before deploying (no live mic needed for
  that check) -- NOT yet verified with Zach actually playing it live
  after the tailer fix; that's the natural next live-test.
- **`bin/crt-wake-pool.py` deployed to potato** (it existed on mandark's
  main but had NEVER been copied to potato at all -- the game script's
  first run there crashed with `FileNotFoundError` until this was fixed).

## Major open findings, fully specced in FOCUS.md's 2026-07-23 entries --
## read FOCUS.md itself for full reasoning, this is just the index

1. **Dormant autonomous wake-judge system**: `bin/crt-wake-pool.py` +
   `bin/crt-wake-judge.py` + `WAKE-TUNING-STATE.md` already implement
   almost exactly an "autonomous self-tuning judge" (rich real judgment
   log from 2026-07-21 proves it ran live once -- on the OLD crt-vm, not
   potato, per one log entry literally saying "it's a virtual machine").
   The ONE missing piece: an arm-window state machine in
   `crt-stt-solo.py` that would call `consume_arm_with_followup()`/
   `check_arm_timeout()` -- these names are referenced in
   `crt-wake-judge.py`'s prompt-building code and the judgment log's own
   vocabulary, but grep confirms **zero implementations exist anywhere**.
   This is also the same feature as the "sticky conversation window" gap
   (item 2 below) -- build once, not two separate things.
2. **No sticky-wake-window**: every utterance needs the wake word fresh,
   confirmed live (a real conversation where 4 follow-ups in a row got
   silently gate-dropped after a successful wake). Same feature as #1.
3. **Whisper is the wrong tool for instant wake-detection on this Pi**:
   measured live, `tiny.en` best-case ~2.8-4s encode time even on a short
   clip with reduced audio context -- a hardware CPU throughput ceiling,
   not a config problem. Real fix: Vosk or Sherpa-ONNX (Kaldi-based,
   <100ms, built for weak ARM hardware) for wake-word spotting
   specifically, NOT whisper at any size. Full whisper transcription for
   actual request content (post-wake) is fine as-is.
4. **MAXUTT=20/TRAIL=0.8 in `crt-stt-solo.py` is a real architecture
   limit, confirmed live tonight**: continuous speech with no real pause
   rides the full 20s hard cap before an utterance even gets cut, THEN
   queues for transcription -- this is why the console can feel
   unresponsive during continuous talking, independent of whisper/network
   speed. The batch-VAD design (wait for silence or a cap, transcribe the
   whole blob) fundamentally cannot be snappy mid-speech without a real
   streaming STT layer (ties directly to item 3's Vosk/Sherpa-ONNX
   pivot) -- tuning TRAIL/MAXUTT numbers alone won't fix this, it needs a
   different mechanism for the wake-detection job specifically.
5. **Acoustic loopback self-test idea** (not built): play a known tone,
   record via the mic, detect it -- would give a real audio-diagnostic
   test (vs exit-code-only checks that let tonight's silent earcon bug
   go unnoticed) and double as a noise-floor calibration tool for
   `CRT_VAD_THRESHOLD` tuning.

See `HANDOFF.md`'s "What's actually running right now" section for the
older (2026-07-20, now-superseded-by-the-above) live layout description.

## Sixth wave (2026-07-20): live access, real bugs found and fixed on hardware
- **VM deploy gap closed**: the VM's `~/crt` (no git, plain deploy target)
  was ~a day behind this repo; nothing from waves 1-5 had ever been
  deployed. New `bin/crt-sync-vm.sh` (status/pull/push, sha256 diff +
  tar-over-ssh, no rsync on either box) replaces manual diffing. Policy:
  safe to overwrite the VM, never dexter; always `pull` VM-only work first.
  Recovered 4 files that only ever existed on the VM (`stt-fixups.json` —
  real confirmed STT mis-hear mappings — plus 3 prototype scripts) before
  the first push.
- **VM hardware-check timer**: installed and *actually verified* (not just
  written) — ran the real offline test suite against real ALSA/tmux on
  crt-vm (126+ checks, all green), confirmed earcons/TTS/sideband all exit
  0 on real hardware. Reworked to a plain script
  (`bin/crt-vm-hardware-check.sh`), not a `claude -p` call — Zach's
  question ("can't this be done without claude?") was right, every check
  is mechanical.
- **OctoPrint confirmed reachable** at `192.168.0.43` (HTTP 302, alive).
- **Real STT pipeline bug found and fixed live**: `stt-feed.sh` was
  silently discarding every utterance after capture (pipefail + arecord's
  expected SIGPIPE on VAD cutoff made the whole pipeline register as
  "failed" even though sox succeeded) — see `HANDOFF.md` for the full
  mechanism. This was likely broken for a while; nobody could tell because
  it failed silently with no error output anywhere.
- **A real regression found and permanently fixed**: the previous
  session's hand-assembled live layout (single-reader `crt-stt-solo.py` +
  `crt-claude-bridge.py` + `crt-monologue.py` pretty-print dialogue pane,
  window 1) worked great for an evening, was never wired into
  `bin/crt-console.sh`, and got silently clobbered by a routine VM reboot.
  Now wired directly into `crt-console.sh`'s own code (not just
  documented) so a future respawn can't lose it again. **Still open**: a
  visual signal of the USER's own speech in window 1 (currently only shows
  claude's replies) — flagged, not built.
- **`bin/crt-levels.sh` missing exec bit** (never worked, unrelated to any
  reboot) — fixed.
- Full VM power-cycle (`VBoxManage controlvm crt-vm poweroff` + `startvm
  --type gui`) was needed at one point — a guest-level `reboot` alone
  doesn't re-establish VirtualBox's audio/USB device bindings, since those
  attach at VM power-on, not guest boot. Worth remembering for the MIDI
  blocker too (`VBoxManage usbattach` "busy with a previous request").

Older waves below are historical record from prior sessions, kept for
context — not all still accurate against current `HANDOFF.md`.

---

Previously last updated: 2026-07-19 night, still no live VM/mic access all session —
no new STT transcriptions came in, so no new error-pattern learning this
session; see `STT-MECHANISM.md` + `~/.crt/stt.log` for that work, still
the standing top priority per `CLAUDE.md`. First commit of this session's
work (`cef8fd1`) is pushed to `origin` (a local bare repo — pushing it
didn't need network, unlike dexter/VM access which this session never had).
A second wave of work (persona-channel mechanism, the secretary wrapper)
happened after that push and is **NOT yet committed** — check `git status`
next session before assuming it's saved anywhere but the working tree.

## What this session did
Chris asked for: (1) an "idle bait" workflow — job reports/blockers
surfaced through the day as cute, low-friction hooks, never naggy enough
he'd turn the TV off, interacted with by picking up the handset; (2)
continued STT refinement (none to do this session — no live traffic);
(3) more expressive earpiece/computer beeps; (4) sidetone investigation;
(5) deeper philosophy digging; (6) keep generating tasks/CAD/RFPs, don't
run dry. All design + scaffolding, **nothing hardware-verified** (no VM
access this session).

## New docs (read these for the actual designs)
- `IDLE-BAIT.md` — the core workflow: report/question sources -> on-screen
  teaser -> earcon (rate-limited, one-shot per item, no nagging) -> pickup
  -> secretary answers by voice. This is the design Chris's mid-session
  note ("cute idle bait... never annoying... he'd turn the TV off")
  directly shaped — that line is close to load-bearing, re-read it if a
  future change threatens to make this feel like a notification badge.
- `SIDETONE.md` — what sidetone is, why it's actually an STT-accuracy
  lever (not cosmetic — ties to VAD-clipping/denoise-distortion failure
  modes in `STT-MECHANISM.md`), and a real open question it surfaced (see
  below).
- `PHILOSOPHY.md` — seven named principles (answer-first-be-right-later,
  cost-of-ignoring-near-zero, restraint-as-trust, verbs-not-menus,
  one-body-several-selves, imperfection-as-character, local-first) plus
  open threads at the bottom worth revisiting.
- `RFP-GALLERY.md`, `RFP-PAYPHONE.md` — design briefs for the two
  gallery/art installation ideas in `PARKING-LOT.md`, fleshed out enough
  to hand to a collaborator. **Payphone brief has a real legal-risk
  section** (real-money payout = gambling device in most jurisdictions) —
  read that before anyone gets excited about the coin mechanism.
- `cad/CAD-BACKLOG.md` — full inventory of printed parts, existing +
  speculative, with what's blocked on what.

## New scripts (all untested against real hardware/audio)
- `bin/crt-earcon.sh` — five tones (bait/question/success/ack/oops) via
  sox synth, routed through the same device logic as `crt-tts.py`
  (dexter bridge for tv/handset, local aplay otherwise).
- `bin/crt-report.sh` — writes `~/reports/crt/LATEST.md` in the
  scheduler's exact shape (see `Project Archive/scheduler`) from inside
  this interactive session, so idle-bait has real content before crt's
  registered-but-dormant nightly Tier 2 batch ever runs. **Already used
  once this session** — `~/reports/crt/2026-07-19.md` has a real entry.
- `bin/crt-idle-teaser.sh` — polling watcher, turns new report/question
  lines into one `crt-think.sh` teaser + (judgment calls only) one earcon.
  Deliberately a separate process from `crt-monologue.sh`, not merged in —
  see `PHILOSOPHY.md`'s open thread on narration vs. restraint.
- `bin/crt-announce.sh` — **bugfix**: was still passing an old `plughw:*`
  guess as the TV device; `crt-tts.py`'s dexter bridge (confirmed working
  via live human test per its own header) expects the literal string
  `"tv"`. Fixed.
- `cad/ir_blaster_mount.scad`, `cad/earcon_grille.scad` — new speculative
  parts, no measurements, see `cad/CAD-BACKLOG.md`.

## Open questions logged (`.claude/QUESTIONS.md`, need Chris)
1. **Is the handset earpiece guest-local ALSA or only host-bridged via
   dexter?** Blocks whether software sidetone is even possible — see
   `SIDETONE.md`. `crt-tts.py`'s `DEXTER_DEVICES` now includes `"handset"`
   alongside `"tv"`, which is a real architecture drift from
   `AUDIO-ROUTING.md`'s original assumption (handset stays guest-local).
   Worth resolving early since it also affects the hardware-sidetone
   recommendation (design the mic/earpiece wiring with a passive tap from
   the start, per `SIDETONE.md` option 1).
2. **Idle-bait quiet hours** — what hours should the earcon go silent?

## Second wave, after the first push (uncommitted)
- `PERSONA-CHANNEL.md` — decided the persona-channel indicator mechanism
  (`cad/CAD-BACKLOG.md`'s open item): a real detented rotary switch Chris
  turns by hand, not a servo/LED display — control and indicator are the
  same object, can't desync, works unpowered. Still needs a specific
  switch part sourced before the faceplate CAD can be drawn.
- `bin/crt-secretary.py` — first real implementation of the secretary
  wrapper (`SECRETARY.md` steps 1-4). Local-answer path ("what's up" reads
  `~/reports/crt/LATEST.md` + `QUESTIONS.md` directly, no Claude call)
  tested standalone and works. Claude-routing path (tmux send-keys + poll
  capture-pane for idle) is an **untested heuristic** — flagged as the
  riskiest part of the design, needs a live session to tune.
  **Not wired into `stt-feed.sh` yet** — that still does raw send-keys.
- `bin/crt-print.sh` + `bin/crt-print-render.py` — text-to-image-to-printer
  path for the secretary's "print full detail" option, wrapping the
  already-installed `catprint` tool. Render tested locally (produces a
  correct PNG); the actual `catprint` invocation/device flag and the
  384px Phomemo head-width guess are unverified against a real printer.

## Third wave: offline-only pass (predictive text, tests, tone taxonomy)
Explicitly scoped to "what we can do without dexter" — all genuinely
offline-buildable/testable, unlike waves 1-2's mostly-design docs:
- **Terminal-size auto-detect** (`crt-pager.py`, `crt-monologue.sh`) — was
  hardcoded 40x15, now env override > real terminal size > hardware
  fallback, so a resized VM window or running on a different machine
  renders correctly instead of silently assuming the wrong geometry.
- **`tests/`** — a real offline test suite, first one this project has had:
  `run_tests.sh` runs shell-syntax checks on all of `bin/*.sh`,
  `crt-pager.py`'s wrap/render/detect_size logic, `crt-monologue.sh`'s
  width-resolution precedence, and `crt-predict.py`'s model/guess logic.
  **All green right now** (`bash tests/run_tests.sh`) — rerun after any
  future change to those files, this is real regression coverage, not
  aspirational.
- **`bin/crt-predict.py` + wiring into `crt-stt-solo.py`** — resolves a
  TODO that was already sitting in `crt-stt-solo.py`'s source. Cheap
  whole-utterance + bigram frequency model over `~/.crt/stt.log`
  (hour-of-day bucketed), flashes a guess the instant an utterance ends,
  before whisper has run — `emit()` already unconditionally overwrites the
  flash with the real transcription once whisper returns, so this was a
  small, safe addition. **Opt-in** (`CRT_PREDICT_FLASH=1`), off by
  default — nobody's heard/seen it live yet, and a wrong guess flashing
  needs a human judgment call on whether it reads as charming or
  confusing (see `PHILOSOPHY.md` #6). Model needs `crt-predict.py build`
  run against a real `stt.log` before it has anything to guess from — untested
  against real transcript history, only against synthetic data in
  `tests/test_predict.py`.
- **`EXPRESSIVE-TONE.md`** — a register taxonomy (clipped/urgent,
  warm/curious, content/settled, wistful/quiet, public/announcement)
  mapping fade-out length + pitch contour (audio) and line brevity (text)
  to the same emotional dial. Implemented as `CRT_EARCON_FADE_SCALE` in
  `crt-earcon.sh` (one dial scales every tone's fade-out) plus two new
  contours, `curious` and `content`. All 7 tones × 3 fade scales
  synth-tested this session (sox renders clean); still unheard by a human.

## Fourth wave: vision + scheduler wiring, then ramped down
`DEVELOPMENT-WORKFLOW.md` ties everything into a three-tier autonomy model
(mandark disposable-clone batch / new VM-resident hardware check / this
kind of interactive session). New this wave: `VM-JOBS.md` +
`.claude/commands/vm-hardware-check.md` + `systemd/crt-vm-hardware-check.
{service,timer}` (not installed, no VM access) + `bin/crt-sync-vm-reports.
sh` (pull-based, untested). **Real scheduler wiring done**: `schedule/
crt.conf` (outside this repo, in Project Archive/scheduler) now has a
`DEPLOY_FRESH_CMD`/`DEPLOY_CMD` pair surfacing a stale/missing VM-report
sync in the daily `morning-report.sh` aggregate — verified the probe
itself runs correctly in isolation. Also: `SUPERVISOR.md` +
`crt-secretary.py` refactored to a playbook registry (status/run_tests/
what_time, 10 tests), `HOOKSWITCH.md` + a real debounce fix (was a genuine
bug, no hardware needed to find or fix it), `DISPLAY-CALIBRATION.md` +
`crt-calibrate-display.py` (overscan safe-margin game, 15 tests),
`SIDEBAND.md` + `crt-sideband.sh` (ambient presence tone, 8 tests). Test
suite is now 56 checks, all green (`bash tests/run_tests.sh`).
**Explicitly stopped here on the user's instruction** ("ramp this down")
rather than continuing to expand scope.

## Fifth wave: "full steam" — all 8 offline-safe FOCUS.md items shipped
User asked to work through everything buildable without VM/dexter access,
self-pacing usage (no live usage-% tool available, so paced by chunking +
frequent commits instead). All landed, tested, committed, pushed:
`fa31856`/`082db9e`/`7fde922`/`16c816b`/`ae639b6` (see git log for exact
diffs) —
1. `stt-feed.sh` routes through `crt-secretary.py` when `CRT_SECRETARY=1`
   (default off).
2. `crt-pager.py`/`crt-monologue.sh` now consume `~/.crt/display.conf`'s
   safe margin.
3. `crt-earcon.sh`'s `bait`/`curious`/`question`/`content` are continuous
   glissando sweeps now, not stepped notes.
4. `crt-idle-teaser.sh` teaser lines carry an ANSI color per register into
   `thoughts.log`.
5. `crt-tts.py` has `--mood`/`--pitch-semitones`/`--rate-mult`/
   `--volume-mult`, applied via a sox post-process step (works for both
   backends despite neither having a native pitch knob for this).
6. Sideband state transitions wired: `crt-stt-solo.py` opt-in
   (`CRT_SIDEBAND=1`) listening/thinking; `crt-tts.py`/`crt-earcon.sh`
   always-on mute-duck (inert unless `crt-sideband.sh` is running).
7. `crt-secretary.py` gained a `calibrate` playbook (single-shot pattern
   render only, not the interactive game).
8. Claude-fallthrough requests now log to `~/.crt/fallthrough.log`.

Test suite grew from 76 to **126 checks**, still all green. `FOCUS.md`'s
offline-safe section marked DONE — nothing left there for an unattended
pass until a new batch gets registered. A recurring cron
(`092c9b41`, every 3h, session-only/expires in 7 days) checks
`BLOCKERS.md`'s crt section for anything you've cleared and reports back
— it does not resolve/delete entries itself.

## Not done / explicitly out of scope this session
- Nothing hardware-verified (no VM/mic/audio access this session at all —
  pure design + scaffolding).
- The secretary wrapper itself (`SECRETARY.md` steps 1-4) — still the
  actual next concrete build once someone's back on the VM; idle-bait is
  the lure toward it, not a replacement for it.
- No STT error-pattern learning (no live transcriptions this session).

## Seventh wave (2026-07-22): potato migration + self-repair scoping
`potato` (Raspberry Pi, 192.168.0.45, user `vkv`, sudo added to that
account) is the new migration target, replacing dexter/crt-vm eventually.
Repo deployed there (`~/crt`, tar-over-ssh, 164 files), offline test suite
green, `install.sh` run (whisper.cpp built, ALSA/autologin wired), `claude`
logged in as zach@nomac.org on tty1 — confirmed working live. **No mic
hardware attached to potato yet** (`arecord -l` empty) — nothing audio-side
is verifiable until that's physically wired.

`CRT_CLAUDE_ARGS="--permission-mode bypassPermissions"` set in potato's
`~/.bash_profile` (zero-prompt autonomy, explicitly scoped to this trusted
console per Zach). New tonight: `SELF-REPAIR.md` + `bin/crt-self-repair.sh`
+ `systemd/crt-self-repair.{service,timer}` — a nightly unattended
`claude -p` pass, potato-only, licensed to tune STT/VAD settings (and
beyond) aggressively, gated ONLY by a forced pre/post git commit (so any
change is one `git revert` away) — read `SELF-REPAIR.md` in full before
touching this, it has the exact scoping Zach gave and what's deliberately
NOT built yet (off-box visibility, push access, actual tuning numbers —
none of that ran, potato went unreachable mid-move before the timer could
even be installed).

**Not yet done**: `git init` on potato's `~/crt` (was about to run this
when potato dropped off the network — no route to host, mid-physical-move
per Zach). The self-repair timer/service files exist in THIS repo but were
never copied to potato or `systemctl enable`'d. Service-user setup (push/
pull access, modeled on `svc-vaporwave`, likely pull-only at first) is
explicitly deferred — needs potato back up and a live design conversation
about the `/srv/` reporting mechanism first.

**Update, later same night — potato came back on an unknown IP.** Old
address (192.168.0.45) went dead mid-move; a full subnet scan found no
other host with SSH open. Zach was physically at potato's monitor but the
text was too small to read the IP, and it booted straight into the
tmux `book` window instead of `claude` (window 0) — **confirmed
NOT a bug**, that's `crt-console.sh`'s intentional boot-default (see its
own 2026-07-21 comment re: scanner-keystroke focus) — don't "fix" it in a
future pass. Full blocker writeup + the one real code-shaped task
(potato has no avahi/mDNS — `potato.local` doesn't resolve, install
`avahi-daemon` once reachable so this can't happen again) is in
`.claude/FOCUS.md`'s new "potato migration" section — read that before
resuming this thread, not just this file.

## Pick up next, in order
1. Get back on `crt-vm` and answer question #1 above — it gates both
   sidetone and whether `crt-idle-teaser.sh`'s earcon calls will even
   reach the handset correctly.
2. Smoke-test `crt-earcon.sh`'s five tones by ear (nobody has heard them).
3. Run `crt-report.sh` + `crt-idle-teaser.sh` live for a day, see if the
   teaser cadence actually feels like bait or like a nag — this is a
   judgment call only a live test can settle, not more design.
4. Keep building the secretary wrapper (`SECRETARY.md`) — the actual
   payoff once idle-bait gets someone to pick up.
