---
description: Hardware-verification pass that can ONLY run on crt-vm itself (real mic/display/printer access) -- see VM-JOBS.md for why this is a separate job from /nightly-batch, which explicitly cannot reach the VM.
---

<!-- Runs via systemd/crt-vm-hardware-check.timer, ON crt-vm, not through
     the mandark scheduler's disposable-clone engine. Real hardware is
     available here -- that's the entire point of this job existing
     separately from /nightly-batch. -->

This is the one autonomous job in this project allowed to touch real
hardware. Everything here was previously untestable and marked "NOT
hardware-verified" in this repo's own comments -- your job is to actually
verify what can be verified mechanically, and report honestly on what
still needs a human ear/eye.

## 1. Orient
`git pull`, then read `.claude/SESSION-STATE.md` and `HANDOFF.md` for what
changed since the last time this ran, plus `VM-JOBS.md` for this job's own
scope and boundaries.

## 2. Run the real offline test suite, for real this time
`bash tests/run_tests.sh`. This suite was written and validated entirely
off the VM (no mic/display/printer access there) -- confirm it still
passes here too. A pass here is a genuinely stronger signal than a pass on
the dev machine, since it now also exercises real ALSA/ffmpeg/tmux
presence, not just logic.

## 3. Hardware presence checks (mechanical, not judgment calls)
For each of these, report present/absent/working -- do NOT attempt to
fix physical wiring issues, just report exactly what's observed:
- `aplay -L` / `arecord -l` — what capture/playback devices actually
  exist. Cross-check against `AUDIO-ROUTING.md`'s assumptions and
  `.claude/QUESTIONS.md`'s open question about whether the handset
  earpiece is guest-local or host-bridged (SIDETONE.md needs this
  answered — if `aplay -L` settles it, answer the question inline in
  QUESTIONS.md per its own `> ` convention, don't just leave it open).
- Whisper backend reachable (local `whisper.cpp` binary present, or
  `CRT_WHISPER_SERVER` reachable if set).
- TTS backend (`piper` or `espeak-ng`) actually installed.
- `sox` present (needed by `crt-earcon.sh` and `crt-sideband.sh`).
- Hookswitch device (`CRT_HOOK_DEVICE`, if configured) present in
  `/dev/input/by-id/`.
- `catprint`/Phomemo printer reachable (see `bin/crt-print.sh`).

## 4. Exercise (not judge) the audio scripts
Run each of `crt-earcon.sh`'s tones, `crt-tts.py` with a short phrase, and
`crt-sideband.sh`'s `ensure_tone_wav` once each, purely to confirm they
run without error against the real hardware/ALSA stack (exit codes, no
stderr crashes). **Do not claim anything "sounds good"** -- that
judgment needs a human ear and is explicitly out of scope for this job.
Report exit status only.

## 5. Display calibration -- observe, don't decide
Run `bin/crt-calibrate-display.py show` and, if there's any way to capture
or describe the actual visible framebuffer state (a screenshot via the
VirtualBox tooling, if available), note it in the report. Do not run the
interactive `run` calibration loop unattended -- it needs a real human
answering by voice, that's the entire design (`DISPLAY-CALIBRATION.md`).

## 6. Stress-test what changed
Same bar as `/nightly-batch` step 4: read back through anything touched
this run for the actual failure modes this project has (stale/flatlined
capture, a second reader starving the first, a control-file race) rather
than declaring victory on exit codes alone.

## 7. Write the report AND sync it back
Write `~/reports/crt/$(date +%Y-%m-%d).md` (append if today's file
already exists, same convention as `bin/crt-report.sh`) and update
`~/reports/crt/LATEST.md`. This report lives on the VM's own filesystem —
it does **not** automatically reach mandark's `~/reports/crt/` where
`morning-report.sh` looks. That sync is `bin/crt-sync-vm-reports.sh`,
run FROM mandark (pull-based, since the VM has no push credential to
mandark) — note in the report whether this job's own timer is also
expected to trigger that sync, or whether it's still a manual pull (see
`VM-JOBS.md` for the current answer; this may change as that gets wired
up).

## 8. Commit
Same as `/nightly-batch`: commit and push anything changed (config fixes,
QUESTIONS.md answers found via hardware inspection) to `origin` before
finishing.
