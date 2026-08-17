#!/usr/bin/env bash
# bin/crt-senechal-guard.sh -- the PostToolUse(Bash) hook that catches
# machine-scoped changes owing senechal a note (CLAUDE.md's ecosystem
# protocols). Added 2026-07-28, Zach-directed: "set up a trigger to
# notify-senechal automatically, in case I forget."
#   [rest: vault:crt/header-archaeology-20260817.md]
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK="$DIR/../bin/crt-senechal-guard.sh"
fail=0

run() {
  printf '{"tool_name":"Bash","tool_input":{"command":%s}}' "$(jq -Rn --arg c "$1" '$c')" \
    | bash "$HOOK"
}

fires() {
  local desc="$1" cmd="$2"
  if run "$cmd" | grep -q 'notify-senechal owed'; then
    echo "ok - fires on $desc"
  else
    echo "FAIL - stayed silent on $desc: $cmd"
    fail=1
  fi
}

quiet() {
  local desc="$1" cmd="$2"
  local out
  out="$(run "$cmd")"
  if [ -z "$out" ]; then
    echo "ok - quiet on $desc"
  else
    echo "FAIL - nagged about $desc: $cmd"
    fail=1
  fi
}

fires "systemctl enable"            'sudo systemctl enable --now crt-self-repair.timer'
fires "systemctl disable (retiring)" 'sudo systemctl disable --now crt-whisper-server'
fires "a unit written into /etc"    'sudo install -m644 /tmp/x.service /etc/systemd/system/'
fires "crontab editing"             'crontab /tmp/newcron'
fires "an autostart entry"          'cp foo.desktop ~/.config/autostart/'
fires "a script into ~/.local/bin"  'install -m755 bin/tool ~/.local/bin/tool'
fires "~/.claude settings"          'jq . ~/.claude/settings.json > /tmp/s && mv /tmp/s ~/.claude/settings.json'
# The remote case is the one most likely to be forgotten -- the change lands
# on another box, so nothing local looks different afterwards.
fires "a remote unit install over ssh" \
  'ssh vkv@192.168.0.45 "sudo install -m644 /tmp/crt-self-repair.service /etc/systemd/system/"'

quiet "systemctl status"            'systemctl status crt-self-repair.timer --no-pager'
quiet "systemctl list-timers"       'systemctl list-timers --no-pager'
quiet "crontab -l"                  'crontab -l'
quiet "listing ~/.local/bin"        'ls ~/.local/bin'
quiet "an unrelated command"        'git status --porcelain'
# Filing the note IS the discharge of the debt; reminding afterwards would
# make the hook cry wolf on the one command that proves it worked.
quiet "a notify-senechal call itself" "notify-senechal 'installed a unit on potato'"

# The reminder has to name the surface, or it degrades into a generic nag
# that gets ignored -- the exact fate of the prose rule it backs up.
if run 'sudo systemctl enable foo' | grep -q 'systemctl enable/disable/mask'; then
  echo "ok - the reminder names which surface was touched"
else
  echo "FAIL - reminder does not say what it matched"
  fail=1
fi

# It must be valid hook JSON or Claude Code silently ignores it, which
# looks identical to a hook that never fired.
if run 'sudo systemctl enable foo' | jq -e '.hookSpecificOutput.additionalContext' >/dev/null 2>&1; then
  echo "ok - emits valid PostToolUse hook JSON with additionalContext"
else
  echo "FAIL - output is not valid hook JSON"
  fail=1
fi

exit "$fail"
