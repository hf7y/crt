#!/usr/bin/env bash
# PostToolUse(Bash) hook: catch machine-scoped changes that owe senechal a
# note, and say so loudly in-session.
#
# WHY A REMINDER AND NOT AN AUTO-FILE (decided 2026-07-28 with Zach). The
# obvious version pipes the command straight into notify-senechal -- but
# that files a note nobody wrote, marking the debt PAID while the actual
# knowledge stays unrecorded. This hook makes forgetting loud instead; a
# human/agent still writes the sentence. Prefer "reminded twice" over
# "filed wrong once".
set -uo pipefail

payload="$(cat)"

# A guard that cannot parse its input must SAY SO, not wave the command
# through (found blind on dexter, no jq installed) -- witnessed by
# tests/test_senechal_guard.sh's missing-jq case.
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

# A heredoc BODY (`<<'EOF' ... EOF`) is literal text landing wherever the
# redirect before `<<` points -- not a command the shell reads. If that
# body merely *mentions* ~/.local/share or ~/.local/bin in prose (e.g. this
# guard writing an issue/PR body about itself to /tmp), every check below
# scans the whole command string with no notion of WHERE a `>` actually
# writes, so a heredoc body discussing the path and an unrelated `>`
# elsewhere in the same command (even the heredoc's own redirect into
# /tmp) combine into a false positive. Found live: a `cat > /tmp/x.md
# <<'EOF' ... mentions ~/.local/share in prose ... EOF` false-positived as
# "a marker file under ~/.local/share" though nothing under .local/share
# was touched. Strip heredoc bodies (keeping the redirect line itself, so
# a real `cat > ~/.local/share/x/y <<'EOF'` still matches) before scanning.
cmd_scan="$(printf '%s' "$cmd" | awk '
  in_here { body = $0; if (indent) sub(/^[ \t]+/, "", body)
            if (body == delim) in_here = 0
            next }
  match($0, /<<-?[ \t]*["'"'"']?[A-Za-z_][A-Za-z0-9_]*["'"'"']?/) {
    tok = substr($0, RSTART, RLENGTH)
    indent = (tok ~ /^<<-/)
    delim = tok; sub(/^<<-?[ \t]*/, "", delim); gsub(/["'"'"']/, "", delim)
    in_here = 1
  }
  { print }
')"

printf '%s' "$cmd_scan" | grep -qE 'systemctl[^|;&]*(enable|disable|mask|unmask)' && add 'systemctl enable/disable/mask'
printf '%s' "$cmd_scan" | grep -qE '/etc/systemd/system' && add 'a unit file in /etc/systemd/system'
printf '%s' "$cmd_scan" | grep -qE 'crontab[[:space:]]+(-e|-r|[^-])' && add 'crontab'
printf '%s' "$cmd_scan" | grep -qE '(\.config/)?autostart' && add 'autostart entry'
# A literal "->" arrow (echoed text), a stderr-to-void redirect
# (`2>/dev/null`, `&>/dev/null`), an fd-duplicating redirect (`2>&1`,
# `1>&2`), or a ">=" comparison inside embedded script code (e.g. an awk
# `count>=3`) writes nothing anywhere -- strip all four before checking for
# a write verb, or a read-only command that merely references ~/.local/bin
# or ~/.local/share false-positives on the bare ">" in any of them. Found
# live: a `cd ~/.local/share/crt-nightly-batch/repo` followed by a plain
# `cat foo 2>&1 | head` in the same command false-positived on the `>` in
# `2>&1`; separately, an inline awk script comparing `count>=3` while
# reading under a ~/.local/share checkout false-positived on the `>` in
# `>=`.
cmd_for_write_check="$(printf '%s' "$cmd_scan" | sed -E 's/->//g; s/[0-9&]*>>?[[:space:]]*\/dev\/null//g; s/[0-9]*>&[0-9]+//g; s/>=//g')"
# The write must TARGET ~/.local/bin or ~/.local/share, not merely
# co-occur with one somewhere else in the command -- checking "does a
# write verb appear anywhere" and "does .local/share appear anywhere"
# independently false-positives on a `cd` through a ~/.local/share
# checkout followed by a real write to somewhere unrelated. Found live:
# `cd ~/.local/share/crt-nightly-batch/repo && (pytest ... > /tmp/out.log
# ...) &` -- the redirect's target was /tmp, not .local/share, but both
# substrings appeared in the command so it fired anyway. Anchor a write-verb
# command to its own argument list (flags allowed, but not past a `;`/`&`/
# `|` boundary), and a `>`/`>>` redirect to its own immediate target.
WRITE_VERB_CMD='(sudo[[:space:]]+)?(install|cp|mv|ln|touch|mkdir|chmod|tee)[[:space:]]'
targets_path() { # <path fragment, e.g. local/bin> -> 0 if a write targets it
  printf '%s' "$cmd_for_write_check" | grep -qE "${WRITE_VERB_CMD}[^;&|]*\\.$1" && return 0
  printf '%s' "$cmd_for_write_check" | grep -qE "[0-9]*>>?[[:space:]]*[\"']?[^[:space:];&|]*\\.$1" && return 0
  return 1
}
targets_path 'local/bin' && add 'a script in ~/.local/bin'
targets_path 'local/share' && add 'a marker file under ~/.local/share'
printf '%s' "$cmd_scan" | grep -qE '\.claude/settings' && add '~/.claude settings/hooks'

[ -z "$MATCH" ] && exit 0

# Already filed in the same command? Then the debt is settled, stay quiet.
printf '%s' "$cmd" | grep -q 'notify-senechal' && exit 0

REMINDER="This command touched machine-scoped config ($MATCH). Per CLAUDE.md's ecosystem protocols, senechal owns KNOWING it exists: run notify-senechal '<what changed, where, who owns it>' now, without waiting to be asked. If the change was on a remote host (e.g. potato), say so in the note -- senechal tracks the whole ecosystem, not just this box. If it RETIRED something, say that too; a stale entry pointing at a dead unit is the failure this protocol exists to prevent. If the change did not actually land (dry run, denied, failed), no note is owed -- say why instead of filing one."

jq -n --arg r "$REMINDER" --arg m "$MATCH" \
  '{systemMessage: ("senechal: machine config touched (" + $m + ") -- notify-senechal owed"),
    hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: $r}}'
