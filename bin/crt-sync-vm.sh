#!/usr/bin/env bash
# Two-way file sync between this repo and the live VM's ~/crt, over SSH.
# Written 2026-07-20 after finding the VM's ~/crt (a plain deploy target,
# no git) had drifted ~a day behind this repo, plus four files (stt-fixups.json,
# crt-bell-test.sh, crt-idle-bait.sh, crt-screensaver.py) that only ever
# existed on the VM -- real work at risk of being silently clobbered by the
# next deploy. Policy (Zach, 2026-07-20): safe to overwrite the VM, NEVER
# dexter; but always pull VM-only work back first.
#
# Neither box has rsync -- this uses sha256sum diffing + tar-over-ssh.
#
# Usage:
#   bin/crt-sync-vm.sh pull   # show/copy files that exist only on the VM
#                              # (or differ from the repo) back into the repo,
#                              # for you to review and `git add` yourself --
#                              # never auto-commits.
#   bin/crt-sync-vm.sh push   # tar the repo's tracked files
#                              # onto the VM, overwriting same-named files.
#                              # Run `pull` first so nothing VM-only is lost.
#   bin/crt-sync-vm.sh status # just report the diff, no copying either way.
set -euo pipefail

VM="zach@dexter.local"
VM_PORT=2222
VM_DIR="~/crt"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SSH="ssh -p $VM_PORT $VM"

cmd="${1:-status}"

diff_report() {
  local vm_hashes local_hashes
  vm_hashes=$(mktemp)
  local_hashes=$(mktemp)
  trap 'rm -f "$vm_hashes" "$local_hashes"' RETURN

  $SSH "cd $VM_DIR && find . -type f -not -path './.git/*' -not -path '*/__pycache__/*' -exec sha256sum {} \;" \
    | awk '{h=$1; $1=""; sub(/^ /,""); p=$0; sub(/^\.\//,"",p); print p, h}' \
    | LC_ALL=C sort > "$vm_hashes"

  (cd "$REPO_DIR" && git ls-files -z) \
    | xargs -0 sha256sum \
    | awk '{print $2, $1}' \
    | LC_ALL=C sort > "$local_hashes"

  python3 - "$vm_hashes" "$local_hashes" <<'PYEOF'
import sys
vm = dict(l.split() for l in open(sys.argv[1]))
loc = dict(l.split() for l in open(sys.argv[2]))
only_vm = sorted(set(vm) - set(loc))
only_local = sorted(set(loc) - set(vm))
differ = sorted(p for p in (set(vm) & set(loc)) if vm[p] != loc[p])
print("ONLY_VM", len(only_vm))
for p in only_vm: print(" ", p)
print("ONLY_LOCAL", len(only_local))
for p in only_local: print(" ", p)
print("DIFFER", len(differ))
for p in differ: print(" ", p)
PYEOF
}

case "$cmd" in
  status)
    diff_report
    ;;
  pull)
    report=$(diff_report)
    echo "$report"
    only_vm=$(echo "$report" | awk '/^ONLY_VM/{n=$2; for(i=0;i<n;i++){getline; print $1}}')
    if [ -z "$only_vm" ]; then
      echo "Nothing VM-only to pull."
      exit 0
    fi
    echo "$only_vm" | while read -r f; do
      [ -z "$f" ] && continue
      mkdir -p "$REPO_DIR/$(dirname "$f")"
      $SSH "cat $VM_DIR/$f" > "$REPO_DIR/$f"
      echo "pulled: $f (review + git add yourself)"
    done
    ;;
  push)
    (cd "$REPO_DIR" && git ls-files) > /tmp/crt-sync-push-filelist.txt
    tar cf - -C "$REPO_DIR" -T /tmp/crt-sync-push-filelist.txt \
      | $SSH "mkdir -p $VM_DIR && tar xf - -C $VM_DIR"
    echo "pushed $(wc -l < /tmp/crt-sync-push-filelist.txt) files to VM:$VM_DIR"
    rm -f /tmp/crt-sync-push-filelist.txt
    ;;
  *)
    echo "usage: $0 {status|pull|push}" >&2
    exit 1
    ;;
esac
