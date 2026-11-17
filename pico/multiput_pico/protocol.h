// SPDX-License-Identifier: Apache-2.0
// Copyright (C) 2026 Arsmillis (https://github.com/Arsmillis/multiput)
// multiput wire protocol (Pico side). Uses only BearSSL (bundled with the arduino-pico
// core), so it can also be tested on a desktop. The PC side lives in pc/protocol.py.
//
// Frames (all integers little-endian):
//   HELLO     PC -> Pico  "MH"
//   SYNC      Pico -> PC  "MN" nonce[8] last_counter[8]                    (18 bytes)
//   SIGNED    PC -> Pico  "MS" counter[8] report[8] mac[16]                (34 bytes)
//   UNSIGNED  PC -> Pico  "MI" report[8]   (only if unsigned is allowed)   (10 bytes)
//   VERSION?  PC -> Pico  "MV"
//   VERSION   Pico -> PC  "MV" length[1] version[length]  (e.g. "0.2.0"; firmware 0.1.0 never answers)
//
// mac = first 16 bytes of HMAC-SHA256(key, nonce || "MS" || counter || report).
// The nonce is random per Pico boot, so packets recorded in an earlier session are
// useless. The counter must strictly increase within a session, so packets can't be
// replayed. The Pico sends SYNC in reply to HELLO and to rejected packets, which is
// how the PC learns a new nonce after the Pico reboots. SYNC is unsigned: forging
// one can only make the PC's packets get rejected, never inject input.
#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <bearssl/bearssl_hmac.h>

struct __attribute__((packed)) Report {  // HORIPAD S HID input report
  uint16_t buttons;
  uint8_t hat;
  uint8_t lx, ly, rx, ry;
  uint8_t vendor;
};
static_assert(sizeof(Report) == 8, "report must be 8 bytes");

static const Report NEUTRAL = {0, 8, 128, 128, 128, 128, 0};

static const size_t KEY_LEN = 32, NONCE_LEN = 8, MAC_LEN = 16;
static const size_t SYNC_LEN = 2 + NONCE_LEN + 8;
static const size_t SIGNED_BODY_LEN = 2 + 8 + sizeof(Report);
static const size_t SIGNED_LEN = SIGNED_BODY_LEN + MAC_LEN;
static const size_t UNSIGNED_LEN = 2 + sizeof(Report);

struct Frame {
  size_t used;    // bytes consumed; 0 = need more data
  bool accepted;  // g_report was updated
  bool wantSync;  // caller should send a SYNC frame back
  bool wantVersion;  // caller should send a VERSION frame back
};

static const size_t VERSION_MAX = 32;

static br_hmac_key_context g_hmacKey;
static bool g_allowUnsigned = false;
static uint8_t g_nonce[NONCE_LEN];
static uint64_t g_lastCounter = 0;
static Report g_report = NEUTRAL;

static void protocol_init(const uint8_t key[KEY_LEN], bool allowUnsigned, uint32_t rand1, uint32_t rand2) {
  br_hmac_key_init(&g_hmacKey, &br_sha256_vtable, key, KEY_LEN);
  g_allowUnsigned = allowUnsigned;
  memcpy(g_nonce, &rand1, 4);
  memcpy(g_nonce + 4, &rand2, 4);
  g_lastCounter = 0;
  g_report = NEUTRAL;
}

static void accept_report(const uint8_t *p) {
  memcpy(&g_report, p, sizeof(Report));
  if (g_report.hat > 8) g_report.hat = 8;
}

static bool mac_ok(const uint8_t *frame) {
  br_hmac_context ctx;
  uint8_t mac[MAC_LEN];
  br_hmac_init(&ctx, &g_hmacKey, MAC_LEN);  // truncated to 16 bytes
  br_hmac_update(&ctx, g_nonce, NONCE_LEN);
  br_hmac_update(&ctx, frame, SIGNED_BODY_LEN);
  br_hmac_out(&ctx, mac);
  uint8_t diff = 0;  // constant-time compare
  for (size_t i = 0; i < MAC_LEN; i++) diff |= mac[i] ^ frame[SIGNED_BODY_LEN + i];
  return diff == 0;
}

// Parses one frame at the start of buf. Works for single datagrams and byte streams
// (on garbage it consumes 1 byte so a stream re-synchronises).
static Frame parse_frame(const uint8_t *b, size_t n) {
  Frame f = {0, false, false, false};
  if (n < 2) return f;
  if (b[0] != 'M') { f.used = 1; return f; }
  switch (b[1]) {
    case 'H':
      f.used = 2;
      f.wantSync = true;
      return f;
    case 'V':  // informational and unsigned, like SYNC: a forged reply can only mislead a message
      f.used = 2;
      f.wantVersion = true;
      return f;
    case 'S': {
      if (n < SIGNED_LEN) return f;
      if (!mac_ok(b)) { f.used = 1; f.wantSync = true; return f; }
      f.used = SIGNED_LEN;
      uint64_t counter;
      memcpy(&counter, b + 2, 8);  // RP2040 and x86 are little-endian
      if (counter <= g_lastCounter) { f.wantSync = true; return f; }  // replay or stale
      g_lastCounter = counter;
      accept_report(b + 10);
      f.accepted = true;
      return f;
    }
    case 'I':
      if (!g_allowUnsigned) { f.used = 1; return f; }
      if (n < UNSIGNED_LEN) return f;
      accept_report(b + 2);
      f.used = UNSIGNED_LEN;
      f.accepted = true;
      return f;
    default:
      f.used = 1;
      return f;
  }
}

// VERSION frame into out (at least 3 + VERSION_MAX bytes); returns its length.
static size_t build_version(uint8_t *out, const char *version) {
  size_t n = strlen(version);
  if (n > VERSION_MAX) n = VERSION_MAX;
  out[0] = 'M';
  out[1] = 'V';
  out[2] = (uint8_t)n;
  memcpy(out + 3, version, n);
  return 3 + n;
}

static void build_sync(uint8_t out[SYNC_LEN]) {
  out[0] = 'M';
  out[1] = 'N';
  memcpy(out + 2, g_nonce, NONCE_LEN);
  memcpy(out + 2 + NONCE_LEN, &g_lastCounter, 8);
}
