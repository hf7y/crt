#!/usr/bin/env bash
# Text -> image -> Phomemo M02 thermal printer, via the already-installed
# `catprint` tool (python-catprinter, ~/.local/bin/catprint on this machine
# -- SECRETARY.md calls it `bin/catprint` but it's actually a system tool,
# not part of this repo; adjust CRT_CATPRINT_BIN if it lives elsewhere on
#   [rest: vault:crt/header-archaeology-20260817.md]
set -euo pipefail
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CATPRINT="${CRT_CATPRINT_BIN:-$HOME/.local/bin/catprint}"
DEVICE="${CRT_PRINTER_DEVICE:-}"

text="${*:-}"
[ -z "$text" ] && text="$(cat)"
[ -z "$text" ] && { echo "usage: crt-print.sh <text>" >&2; exit 2; }

command -v "$CATPRINT" >/dev/null 2>&1 || { echo "[crt-print] catprint not found at $CATPRINT" >&2; exit 1; }

png="$(mktemp --suffix=.png)"
trap 'rm -f "$png"' EXIT

python3 "$BIN_DIR/crt-print-render.py" "$png" <<< "$text"

if [ -n "$DEVICE" ]; then
  "$CATPRINT" -d "$DEVICE" "$png"
else
  "$CATPRINT" "$png"
fi
