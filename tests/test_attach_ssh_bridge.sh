#!/usr/bin/env bash
# Offline test for crt-attach-ssh-bridge.sh's project-dir resolution
# (2026-07-21, twelfth pass, REAL BUG FOUND LIVE): the first version
# derived the Claude Code project directory from `pwd` (the Bash tool's
# CURRENT working directory) -- fixed to search for the session's own transcript file by UUID instead.
set -uo pipefail
fail=0

check() {
  local desc="$1" expected="$2" got="$3"
  if [ "$got" = "$expected" ]; then
    echo "ok - $desc"
  else
    echo "FAIL - $desc: expected '$expected', got '$got'"
    fail=1
  fi
}

resolve_project_dir() {
  # Mirrors crt-attach-ssh-bridge.sh's exact resolution logic -- kept in
  # sync by hand; if that logic changes, update this too. Empty
  # FOUND_TRANSCRIPT must yield empty output, NOT dirname's own "."
  # fallback for an empty argument (the real bug this test file exists
  # to catch).
  local projects_root="$1" session_id="$2"
  local found
  found="$(find "$projects_root" -maxdepth 2 -iname "${session_id}.jsonl" 2>/dev/null | head -1)"
  [ -z "$found" ] && return
  dirname "$found"
}

TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

# Case 1: session transcript lives under a dir that does NOT match a
# naive cwd-derived guess -- the real live bug. Search must still find it.
mkdir -p "$TMPDIR/projects/-home-zach"
touch "$TMPDIR/projects/-home-zach/aaaa1111-0000-0000-0000-000000000000.jsonl"
got=$(resolve_project_dir "$TMPDIR/projects" "aaaa1111-0000-0000-0000-000000000000")
check "finds the real project dir regardless of a differently-named sibling dir" \
  "$TMPDIR/projects/-home-zach" "$got"

# Case 2: multiple project dirs exist (a realistic tree with several
# projects) -- search must find the ONE containing the right session,
# not get confused by unrelated sibling directories.
mkdir -p "$TMPDIR/projects/-home-zach-crt"
touch "$TMPDIR/projects/-home-zach-crt/bbbb2222-0000-0000-0000-000000000000.jsonl"
got=$(resolve_project_dir "$TMPDIR/projects" "aaaa1111-0000-0000-0000-000000000000")
check "still finds the right one among multiple project dirs" \
  "$TMPDIR/projects/-home-zach" "$got"

# Case 3: session ID with no matching file anywhere -- empty result,
# not a crash or a wrong match.
got=$(resolve_project_dir "$TMPDIR/projects" "cccc3333-0000-0000-0000-000000000000")
check "no match yields empty string, not a wrong guess" "" "$got"

next_window_index() {
  # Mirrors crt-attach-ssh-bridge.sh's own NEXT_INDEX line -- kept in
  # sync by hand. Explicit max()+1 instead of a bare `tmux new-window`,
  # since that can fail with "index 0 in use" on this tmux even when all
  # existing indices are legitimately occupied (2026-07-21, found live).
  local indices="$1"
  echo $(( $(printf '%s\n' "$indices" | sort -n | tail -1) + 1 ))
}

# Case 4: ordinary run of occupied indices -- next slot is one past the max.
got=$(next_window_index "0
1
2")
check "next index is one past the highest occupied" "3" "$got"

# Case 5: a single, non-zero window index (the realistic steady state --
# window 0 killed or renamed away) -- still max()+1, not a hardcoded guess.
got=$(next_window_index "4")
check "single occupied window still yields max+1" "5" "$got"

exit "$fail"
