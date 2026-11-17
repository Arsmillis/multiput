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

// Settings are also kept in the Pico's flash storage (settings.bin), so that an
// over-the-air update can install the generic firmware (blank block) and keep them,
// and so `multiput --update` can change the Wi-Fi network in place.
struct __attribute__((packed)) SavedSettings {
  Settings s;
  uint32_t builtinHash;  // settings_hash() of the built-in block these were saved from
};

static uint32_t settings_hash(const Settings &s) {  // FNV-1a: tells built-in blocks apart
  uint32_t h = 2166136261u;
  const uint8_t *p = (const uint8_t *)&s;
  for (size_t i = 0; i < sizeof s; i++) h = (h ^ p[i]) * 16777619u;
  return h;
}

enum SettingsChoice { USE_NONE, USE_BUILTIN, USE_SAVED };

// builtin: the firmware's own block (filled in by --setup for a USB flash; blank in an
// over-the-air image). saved: settings.bin, or nullptr if missing or unreadable.
//   - A configured built-in block the Pico hasn't seen before is a fresh USB setup:
//     it wins (and the caller saves it).
//   - Otherwise the saved settings win: after an over-the-air firmware update (blank
//     block), and after an over-the-air Wi-Fi change (same built-in block as before).
static SettingsChoice choose_settings(const Settings &builtin, const SavedSettings *saved) {
  bool builtinOk = builtin.configured == 1;
  bool savedOk = saved && saved->s.configured == 1;
  if (builtinOk && !(savedOk && saved->builtinHash == settings_hash(builtin))) return USE_BUILTIN;
  if (savedOk) return USE_SAVED;
  return USE_NONE;
}
