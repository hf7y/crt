# zaxon — crt's WhatsApp channel

**crt owns zaxon as of 2026-08-14 (Zach's call.)** An MCP server over
streamable-http exposing `ask_zach`, `revise_zach_question` and
`check_zach_reply`; loopback and tailnet only (#52). See `compose.yaml` for the
rest.

**One question per ticket (Zach 2026-08-20, crt#190).** He reads tickets on a
WhatsApp phone screen -- a bundle of several questions in one message runs
past what he can see and he ends up re-answering the same batch repeatedly.
Never bundle multiple decisions into one `ask_zach` call; open a separate
ticket per question instead. Enforced at the send, not just documented here:
`validate_message`/`validate_single_question` in `relay/zaxon_relay_queue.py`
refuse a question carrying more than one `?`, more than one enumerated item
("1. ... 2. ..."), or more than `MAX_QUESTION_LINES` lines -- refused, not
truncated or silently split. Use `options=` for a multiple-choice poll on
ONE question; that is not bundling. If a ticket goes stale unanswered, do
NOT just re-send it -- reconsider whether it still needs asking.

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

## Open

- `hermes` is still registered, so it can still seize the session; the page
  reports it every hour. Before `wsl --unregister hermes`: its verified `.vhdx`
  export and extracted `ggml-base.en.bin` are at
  `/mnt/d/gardien-backups/hermes-wsl-export/` on dexter.
- Still **no auth** on the MCP port, only a bind — today, the tailnet.
