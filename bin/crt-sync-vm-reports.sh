#!/usr/bin/env bash
# Pulls crt-vm's own ~/reports/crt/ (written by the VM-resident hardware
# check, VM-JOBS.md) back to mandark, where morning-report.sh actually
# looks. Run FROM mandark -- the VM has no push credential back to
# mandark (HANDOFF.md: deploys are one-directional, mandark -> VM), so
# this is a pull, not something the VM triggers itself.
#
# Deliberately syncs into a SEPARATE namespace (~/reports/crt/vm/) rather
# than overwriting ~/reports/crt/LATEST.md directly -- that file is also
# written by this session's own bin/crt-report.sh from interactive work,
# and a blind overwrite would silently clobber one or the other's entries.
# See VM-JOBS.md's open item: morning-report.sh (shared scheduler infra,
# not this repo) doesn't know to look at a project's vm/ subdirectory yet
# -- until that's taught to it (or this script learns to merge instead of
# just copy), the VM's reports are pulled here but not yet surfaced by the
# morning aggregate automatically.
#
# STATUS: NOT run against a real VM this session (no VM access). ssh
# target/port match HANDOFF.md's documented crt-vm access; untested.
#
# Usage: crt-sync-vm-reports.sh
set -euo pipefail

VM_HOST="${CRT_VM_HOST:-dexter.local}"
VM_PORT="${CRT_VM_PORT:-2222}"
VM_USER="${CRT_VM_USER:-zach}"
LOCAL_DEST="${CRT_REPORTS_DIR:-$HOME/reports/crt}/vm/"

mkdir -p "$LOCAL_DEST"

echo "[sync-vm-reports] pulling from ${VM_USER}@${VM_HOST}:~/reports/crt/ (port $VM_PORT)"
rsync -az -e "ssh -p $VM_PORT" \
  "${VM_USER}@${VM_HOST}:reports/crt/" \
  "$LOCAL_DEST"

echo "[sync-vm-reports] done -> $LOCAL_DEST"
