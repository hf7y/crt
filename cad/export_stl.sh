#!/usr/bin/env bash
# Renders all four hookswitch-assembly parts to STL.
# Requires: sudo apt-get install openscad
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$DIR/stl"

for part in phone_saddle hook_lever switch_mount cradle wall_hook ir_blaster_mount earcon_grille; do
  echo "==> $part.stl"
  openscad -o "$DIR/stl/$part.stl" "$DIR/$part.scad"
done

echo "Done. STLs in $DIR/stl/"
