# Audio capture debugging — the "stops detecting" bug

The recurring failure: STT works, then mid-session the mic signal goes quiet
with the ALSA mixer still correct — VirtualBox's emulated capture goes **stale**
when the capture device is opened/closed repeatedly (per-utterance) or when a
second reader (the dsnoop meter) starves the primary. Symptoms and the two
already-shipped mitigations are documented in `README.md` and `HANDOFF.md`.

This file tracks **multiple independent angles of attack** so they can be built
and tested in parallel (interactive sessions on the VM, plus overnight batches
that advance the code). Each approach is opt-in and does not disturb the working
pipeline. **None of these are hardware-verified yet** — they were written on the
dev box (mandark), which has no handset/VM. Each needs a run on `crt-vm`.

## Status legend
`[code]` implemented, needs VM test · `[partial]` scaffolded · `[idea]` sketch only

---

## Approach A — capture watchdog (auto re-open) `[code]`
`bin/crt-capture-watchdog.sh`

The narrowest fix for the exact reported symptom. A background daemon holds one
continuous reader on the mic and computes a rolling level. If the signal stays
**flat** (near-zero peak variance) for `CRT_WD_FLAT_SECS` — i.e. the capture has
gone stale, not merely silent — it declares the device dead and **recovers**:
kills stale `arecord`/`sox` holders, re-asserts the mixer (Input Source=Line,
Capture 100%), and (opt-in) restarts the `stt` tmux window so `stt-feed.sh`
re-opens a fresh capture. Logs every event to `~/.crt/watchdog.log` so the
failure cadence can be characterized.

Test: run alongside the normal console; force staleness (let it idle, or toggle
the VBox audio controller) and confirm it recovers within a few seconds.

## Approach B — single-reader console (eliminate dsnoop) `[promoted, now the default]`
`bin/crt-stt-solo.py` extended with `CRT_STT_SINK=claude`, wired into `bin/crt-console.sh`

Root-cause structural fix: the staleness class that comes from *multiple readers*
(meter + stt-feed both on dsnoop) simply cannot happen if exactly **one** process
ever touches the mic. `crt-stt-solo.py` already is that one process for STT-only;
extending it to also type into the Claude tmux pane makes it a drop-in
replacement for the whole stt-feed + dsnoop-meter stack.

**Verified live 2026-07-19/20** (real handset session on crt-vm) and, as of
2026-07-20, promoted into `bin/crt-console.sh` itself as the actual boot
default (see that file's own comments, and `vault:crt/HANDOFF-20260829.md`'s
"what's running" section) — `bin/crt-console-solo.sh` is no longer the only way to get this,
it's just a thinner standalone variant of the same idea. `stt-feed.sh` +
`crt-levels.sh` still exist (used by `CRT_SECRETARY`/stdout debug modes) but
are no longer what boots by default.

## Approach C — proactive keep-alive heartbeat `[code]`
Built into Approach A's watchdog as `CRT_WD_KEEPALIVE=1`

Rather than only reacting to staleness, periodically nudge the emulated ADC so it
never goes cold: the watchdog's single always-open stream is itself a keep-warm;
with keepalive on it additionally re-asserts the mixer every `CRT_WD_KEEPALIVE_SECS`
even when the signal looks fine. Cheap insurance; may make A's reactive path rare.

## Approach D — audio doctor / liveness telemetry `[code]`
`bin/crt-audio-doctor.sh`

Research instrument, not a fix. Two modes: `check` (one-shot health report — lists
cards, the Input Source/Capture mixer state, and a 3 s live RMS/peak sample, exit
non-zero if dead) and `monitor` (append a timestamped RMS/peak sample every N s to
a CSV, so a whole session's capture behaviour can be plotted afterwards). The goal
is to answer the open question: does staleness correlate with idle time, with
utterance boundaries, or with a fixed interval? That determines which of A/B/C is
the real fix vs a band-aid.

Test: `bin/crt-audio-doctor.sh check`; `bin/crt-audio-doctor.sh monitor` during a
session, then inspect `~/.crt/liveness.csv`.

## Approach E — capture-backend variants `[idea]`
Config-only alternatives to try when A–D don't fully settle it:
- **arecord buffer tuning**: `--buffer-size`/`--period-size`/`-F` to avoid xruns
  that may trigger the VBox stall; try larger buffers.
- **Different PCM path**: `hw:0,0` vs `plughw:0,0` vs a fresh `dsnoop`/`dmix`
  rate-matched to 16 kHz to avoid the plug plugin's resample churn.
- **PipeWire/`parecord`** as the capture source instead of raw ALSA, letting the
  guest audio server own the device lifecycle.
- **VirtualBox audio backend**: try `--audiocontroller hda` vs `ac97`, and the
  host audio driver, from the dexter side (VBoxManage). Host-side, needs dexter.

These are enumerated so an overnight job (or a VM session) can pick one, wire a
toggle, and measure with Approach D — not to be all built blindly.

## Approach F — streaming / rolling-window STT `[partial]` (nightly batch: research + prototype)

Right now whisper.cpp runs **batch per VAD-cut utterance**: it waits for the
phrase to end, transcribes the whole clip once, and never revises. Web/streaming
ASR instead emits partial words and *revises them as more audio + language-model
context arrive* (online transducer/attention decoders committing late). That
self-correction is what makes browser dictation feel live.

Whisper isn't natively streaming, but two routes approximate it:
- **whisper.cpp `stream`** example — sliding window, partial results (crude; not
  even built here yet — `make stream` in whisper.cpp).
- **LocalAgreement rolling window** (à la `whisper_streaming`): re-decode a
  growing buffer every ~0.5 s and only *commit* a word once two consecutive
  windows agree on it, revising the uncommitted tail. Lower latency + context
  self-correction.

**Scope for the nightly batch (code only, no VM):** research both, and prototype
the LocalAgreement approach as a NEW opt-in engine (e.g. `bin/crt-stt-stream.py`)
alongside `crt-stt-solo.py` — do NOT replace the working batch engine. Wire the
same sinks (stdout / claude) and the same hallucination + noise filters. Leave a
clear note on CPU cost (re-decoding is much heavier than batch) since this runs
on a VM. Honest caveat in code: not hardware-verified.

**Reality check (already assessed 2026-07-19):** for a short-command console,
streaming mainly buys latency and long-form self-correction; it will NOT fix
noise-driven hallucinations — that's what the highpass/noisered filter (now in
crt-stt-solo.py) and a better VAD (Silero) are for. So treat F as a
feel/latency upgrade, not the noise fix.

**Prototype built (2026-07-19 nightly batch):** `bin/crt-stt-stream.py` +
`bin/crt-stt-stream-view.sh`. Same VAD/capture/denoise/hallucination-filter/
log conventions as `crt-stt-solo.py`; the new part is `local_agreement_commit()`
— every `CRT_STREAM_INTERVAL` (default 0.7s) it re-decodes the whole
utterance-so-far and commits the prefix that agrees with the immediately
prior decode (LocalAgreement-2), printing committed words plain and the
uncommitted tail dimmed. On utterance end it does one more full decode and
that — not the partial trail — is what actually reaches the log/claude sink,
so accuracy of the *final* result is unaffected either way; only the live
feel changes. Verified so far: syntax/compile clean, `local_agreement_commit`
unit-tested (agreement + disagreement-halts-commit cases), and `transcribe()`
smoke-tested against a real local whisper-cli + tiny.en model on the dev box
(silence in, empty string out, no crash). **NOT verified:** live mic
behavior, whether 0.7s ticks feel responsive vs. janky, or whether the
guest's CPU cap (see COST WARNING in the file's header) makes this unusably
slow without `CRT_WHISPER_SERVER` pointed at dexter — needs a VM/handset
session with real speech.

---

## The handset "0.1x above baseline" measurement should be re-run (2026-07-25)

The 2026-07-23 backlog entry recorded the strongest audio finding this
project has: a tone played on the handset device (`plughw:1,0`) while capture was
running showed **0.1x above baseline** in the recording, read as "this USB
adapter cannot reliably play and record at once — a hardware/driver limit,
not a routing bug." The whole CTL-file capture-duck feature (cycles 3, 4 and
`fe46ac1`) was built on that reading, and stability-bar item 2 is waiting on a
re-run of the tool to confirm it.

`bin/crt-earcon-loopback-test.py` could not have established it. Until
2026-07-25 it sent sox's and aplay's exit status **and** stderr to
`/dev/null`, so "played, and the mic could not hear it" and "never played at
all" produced byte-identical output and it always reported the first. Those
two indict opposite things — a USB adapter versus a device name — and this
project's audio history is overwhelmingly the second (`plughw:0,0` with no
capture stream, the dead dexter earcon URL, the `:8992` default).

The tool now has a third verdict (`INCONCLUSIVE`) and exits 3 for it, so the
re-run answers the question either way. **Nothing here overturns the original
reading** — 0.1x is also exactly what a working-but-deafened adapter looks
like, and the tone did register on the TV path in the same session, which
argues aplay was working at least there. It is one command's worth of
uncertainty that no longer has to be carried:

    python3 bin/crt-earcon-loopback-test.py handset ; echo "exit $?"

`exit 3` means the measurement never happened and the finding is unsupported.
`exit 1` with a ratio near 0.1 means the finding stands and the duck is right.

---

## How the overnight batch should use this
Advance approaches marked `[idea]`/`[partial]` toward `[code]`, or harden the
`[code]` ones (edge cases, logging, a test harness). Do **not** claim any of them
hardware-verified — that requires a human on the VM. Prefer breadth across
approaches over depth on one.
