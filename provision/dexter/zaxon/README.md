# zaxon — crt's WhatsApp channel

**crt owns zaxon as of 2026-08-14 (Zach's call.)** An MCP server over
streamable-http exposing `ask_zach`, `revise_zach_question` and
`check_zach_reply`; loopback and tailnet only (#52). See `compose.yaml` for the
rest.

Deploys are automatic — `zaxon-autoupdate.timer` pulls hourly and verifies the
relay answers. By hand: `sudo docker compose pull && sudo docker compose up -d`
(`sudo` because `zach` is not in the `docker` group).

`data/` is service state, never overwritten from a repo; the relay's SOURCE ships in the image.

## The status page

`hf7y.com/zaxon` — `zaxon-watch.sh --apply` hourly, `--install` writes the timer,
`--check` publishes nothing. What used to be written down here as rules a reader
had to remember is enforced by `tests/test_zaxon_watch_guards.sh` and reported
by the page itself: the one-holder rule for `data/whatsapp/session`, the
never-bind-`0.0.0.0` rule, where the STT command lives, and why a relay that
merely answers is never `OK`.

## Filing a tagged inbox note (crt#154)

The `watcher` service opens a pointer issue (never the transcript) in a
note's target repo once it's tagged — `zaxon_relay_filer.py`. It runs `gh`,
which reads `GH_TOKEN` from `./.env` next to this `compose.yaml` (docker
compose's own env file, not the hermes-owned `data/.env`). Without
`ZAXON_GH_TOKEN` set there, `docker compose up` refuses the `watcher`
service outright rather than starting a watcher that can retag but never
file. Use a fine-grained PAT, `issues:write` only, scoped to the repos this
relay is ever tagged for — not an org-wide token.

## Open

- `hermes` is still registered, so it can still seize the session; the page
  reports it every hour. Before `wsl --unregister hermes`: its verified `.vhdx`
  export and extracted `ggml-base.en.bin` are at
  `/mnt/d/gardien-backups/hermes-wsl-export/` on dexter.
- Still **no auth** on the MCP port, only a bind — today, the tailnet.
