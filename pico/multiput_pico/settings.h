// SPDX-License-Identifier: Apache-2.0
// Copyright (C) 2026 Arsmillis (https://github.com/Arsmillis/multiput)
// Per-user settings. They are NOT compiled in: the firmware ships with this block
// blank, and `multiput --setup` on the PC finds it inside the .uf2 file (by its magic)
// and fills it in before flashing.
//
// The layout must match SETTINGS_FORMAT in pc/firmware.py.
#pragma once
#include <stdint.h>

struct __attribute__((packed)) Settings {
  char magic[16];      // "multiput-config1" (16 bytes, no NUL); only the PC tool reads it
  uint8_t configured;  // 0 = blank firmware, 1 = filled in by --setup
  uint8_t flags;       // SETTINGS_ALLOW_UNSIGNED
  char ssid[33];       // NUL-terminated (Wi-Fi only)
  char pass[64];       // NUL-terminated (Wi-Fi only)
  uint8_t key[32];     // signing key
};
static_assert(sizeof(Settings) == 147, "update pc/firmware.py if this changes");

static const uint8_t SETTINGS_ALLOW_UNSIGNED = 1 << 0;
