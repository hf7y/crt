#!/usr/bin/env bash
# Offline test for bin/crt-pull.sh (crt#325): fast-forward-only pull, plus
# restarting only the tmux window whose backing file actually changed.
# Real git repos as fixtures (test_self_repair.sh's pattern), a fake tmux
# logging its own invocations (test_zaxon_autoupdate_rollback.sh's pattern).
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
pass=0; fail=0
ok()  { pass=$((pass+1)); printf '  ok - %s\n' "$1"; }
bad() { fail=$((fail+1)); printf '  FAIL - %s\n' "$1"; [ $# -gt 1 ] && printf '        %s\n' "$2"; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

ORIGIN="$TMP/origin.git"
git init -q --bare "$ORIGIN"

seed_origin() {
  local seed="$TMP/seed"
  rm -rf "$seed"; mkdir -p "$seed/bin"
  git -C "$seed" init -q
  git -C "$seed" config user.email test@example.com
  git -C "$seed" config user.name test
  mkdir -p "$seed/bin"
  # crt-pull.sh itself ships IN the seeded history (like every other bin/
  # script would on a real clone) -- copying it in afterward, uncommitted,
  # would leave the clone permanently "dirty" and never actually pull.
  cp "$DIR/../bin/crt-pull.sh" "$seed/bin/crt-pull.sh"
  printf '#!/usr/bin/env bash\necho stub\n' > "$seed/bin/crt-stt-supervisor.sh"
  printf 'seed\n' > "$seed/README.md"
  git -C "$seed" add -A
  git -C "$seed" commit -q -m seed
  git -C "$seed" branch -M main
  git -C "$seed" remote add origin "$ORIGIN"
  git -C "$seed" push -q origin main
}
seed_origin

CLONE="$TMP/clone"
git clone -q "$ORIGIN" "$CLONE"
git -C "$CLONE" checkout -q main

FAKEBIN="$TMP/fakebin"
mkdir -p "$FAKEBIN"
TMUX_LOG="$TMP/tmux.log"
cat > "$FAKEBIN/tmux" <<EOF
#!/usr/bin/env bash
echo "\$@" >> "$TMUX_LOG"
case "\$1" in
  has-session) exit 0 ;;
  list-windows) printf '0\nmono\nbridge\nstt\n' ;;
  respawn-window) exit 0 ;;
esac
EOF
chmod +x "$FAKEBIN/tmux"

HOMEDIR="$TMP/home"
PULL_LOG="$TMP/pull.log"

run_pull() {
  rm -f "$TMUX_LOG" "$PULL_LOG"
  ( cd "$CLONE" && HOME="$HOMEDIR" CRT_PULL_TMUX="$FAKEBIN/tmux" CRT_PULL_LOG="$PULL_LOG" \
      bash bin/crt-pull.sh )
}

# --- nothing new upstream: no-op -------------------------------------------
run_pull
if grep -q "up to date" "$PULL_LOG"; then
  ok "nothing new upstream is a no-op, logged as such"
else
  bad "expected an 'up to date' log line" "$(cat "$PULL_LOG")"
fi
[ -s "$TMUX_LOG" ] && bad "tmux touched on a no-op pull" "$(cat "$TMUX_LOG")" \
  || ok "no tmux window touched on a no-op pull"

# --- dirty tree: skip, never pulls ------------------------------------------
echo dirty > "$CLONE/scratch.txt"
before_head="$(git -C "$CLONE" rev-parse HEAD)"
run_pull
after_head="$(git -C "$CLONE" rev-parse HEAD)"
if [ "$before_head" = "$after_head" ] && grep -q "dirty" "$PULL_LOG"; then
  ok "a dirty tree is skipped, not overwritten"
else
  bad "dirty tree was not skipped as expected" "$(cat "$PULL_LOG")"
fi
rm -f "$CLONE/scratch.txt"

# --- clean pull, unrelated file: fast-forwards, no window restarted --------
printf 'unrelated change\n' >> "$TMP/seed/README.md"
git -C "$TMP/seed" commit -qam "unrelated change"
git -C "$TMP/seed" push -q origin main
before_head="$(git -C "$CLONE" rev-parse HEAD)"
run_pull
after_head="$(git -C "$CLONE" rev-parse HEAD)"
if [ "$after_head" != "$before_head" ] && [ "$(cat "$CLONE/README.md" | tail -1)" = "unrelated change" ]; then
  ok "fast-forwards past an unrelated upstream commit"
else
  bad "did not fast-forward on an unrelated change" "$(cat "$PULL_LOG")"
fi
if grep -q "respawn-window" "$TMUX_LOG" 2>/dev/null; then
  bad "restarted a window for a change that touched no watched file" "$(cat "$TMUX_LOG")"
else
  ok "no window restarted for an unrelated file change"
fi

# --- clean pull, stt-supervisor changed: restarts ONLY the stt window ------
printf 'echo stub2\n' >> "$TMP/seed/bin/crt-stt-supervisor.sh"
git -C "$TMP/seed" commit -qam "touch stt supervisor"
git -C "$TMP/seed" push -q origin main
run_pull
if grep -q "respawn-window -k -t claude:stt" "$TMUX_LOG"; then
  ok "restarts the stt window when crt-stt-supervisor.sh changes"
else
  bad "did not restart the stt window" "$(cat "$TMUX_LOG")"
fi
if grep -qE "respawn-window -k -t claude:(mono|bridge)" "$TMUX_LOG"; then
  bad "restarted an unrelated window too" "$(cat "$TMUX_LOG")"
else
  ok "left mono/bridge alone for an stt-only change"
fi

# --- diverged history: local has a commit origin doesn't share -------------
git -C "$CLONE" commit -q --allow-empty -m "local-only work"
printf 'origin moves on again\n' >> "$TMP/seed/README.md"
git -C "$TMP/seed" commit -qam "origin moves on again"
git -C "$TMP/seed" push -q origin main
before_head="$(git -C "$CLONE" rev-parse HEAD)"
run_pull
after_head="$(git -C "$CLONE" rev-parse HEAD)"
if [ "$before_head" = "$after_head" ] && grep -qi "not a fast-forward" "$PULL_LOG"; then
  ok "a diverged history is left alone, not force-merged"
else
  bad "diverged history was not handled safely" "$(cat "$PULL_LOG")"
fi

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" = 0 ]
