#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Arsmillis (https://github.com/Arsmillis/multiput)
# Build the generic (blank-settings) firmware: build/firmware/multiput.uf2
# (one firmware for both Wi-Fi and Bluetooth).
# Installs what it needs the first time (arduino-cli into ~/.local/bin, then the
# Raspberry Pi Pico board core, about 500 MB). Set ARDUINO_CLI to use another arduino-cli.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
CORE_URL=https://github.com/earlephilhower/arduino-pico/releases/download/global/package_rp2040_index.json
TESTED_CORE=6.3.2

if [ -n "${ARDUINO_CLI:-}" ]; then
  CLI=$ARDUINO_CLI
elif command -v arduino-cli >/dev/null; then
  CLI=arduino-cli
else
  CLI=~/.local/bin/arduino-cli
  if [ ! -x "$CLI" ]; then
    echo "== Installing arduino-cli into ~/.local/bin (one time)"
    mkdir -p ~/.local/bin
    curl -fsSL https://downloads.arduino.cc/arduino-cli/arduino-cli_latest_Linux_64bit.tar.gz | tar xz -C ~/.local/bin arduino-cli
  fi
fi
if ! "$CLI" core list 2>/dev/null | grep -q '^rp2040:rp2040 '; then
  echo "== Installing the Raspberry Pi Pico board core (about 500 MB, one time)"
  "$CLI" core update-index --additional-urls "$CORE_URL"
  "$CLI" core install rp2040:rp2040 --additional-urls "$CORE_URL"
fi
CORE=$("$CLI" core list | awk '$1 == "rp2040:rp2040" { print $2 }')
[ "$CORE" = "$TESTED_CORE" ] || echo "note: rp2040 core $CORE is installed; multiput was tested with $TESTED_CORE"

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
OUT="$ROOT/build/firmware"
LOGS="$ROOT/build/logs"  # full compiler output, one file per build
mkdir -p "$OUT" "$LOGS"
FQBN=rp2040:rp2040:rpipicow:usbstack=tinyusb

echo "== firmware"
LOG="$LOGS/firmware.log"
if ! "$CLI" compile --fqbn "$FQBN,ipbtstack=ipv4btcble" --warnings all --output-dir "$WORK/out" \
     "$ROOT/pico/multiput_pico" >"$LOG" 2>&1; then
  grep -E "error" "$LOG" | head -20
  echo "Full compiler output: build/logs/firmware.log"
  exit 1
fi
# Library warnings are noise; only show warnings from our own files.
grep -E "multiput_pico/[A-Za-z_]+\.(ino|h|cpp):[0-9]+:[0-9]+: warning" "$LOG" || true
grep -E "^(Sketch uses|Global variables)" "$LOG"
cp "$WORK/out/multiput_pico.ino.uf2" "$OUT/multiput.uf2"

# The settings block must be in flash (so it is in the .uf2) and be 147 bytes.
DATA=$("$CLI" config get directories.data)
NM=$(ls "$DATA"/packages/rp2040/tools/pqt-gcc/*/bin/arm-none-eabi-nm | head -1)
"$NM" -S "$WORK/out/multiput_pico.ino.elf" | awk '/ MULTIPUT_SETTINGS$/ { found = 1
  ok = ($1 ~ /^10/ && $2 == "00000093"); print "== MULTIPUT_SETTINGS at 0x" $1 ", size 0x" $2 (ok ? " (ok)" : " (UNEXPECTED)") }
  END { exit !(found && ok) }'
echo "Wrote $OUT/multiput.uf2"
