#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Arsmillis (https://github.com/Arsmillis/multiput)
# Run all tests (WSL/Linux). Needs python3, gcc/g++, and the rp2040 core
# (tools/build_firmware.sh installs the core; build the firmware first so the
# setup tests also check the real .uf2 files).
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
for tool in python3 gcc g++; do
  command -v "$tool" >/dev/null || { echo "Missing $tool. Install it with: sudo apt install python3 build-essential"; exit 1; }
done
echo "== tests/test_protocol.py"
python3 "$ROOT/tests/test_protocol.py"
echo "== tests/test_setup.py"
python3 "$ROOT/tests/test_setup.py"
echo "== tests/test_controller.py"
python3 "$ROOT/tests/test_controller.py"
echo "== tests/test_perf.py"
python3 "$ROOT/tests/test_perf.py"
echo "== tests/test_release.py"
python3 "$ROOT/tests/test_release.py"
