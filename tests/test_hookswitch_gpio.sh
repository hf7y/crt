#!/usr/bin/env bash
set -uo pipefail   # offline: fake sysfs tree, no Pi needed
BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../bin" && pwd)"
fail=0

check() {
  local desc="$1" expected="$2" got="$3"
  if [ "$got" = "$expected" ]; then
    echo "ok - $desc"
  else
    echo "FAIL - $desc: expected [$expected], got [$got]"
    fail=1
  fi
}

make_fake_gpio() {   # $1=pin $2=initial raw value; pre-exported (no export file)
  local base pin="$1" val="$2"
  base="$(mktemp -d)"
  mkdir -p "$base/gpio$pin"
  printf '%s' "$val" > "$base/gpio$pin/value"
  printf 'in' > "$base/gpio$pin/direction"
  echo "$base"
}

# Case 1: active_low=1 (default) -- raw 0 reads as on-hook (value 1).
base="$(make_fake_gpio 17 0)"
got=$(
  CRT_HOOK_TEST_MODE=1 CRT_HOOK_GPIO_SYSFS_BASE="$base" bash -c '
    source "'"$BIN_DIR"'/hookswitch-listen.sh"
    gpio_loop 17 1 &
    pid=$!
    sleep 0.15
    kill "$pid" 2>/dev/null
    wait "$pid" 2>/dev/null
  ' 2>/dev/null
)
check "active-low raw 0 reads as logical on (value 1)" "GPIO_HOOK value 1" "$got"
rm -rf "$base"

# Case 2: active_low=0 -- raw 1 reads straight through as on.
base="$(make_fake_gpio 17 1)"
got=$(
  CRT_HOOK_TEST_MODE=1 CRT_HOOK_GPIO_SYSFS_BASE="$base" bash -c '
    source "'"$BIN_DIR"'/hookswitch-listen.sh"
    gpio_loop 17 0 &
    pid=$!
    sleep 0.15
    kill "$pid" 2>/dev/null
    wait "$pid" 2>/dev/null
  ' 2>/dev/null
)
check "active-high raw 1 reads straight through as on (value 1)" "GPIO_HOOK value 1" "$got"
rm -rf "$base"

# Case 3: gpio_loop's real output reaches apply_state via debounce_loop (two steps, not a live pipe).
base="$(make_fake_gpio 17 1)"
gpio_lines=$(
  CRT_HOOK_TEST_MODE=1 CRT_HOOK_GPIO_SYSFS_BASE="$base" CRT_HOOK_GPIO_POLL_MS=5 bash -c '
    source "'"$BIN_DIR"'/hookswitch-listen.sh"
    gpio_loop 17 1 &
    pid=$!
    sleep 0.1
    printf "%s" "0" > "'"$base"'/gpio17/value"   # switch closes -> on-hook
    sleep 0.1
    kill "$pid" 2>/dev/null
    wait "$pid" 2>/dev/null
  ' 2>/dev/null
)
rm -rf "$base"
case "$gpio_lines" in
  *"GPIO_HOOK value 0"*"GPIO_HOOK value 1"*)
    echo "ok - captured a real off-hook-then-on-hook transition from gpio_loop" ;;
  *)
    echo "FAIL - gpio_loop did not emit the expected two-line transition: [$gpio_lines]"
    fail=1 ;;
esac

got=$(
  CRT_HOOK_TEST_MODE=1 CRT_HOOK_DEBOUNCE_MS=30 CRT_HOOK_KEY=GPIO_HOOK \
    CRT_HOOK_STT_PROCESS="sleep 9999" bash -c '
      source "'"$BIN_DIR"'/hookswitch-listen.sh"
      { printf "%s\n" "$1"; sleep 1; } | debounce_loop &
      pid=$!
      sleep 0.2
      kill "$pid" 2>/dev/null
      wait "$pid" 2>/dev/null
    ' _ "$gpio_lines" 2>/dev/null
)
case "$got" in
  *"on-hook"*)
    echo "ok - gpio_loop's real output reaches apply_state via the shared debounce_loop" ;;
  *)
    echo "FAIL - gpio_loop's captured output did not reach apply_state: [$got]"
    fail=1 ;;
esac

# Case 4: export-on-demand -- no pre-existing value file, writing to export creates it.
base="$(mktemp -d)"
touch "$base/export"
got=$(
  CRT_HOOK_TEST_MODE=1 CRT_HOOK_GPIO_SYSFS_BASE="$base" bash -c '
    source "'"$BIN_DIR"'/hookswitch-listen.sh"
    ( while [ ! -s "'"$base"'/export" ]; do sleep 0.01; done   # fake kernel
      mkdir -p "'"$base"'/gpio17"
      printf 1 > "'"$base"'/gpio17/value" ) &
    watcher=$!
    gpio_loop 17 0 &
    pid=$!
    sleep 0.3
    kill "$pid" "$watcher" 2>/dev/null
    wait "$pid" "$watcher" 2>/dev/null
  ' 2>/dev/null
)
check "export-on-demand path emits the pin's first settled value" "GPIO_HOOK value 1" "$got"
rm -rf "$base"

exit "$fail"
