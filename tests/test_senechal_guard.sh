#!/usr/bin/env bash
# bin/crt-senechal-guard.sh -- the PostToolUse(Bash) hook that catches
# machine-scoped changes owing senechal a note (CLAUDE.md's ecosystem
# protocols). Added 2026-07-28, Zach-directed: "set up a trigger to
# notify-senechal automatically, in case I forget." crt-senechal-guard.sh's
# own header covers why this reminds rather than auto-files. The two
# failure modes worth testing are opposite: staying SILENT on a change
# that owes a note, and NAGGING on read-only inspection.
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
fires "a marker file written under ~/.local/share" \
  'touch ~/.local/share/some-app/installed.marker'

quiet "systemctl status"            'systemctl status crt-self-repair.timer --no-pager'
quiet "systemctl list-timers"       'systemctl list-timers --no-pager'
quiet "crontab -l"                  'crontab -l'
quiet "listing ~/.local/bin"        'ls ~/.local/bin'
quiet "an unrelated command"        'git status --porcelain'
quiet "reading a file inside a ~/.local/share checkout" \
  'sed -n "1,5p" ~/.local/share/crt-nightly-batch/repo/README.md'
quiet "a multi-stage read pipeline inside a ~/.local/share checkout" \
  'awk "/x/" ~/.local/share/crt-nightly-batch/repo/bin/crt-secretary.py | wc -l'
# A stderr-to-void redirect and a literal "->" arrow both contain the ">"
# WRITE_VERB checks for, but neither writes anything into .local/share --
# found live when a read-only `ls ... 2>/dev/null` under a checkout there
# false-positived.
quiet "a stderr-to-null redirect while reading under ~/.local/share" \
  'ls ~/.local/share/crt-nightly-batch/repo/tests/test_x.py 2>/dev/null'
quiet "a literal arrow in echoed text referencing ~/.local/share" \
  'echo "crt-stt-confidence.py -> $(ls ~/.local/share/crt-nightly-batch/repo/tests)"'
# An fd-duplicating redirect (2>&1, 1>&2) contains the ">" WRITE_VERB checks
# for but writes nothing into .local/share -- found live when a `cd` into a
# ~/.local/share checkout followed by a plain `cat foo 2>&1 | head` in the
# same command false-positived.
quiet "an fd-duplicating redirect while reading under ~/.local/share" \
  'cat ~/.local/share/crt-nightly-batch/repo/tests/test_x.py 2>&1 | head -5'
quiet "a cd into ~/.local/share followed by a 2>&1 read on another line" \
  'cd ~/.local/share/crt-nightly-batch/repo
cat README.md 2>&1 | head -5'
# A ">=" comparison inside embedded script code contains the ">"
# WRITE_VERB checks for but writes nothing into .local/share -- found live
# when an inline awk script comparing `count>=3` while reading files under
# a ~/.local/share checkout false-positived.
quiet "an inline awk >= comparison while reading under ~/.local/share" \
  'cd ~/.local/share/crt-nightly-batch/repo
awk "{ if (count>=3) print; count=0 }" README.md'
# A heredoc BODY is literal text landing wherever its redirect points, not
# a command -- if the body merely mentions ~/.local/share in prose while
# the heredoc's own redirect writes somewhere unrelated (e.g. this guard
# filing an issue/PR body about itself to /tmp), the path-mention and
# write-verb checks combine into a false positive on text that was never
# a write into .local/share. Found live: exactly this, drafting a PR body
# in /tmp that described this very false-positive class.
quiet "a heredoc body mentioning ~/.local/share in prose while writing elsewhere" \
  "cat > /tmp/pr-body.md << 'EOF'
this describes a fix touching ~/.local/share/crt-nightly-batch/repo
EOF"
# The redirect target itself (not the heredoc body) naming ~/.local/share
# is a real write and must still fire -- heredoc-body stripping must not
# blind the guard to the one case it exists to catch.
fires "a real write into ~/.local/share via a heredoc" \
  "cat > ~/.local/share/some-app/installed.marker << 'EOF'
hello
EOF"
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

# A guard that cannot see jq must say so loudly instead of silently
# reminding about nothing forever (found blind on dexter, no jq installed
# -- crt-senechal-guard.sh's own comment). Hide jq from PATH by pointing it
# at a minimal dir holding just the other tools the hook needs.
NOJQ_DIR="$(mktemp -d)"
BASH_BIN="$(command -v bash)"
for tool in cat grep hostname; do
  ln -s "$(command -v "$tool")" "$NOJQ_DIR/$tool"
done
payload='{"tool_name":"Bash","tool_input":{"command":"cp foo.desktop ~/.config/autostart/"}}'
nojq_stderr="$(printf '%s' "$payload" | PATH="$NOJQ_DIR" "$BASH_BIN" "$HOOK" 2>&1 1>/dev/null)"
nojq_stdout="$(printf '%s' "$payload" | PATH="$NOJQ_DIR" "$BASH_BIN" "$HOOK" 2>/dev/null)"
rm -rf "$NOJQ_DIR"

case "$nojq_stderr" in
  *"BLIND"*)
    echo "ok - missing jq is reported loudly instead of silently swallowed" ;;
  *)
    echo "FAIL - missing jq produced no warning: [$nojq_stderr]"
    fail=1 ;;
esac
if [ -z "$nojq_stdout" ]; then
  echo "ok - missing jq still exits quiet on stdout (no bogus hook JSON)"
else
  echo "FAIL - missing jq emitted stdout: [$nojq_stdout]"
  fail=1
fi

exit "$fail"
