#!/usr/bin/env bash
# Offline test for crt-attach-ssh-bridge.sh's project-dir resolution
# (2026-07-21, twelfth pass, REAL BUG FOUND LIVE): the first version
# derived the Claude Code project directory from `pwd` (the Bash tool's
# CURRENT working directory), which is wrong whenever the conversation
#   [rest: vault:crt/header-archaeology-20260817.md]
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

exit "$fail"
