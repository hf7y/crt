#!/bin/bash
set -euo pipefail

SCRATCH=/tmp/claude-1000/-home-zach-Documents-Projects-crt/c19afceb-e43f-45f7-899e-3bfedd96cfb7/scratchpad
PART=/dev/sda3

mkdir -p /mnt/installdata
umount /mnt/installdata 2>/dev/null || true
mount "$PART" /mnt/installdata

cp "$SCRATCH/initrd-minimal.gz" /mnt/installdata/initrd-minimal.gz

sync
ls -la /mnt/installdata/
umount /mnt/installdata
echo "DONE"
