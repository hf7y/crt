#!/usr/bin/env bash
# The console's config, read from ONE place by everything that needs it.
# Sourced, never executed:  . "$BIN_DIR/crt-conf.sh"
#
# WHY THIS EXISTS (2026-07-29, found live). potato's console identity --
#   [rest: vault:crt/header-archaeology-20260817.md]

# Executing this instead of sourcing it does nothing useful and would
# fail silently -- the assignments would land in a shell that then exits.
# Say so loudly rather than looking like a successful no-op.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  echo "crt-conf.sh must be SOURCED, not executed: . \$BIN_DIR/crt-conf.sh" >&2
  exit 2
fi

CRT_CONSOLE_CONF="${CRT_CONSOLE_CONF:-$HOME/.crt/console.conf}"
CRT_BRAIN_CONF="${CRT_BRAIN_CONF:-$HOME/.crt/brain.conf}"
CRT_MANDARK_CONF="${CRT_MANDARK_CONF:-$HOME/.crt/mandark.conf}"

if [ -f "$CRT_CONSOLE_CONF" ]; then
  # shellcheck disable=SC1090
  . "$CRT_CONSOLE_CONF"
fi

if [ -f "$CRT_BRAIN_CONF" ]; then
  # shellcheck disable=SC1090
  . "$CRT_BRAIN_CONF"
elif [ -f "$CRT_MANDARK_CONF" ]; then
  # shellcheck disable=SC1090
  . "$CRT_MANDARK_CONF"
fi
