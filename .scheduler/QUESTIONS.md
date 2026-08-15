# Questions -- retired 2026-08-14, migrated to GitHub issues

**Open questions now live at https://github.com/hf7y/crt/issues.** This file
is a pointer, not a second source of truth. Do not append questions here --
file an issue. Ecosystem policy as of 2026-08-07: `hf7y/scheduler#66`, swept
by `hf7y/realisateur#230`, root cause `hf7y/realisateur#187`.

This retires the inline `> ` reply protocol along with the file. Answer a
question by commenting on its issue; Zach comments and leaves the issue open.

## Where the open questions went

| Question | Now |
|---|---|
| `ssh potato` fails every cycle -- why, structurally? | [#8](https://github.com/hf7y/crt/issues/8) |
| Is `CRT_WAKE_ARM_SECS=12` right, now that the timing-reference confound is fixed? | [#9](https://github.com/hf7y/crt/issues/9) |
| Should `CRT_WAKE_JUDGE_ENABLED` be turned on? | [#10](https://github.com/hf7y/crt/issues/10) |
| Is potato (Pi 3 Model B+) the right long-term hardware? | [#12](https://github.com/hf7y/crt/issues/12) |
| Stand up a second whisper server on dexter | [#13](https://github.com/hf7y/crt/issues/13) |
| potato<->mandark flakiness is one root cause, never measured | [#14](https://github.com/hf7y/crt/issues/14) |
| What happens to the remote-Claude bridge on an always-on host? | [#15](https://github.com/hf7y/crt/issues/15) |
| Does potato get PUSH access, or stay pull-only? | [#16](https://github.com/hf7y/crt/issues/16) |
| Trivia distill stage needs a Gemini key on potato | [#17](https://github.com/hf7y/crt/issues/17) |
| Dual-output earcons, per-earcon-type device | [#18](https://github.com/hf7y/crt/issues/18) |

## What was NOT migrated, and why

- **Is the handset earpiece wired to `crt-vm` or reachable only via dexter?**
  Answered inline by Zach 2026-07-20: only via dexter, and the two halves stay
  conceptually separate until bare metal. The answer is in git and the
  architecture followed it; `crt-vm` no longer exists.
- **Is the handset play-while-capture finding real, by ear?** Yes -- settled
  by live measurement 2026-07-28, twice, including against the dmix/dsnoop
  shared devices. See the FOCUS stub's milestone table.
- **Six `ssh potato` auth-rejected entries (2026-07-24).** Cleared 2026-07-27:
  a working credential exists (`vkv_deploy_key`). The remaining reachability
  problem is a different and larger one -- #8.
- **`~/reports/crt` write access.** Fixed 2026-07-24, confirmed with a real
  touch+rm.
- **"The offline-safe backlog appears exhausted."** A status note, not a
  question, and false as of this migration -- #19, #20, #21, #22, #23, #24 and
  #30 are all offline-safe.

Full history, including every inline `> ` reply, is in git before this commit.
