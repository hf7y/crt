# CONTRACT -- `sonne`

ring the handset: voice front end for a terminal

Derived 2026-07-30 from the tooling that actually existed in `crt`.
Where there was no stated contract before, this is the first one; that
is a finding about the old tree, recorded rather than hidden.

## The promise

```
sonne <subcommand> [args...]
```

| subcommand | promises | backed by |
|---|---|---|
| `crt-announce` | whatever `bin/crt-announce.sh` promised | `bin/crt-announce.sh` |
| `crt-attach-ssh-bridge` | whatever `bin/crt-attach-ssh-bridge.sh` promised | `bin/crt-attach-ssh-bridge.sh` |
| `crt-audio-doctor` | whatever `bin/crt-audio-doctor.sh` promised | `bin/crt-audio-doctor.sh` |
| `crt-bell-test` | whatever `bin/crt-bell-test.sh` promised | `bin/crt-bell-test.sh` |
| `crt-bibquotes-sync` | whatever `bin/crt-bibquotes-sync.sh` promised | `bin/crt-bibquotes-sync.sh` |
| `crt-brain-session` | whatever `bin/crt-brain-session.sh` promised | `bin/crt-brain-session.sh` |
| `crt-capture-watchdog` | whatever `bin/crt-capture-watchdog.sh` promised | `bin/crt-capture-watchdog.sh` |
| `crt-conf` | whatever `bin/crt-conf.sh` promised | `bin/crt-conf.sh` |
| `crt-console` | whatever `bin/crt-console.sh` promised | `bin/crt-console.sh` |
| `crt-console-solo` | whatever `bin/crt-console-solo.sh` promised | `bin/crt-console-solo.sh` |
| `crt-earcon` | whatever `bin/crt-earcon.sh` promised | `bin/crt-earcon.sh` |
| `crt-idle-bait` | whatever `bin/crt-idle-bait.sh` promised | `bin/crt-idle-bait.sh` |
| `crt-idle-teaser` | whatever `bin/crt-idle-teaser.sh` promised | `bin/crt-idle-teaser.sh` |
| `crt-levels` | whatever `bin/crt-levels.sh` promised | `bin/crt-levels.sh` |
| `crt-lib-audio-device` | whatever `bin/crt-lib-audio-device.sh` promised | `bin/crt-lib-audio-device.sh` |
| `crt-mandark-serve` | whatever `bin/crt-mandark-serve.sh` promised | `bin/crt-mandark-serve.sh` |
| `crt-mandark` | whatever `bin/crt-mandark.sh` promised | `bin/crt-mandark.sh` |
| `crt-monologue` | whatever `bin/crt-monologue.sh` promised | `bin/crt-monologue.sh` |
| `crt-print` | whatever `bin/crt-print.sh` promised | `bin/crt-print.sh` |
| `crt-report` | whatever `bin/crt-report.sh` promised | `bin/crt-report.sh` |
| `crt-ring` | whatever `bin/crt-ring.sh` promised | `bin/crt-ring.sh` |
| `crt-self-repair` | whatever `bin/crt-self-repair.sh` promised | `bin/crt-self-repair.sh` |
| `crt-senechal-guard` | whatever `bin/crt-senechal-guard.sh` promised | `bin/crt-senechal-guard.sh` |
| `crt-session-audit` | whatever `bin/crt-session-audit.sh` promised | `bin/crt-session-audit.sh` |
| `crt-sideband-set` | whatever `bin/crt-sideband-set.sh` promised | `bin/crt-sideband-set.sh` |
| `crt-sideband` | whatever `bin/crt-sideband.sh` promised | `bin/crt-sideband.sh` |
| `crt-stt` | whatever `bin/crt-stt.sh` promised | `bin/crt-stt.sh` |
| `crt-stt-speakback` | whatever `bin/crt-stt-speakback.sh` promised | `bin/crt-stt-speakback.sh` |
| `crt-stt-stream-view` | whatever `bin/crt-stt-stream-view.sh` promised | `bin/crt-stt-stream-view.sh` |
| `crt-stt-supervisor` | whatever `bin/crt-stt-supervisor.sh` promised | `bin/crt-stt-supervisor.sh` |
| `crt-think` | whatever `bin/crt-think.sh` promised | `bin/crt-think.sh` |
| `crt-voice-calibration` | whatever `bin/crt-voice-calibration.sh` promised | `bin/crt-voice-calibration.sh` |
| `hookswitch-listen` | whatever `bin/hookswitch-listen.sh` promised | `bin/hookswitch-listen.sh` |
| `setup-mandark-whisper-persistence` | whatever `bin/setup-mandark-whisper-persistence.sh` promised | `bin/setup-mandark-whisper-persistence.sh` |
| `setup-potato-audio-sharing` | whatever `bin/setup-potato-audio-sharing.sh` promised | `bin/setup-potato-audio-sharing.sh` |
| `stt-feed` | whatever `bin/stt-feed.sh` promised | `bin/stt-feed.sh` |
| `add-installdata-partition` | whatever `cad/add-installdata-partition.sh` promised | `cad/add-installdata-partition.sh` |
| `copy-candidate-preseeds` | whatever `cad/copy-candidate-preseeds.sh` promised | `cad/copy-candidate-preseeds.sh` |
| `copy-minimal-test` | whatever `cad/copy-minimal-test.sh` promised | `cad/copy-minimal-test.sh` |
| `export_stl` | whatever `cad/export_stl.sh` promised | `cad/export_stl.sh` |
| `finish-pi-usb` | whatever `cad/finish-pi-usb.sh` promised | `cad/finish-pi-usb.sh` |
| `flash-bootia32` | whatever `cad/flash-bootia32.sh` promised | `cad/flash-bootia32.sh` |
| `flash-pi-usb` | whatever `cad/flash-pi-usb.sh` promised | `cad/flash-pi-usb.sh` |
| `format-and-copy-installdata` | whatever `cad/format-and-copy-installdata.sh` promised | `cad/format-and-copy-installdata.sh` |
| `sideload-us-keyboard` | whatever `cad/sideload-us-keyboard.sh` promised | `cad/sideload-us-keyboard.sh` |
| `sideload-wifi` | whatever `cad/sideload-wifi.sh` promised | `cad/sideload-wifi.sh` |
| `update-diag-initrd` | whatever `cad/update-diag-initrd.sh` promised | `cad/update-diag-initrd.sh` |
| `install` | whatever `install.sh` promised | `install.sh` |

## Universal clauses

Every subcommand, without exception:

- exits **0 only if the promise was kept**. Never an exit-0 no-op.
- exits **4 (GAP)** if the tooling does not exist, and says what is missing.
- exits **6 (BLIND)** if it cannot read its domain. "I cannot see" is
  never reported as "nothing to report".
- **cannot spend money** unless it declares `--summon`, which has no
  short form and is never implied.

## Verification

```
./test/contract-test.sh <command>
```

The same assertions run against the legacy tooling and against `sonne`.
That is what makes "keeps the same contract" a measurement, not a claim.
