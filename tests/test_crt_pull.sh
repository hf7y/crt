#!/usr/bin/env bash
# crt-pull.sh: ff-only pull + window restart, never over a dirty or
# diverged tree (hf7y/crt#325).
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$DIR/../bin/crt-pull.sh"
pass=0; fail=0
ok()  { pass=$((pass+1)); printf '  ok - %s\n' "$1"; }
bad() { fail=$((fail+1)); printf '  FAIL - %s\n' "$1"; [ $# -gt 1 ] && printf '        %s\n' "$2"; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

ORIGIN="$TMP/origin.git"
CLONE="$TMP/clone"
FAKEBIN="$TMP/fakebin"
mkdir -p "$FAKEBIN"

git init -q --bare "$ORIGIN"

git init -q "$TMP/seed"
(
  cd "$TMP/seed"
  git config user.email t@example.com; git config user.name t
  mkdir -p bin
  echo "v1" > bin/crt-stt-solo.py
  echo "v1" > README.md
  git add -A && git commit -q -m seed
  git branch -M main
  git remote add origin "$ORIGIN"
  git push -q origin main
)

git clone -q -b main "$ORIGIN" "$CLONE"
(
  cd "$CLONE"
  git config user.email t@example.com; git config user.name t
  git branch -M main 2>/dev/null || true
)

run_pull() {
  ( HOME="$TMP/home" PATH="$FAKEBIN:$PATH" CRT_PULL_PROJECT_DIR="$CLONE" bash "$SCRIPT" )
}

printf 'crt-pull -- ff-only pull, never over a dirty or diverged tree\n\n'

# --- 1. clean tree, nothing new upstream: no-op --------------------------
mkdir -p "$TMP/home"
out="$(run_pull)"
if printf '%s' "$out" | grep -q 'already at origin/main'; then
  ok "up to date is a no-op"
else
  bad "up to date is a no-op" "$out"
fi

# --- 2. dirty tree: skip, no merge ----------------------------------------
echo "scratch" > "$CLONE/scratch.txt"
out="$(run_pull)"
if printf '%s' "$out" | grep -q 'dirty' && [ -f "$CLONE/scratch.txt" ]; then
  ok "dirty tree is skipped, not touched"
else
  bad "dirty tree is skipped, not touched" "$out"
fi
rm -f "$CLONE/scratch.txt"

# --- 3. clean fast-forward available: pulls, no tmux configured ----------
(
  cd "$TMP/seed"
  echo "v2" > bin/crt-stt-solo.py
  git add -A && git commit -q -m "update stt"
  git push -q origin main
)
before="$(cd "$CLONE" && git rev-parse HEAD)"
out="$(run_pull)"
after="$(cd "$CLONE" && git rev-parse HEAD)"
if [ "$before" != "$after" ] && printf '%s' "$out" | grep -q 'pulled'; then
  ok "a clean fast-forward pulls"
else
  bad "a clean fast-forward pulls" "$out"
fi
if [ "$(cat "$CLONE/bin/crt-stt-solo.py")" = "v2" ]; then
  ok "the pulled content lands on disk"
else
  bad "the pulled content lands on disk"
fi
if printf '%s' "$out" | grep -q "would restart window 'stt'"; then
  ok "a stt-relevant change is named, even with no live tmux session"
else
  bad "a stt-relevant change is named, even with no live tmux session" "$out"
fi

# --- 4. an unrelated file change: no restart mentioned --------------------
(
  cd "$TMP/seed"
  echo "v2" > README.md
  git add -A && git commit -q -m "docs only"
  git push -q origin main
)
out="$(run_pull)"
if ! printf '%s' "$out" | grep -q "restart window"; then
  ok "a docs-only change restarts nothing"
else
  bad "a docs-only change restarts nothing" "$out"
fi

# --- 5. diverged: local HEAD has a commit origin doesn't have -------------
(
  cd "$CLONE"
  git config user.email t@example.com; git config user.name t
  echo "local-only" >> bin/crt-stt-solo.py
  git add -A && git commit -q -m "local-only, self-repair-style"
)
(
  cd "$TMP/seed"
  echo "v3" > README.md
  git add -A && git commit -q -m "another upstream change"
  git push -q origin main
)
before="$(cd "$CLONE" && git rev-parse HEAD)"
out="$(run_pull)"
after="$(cd "$CLONE" && git rev-parse HEAD)"
if [ "$before" = "$after" ] && printf '%s' "$out" | grep -qi 'not a fast-forward'; then
  ok "a diverged local HEAD is left alone, not force-merged"
else
  bad "a diverged local HEAD is left alone, not force-merged" "$out"
fi

# --- 6. tmux present: respawn-window actually gets called -----------------
(
  cd "$CLONE"
  git reset -q --hard HEAD~1
)
RESPAWN_LOG="$TMP/respawn.log"
cat > "$FAKEBIN/tmux" <<EOF
#!/usr/bin/env bash
case "\$1" in
  has-session) exit 0 ;;
  list-windows) echo stt ;;
  respawn-window) echo "\$*" >> "$RESPAWN_LOG" ;;
esac
EOF
chmod +x "$FAKEBIN/tmux"
(
  cd "$TMP/seed"
  echo "v3" > bin/crt-stt-solo.py
  git add -A && git commit -q -m "another stt update"
  git push -q origin main
)
run_pull >/dev/null
if grep -q 'respawn-window' "$RESPAWN_LOG" 2>/dev/null; then
  ok "a live tmux session gets its window respawned"
else
  bad "a live tmux session gets its window respawned"
fi

printf '\n'
if [ "$fail" -eq 0 ]; then
  echo "ALL GREEN ($pass ok)"
else
  echo "SOMETHING FAILED ($fail failed, $pass ok)"
fi
exit "$fail"
