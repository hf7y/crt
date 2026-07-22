#!/bin/bash
set -euo pipefail

grub-mkstandalone \
  -O i386-efi \
  --compress=xz \
  -o /home/zach/Documents/Projects/crt/cad/BOOTIA32.EFI \
  --modules="part_gpt part_msdos fat iso9660 linux normal search" \
  "boot/grub/grub.cfg=/dev/stdin" <<'GRUBCFG'
insmod part_gpt
insmod part_msdos
insmod fat
insmod iso9660
insmod linux
search --no-floppy --set=root --file /install.amd/vmlinuz
linux /install.amd/vmlinuz ---
initrd /install.amd/initrd.gz
boot
GRUBCFG

mkdir -p /mnt/stick
umount /mnt/stick 2>/dev/null || true
mount /dev/sda2 /mnt/stick
rm -f /mnt/stick/EFI/BOOT/GRUBX64.EFI /mnt/stick/EFI/BOOT/grubx64.efi
cp /home/zach/Documents/Projects/crt/cad/BOOTIA32.EFI /mnt/stick/EFI/BOOT/BOOTIA32.EFI
df -h /mnt/stick
ls -la /mnt/stick/EFI/BOOT/
umount /mnt/stick
echo "DONE"
