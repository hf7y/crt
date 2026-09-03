# Moving crt off mandark and onto dexter

Zach's decision: this project's home — the git repo it pushes to,
and the always-on services it depends on — moves off `mandark`, a laptop that
comes and goes, onto `dexter`. This file was the checklist. It is now the
landing record: the live inventory, the rejected alternatives and the wiring
narrative are one `git log DEXTER-MOVE.md` away, and repeating them here would
be documenting a move that is over.

## What landed

| piece | where it ended up |
|---|---|
| the repo | `github.com/hf7y/crt`, not a bare repo on dexter. potato fetches from it, pull-only, holding no credential (crt#16). |
| STT | the `zaxon-whisper` container on dexter, `POST /inference`, published on loopback and on the tailnet (crt#133). mandark's `crt-whisper-server` unit, its `ufw` hole and its build tree and venv are gone. |
| the brain | `bin/crt-brain-shell.py` under an sshd forced command — no daemon, no tunnel, no port, replacing `bin/crt-remote-claude-bridge.py`. `tests/test_brain_ssh.py` holds the degrade contract and proves the SEND payload is never shell-interpreted. |
| potato | on the tailnet (crt#8), transcribing through dexter instead of on its own CPU. |

The direction of trust changed and is worth saying plainly: potato has a
narrow path inward now, where the mandark design gave it none.

## Still open

- `crt-remote-claude-bridge.service` and `crt-potato-tunnel.service` are
  installed-but-inactive on mandark. Keep, replace or delete is crt#15 — a
  corpse left installed is exactly the state this move warned about.
- Docs elsewhere that still name mandark as the STT host.

## Traps worth keeping

- **dexter runs two sshd**: the Windows host, and the WSL2 instance holding
  the brain. Authenticating against the wrong one fails with `Permission
  denied (publickey,password,keyboard-interactive)` — indistinguishable from a
  missing or wrong key, and the fingerprint matches on both ends. Check the
  port before touching credentials.
- potato's nightly self-repair timer commits locally, so it was never blocked
  by any of this and is not fixed by it either.
