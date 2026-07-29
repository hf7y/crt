#!/usr/bin/env bash
# PostToolUse(Bash) hook: catch machine-scoped changes that owe senechal a
# note, and say so loudly in-session.
#
# WHY A REMINDER AND NOT AN AUTO-FILE (decided 2026-07-28 with Zach). The
# obvious version of this hook pipes the command straight into
# notify-senechal. That would file a note nobody wrote: senechal's whole
# value is a human-legible record of WHAT changed, WHERE, and WHO OWNS IT
# -- a machine-generated "someone ran systemctl enable foo" is noise
# wearing a note's clothes, and worse, it would mark the debt PAID while
# leaving the actual knowledge unrecorded. So this hook makes forgetting
# loud, and a human/agent still writes the sentence. The failure mode we
# want is "reminded twice", not "filed wrong once".
#
# Fires on the ecosystem-protocol surface named in CLAUDE.md: systemd
# units, systemctl enable/disable, crontab, autostart, ~/.local/bin,
# ~/.claude settings hooks, and marker files under ~/.local/share.
#
# Deliberately NOT firing on: read-only inspection (systemctl status/
# is-active/list-*, crontab -l). Probing the machine is how you find out
# what's there; only changing it owes a note.
set -uo pipefail

payload="$(cat)"

# A guard that cannot parse its input must SAY SO, not wave the command
# through (2026-07-28). Before this, a missing jq made `cmd` empty and the
# next line exited 0 -- so on any host without jq this hook silently
# reminded about nothing, forever, while looking installed and healthy.
# That is precisely the failure it exists to prevent, turned on itself.
# Found on dexter, which has no jq: an entire session's worth of ~/.ssh
# and authorized_keys edits drew no reminder.
if ! command -v jq >/dev/null 2>&1; then
  printf '%s\n' \
    "[crt-senechal-guard] jq is NOT INSTALLED on $(hostname) -- this hook is BLIND." \
    "[crt-senechal-guard] Machine-scoped changes will draw no reminder here until:" \
    "[crt-senechal-guard]   sudo apt install jq" >&2
  exit 0
fi

cmd="$(printf '%s' "$payload" | jq -r '.tool_input.command // empty' 2>/dev/null)"
[ -z "$cmd" ] && exit 0

# Read-only forms first -- if the command is ONLY inspection, say nothing.
# `ls ~/.local/bin` is someone finding out what is installed, which is the
# behavior this project keeps asking for ("re-probe, don't quote"); nagging
# about it would train the reflex out.
if printf '%s' "$cmd" | grep -qE '^[[:space:]]*(ls|cat|head|tail|less|grep|rg|which|stat|file|find|wc|diff|md5sum)[[:space:]]' \
   && ! printf '%s' "$cmd" | grep -qE '(>|>>|\||;|&&|install|cp |mv |rm |chmod|tee)'; then
  exit 0
fi

if printf '%s' "$cmd" | grep -qE '(systemctl[^|;&]*(status|is-active|is-enabled|list-timers|list-units|cat|show)|crontab[[:space:]]+-l)' \
   && ! printf '%s' "$cmd" | grep -qE '(systemctl[^|;&]*(enable|disable|mask|unmask)|crontab[[:space:]]+[^-]|/etc/systemd/system|autostart|\.local/(bin|share)|\.claude/settings)'; then
  exit 0
fi

MATCH=''
add() { MATCH="${MATCH:+$MATCH; }$1"; }

printf '%s' "$cmd" | grep -qE 'systemctl[^|;&]*(enable|disable|mask|unmask)' && add 'systemctl enable/disable/mask'
printf '%s' "$cmd" | grep -qE '/etc/systemd/system' && add 'a unit file in /etc/systemd/system'
printf '%s' "$cmd" | grep -qE 'crontab[[:space:]]+(-e|-r|[^-])' && add 'crontab'
printf '%s' "$cmd" | grep -qE '(\.config/)?autostart' && add 'autostart entry'
printf '%s' "$cmd" | grep -qE '\.local/bin' && add 'a script in ~/.local/bin'
printf '%s' "$cmd" | grep -qE '\.local/share' && add 'a marker file under ~/.local/share'
printf '%s' "$cmd" | grep -qE '\.claude/settings' && add '~/.claude settings/hooks'

[ -z "$MATCH" ] && exit 0

# Already filed in the same command? Then the debt is settled, stay quiet.
printf '%s' "$cmd" | grep -q 'notify-senechal' && exit 0

REMINDER="This command touched machine-scoped config ($MATCH). Per CLAUDE.md's ecosystem protocols, senechal owns KNOWING it exists: run notify-senechal '<what changed, where, who owns it>' now, without waiting to be asked. If the change was on a remote host (e.g. potato), say so in the note -- senechal tracks the whole ecosystem, not just this box. If it RETIRED something, say that too; a stale entry pointing at a dead unit is the failure this protocol exists to prevent. If the change did not actually land (dry run, denied, failed), no note is owed -- say why instead of filing one."

jq -n --arg r "$REMINDER" --arg m "$MATCH" \
  '{systemMessage: ("senechal: machine config touched (" + $m + ") -- notify-senechal owed"),
    hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: $r}}'
