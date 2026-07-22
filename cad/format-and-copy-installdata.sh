#!/bin/bash
set -euo pipefail

SCRATCH=/tmp/claude-1000/-home-zach-Documents-Projects-crt/c19afceb-e43f-45f7-899e-3bfedd96cfb7/scratchpad
PART=/dev/sda3

mkfs.vfat -F 32 -n INSTALLDATA "$PART"

mkdir -p /mnt/installdata
umount /mnt/installdata 2>/dev/null || true
mount "$PART" /mnt/installdata

cp "$SCRATCH/installdata/install.amd/vmlinuz" /mnt/installdata/vmlinuz
cp "$SCRATCH/initrd-diag.gz" /mnt/installdata/initrd-diag.gz

sync
ls -la /mnt/installdata/
umount /mnt/installdata
echo "DONE"
