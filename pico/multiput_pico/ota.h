// SPDX-License-Identifier: Apache-2.0
// Copyright (C) 2026 Arsmillis (https://github.com/Arsmillis/multiput)
// Over-the-air updates, sent by `multiput --update`: a new firmware image, or new
// Wi-Fi settings, while the Pico stays where it is. No Arduino dependencies (storage
// is reached through g_ota), so it is tested on the desktop with protocol.h.
//
// Frames (integers little-endian; "signed" = HMAC as in protocol.h, counter rules included):
//   BEGIN   PC -> Pico  "MU" counter[8] size[4] mac[16]                   (30)   signed
//   DATA    PC -> Pico  "MD" offset[4] length[2] data[length <= 512]      unsigned, see COMMIT
//   COMMIT  PC -> Pico  "MC" counter[8] image_mac[16] mac[16]             (42)   signed
//   WIFI    PC -> Pico  "MW" counter[8] encrypted[98] mac[16]             (124)  signed, encrypted
//   REPLY   Pico -> PC  "MR" code[1] value[4]                             (7)
//
// The image is only installed if image_mac = HMAC(key, nonce || "image" || size || image)[:16]
// matches every byte received, so DATA needn't be signed: forged or corrupted data just
// fails COMMIT. The nonce ties an update to this Pico session (no replaying old ones).
// The last chunk is held back until COMMIT checks out, because the storage layer installs
// an image as soon as it's complete; an update that fails is discarded, never installed.
//
// WIFI carries ssid[33] pass[64] reserved[1] (an empty ssid turns Wi-Fi off), XORed with the keystream
// HMAC(wifi_key, nonce || counter || block)[0..31], block = 0, 1, 2, 3, where
// wifi_key = HMAC(key, "multiput wifi settings"). The signing key and the other
// settings (such as accepting unsigned input) never change over the air.
#pragma once

static const size_t OTA_CHUNK_MAX = 512;
static const size_t OTA_BEGIN_LEN = 2 + 8 + 4 + MAC_LEN;
static const size_t OTA_DATA_HEADER = 2 + 4 + 2;
static const size_t OTA_COMMIT_LEN = 2 + 8 + MAC_LEN + MAC_LEN;
static const size_t OTA_WIFI_PAYLOAD = 33 + 64 + 1;
static const size_t OTA_WIFI_LEN = 2 + 8 + OTA_WIFI_PAYLOAD + MAC_LEN;
static const uint32_t OTA_IDLE_MS = 10000;  // an update with no DATA for this long is dropped

enum OtaReply : uint8_t {
  OTA_READY = 0,          // value: the next offset expected
  OTA_INSTALLING = 1,     // image verified; restarting to install it
  OTA_WIFI_SAVED = 2,     // new Wi-Fi settings stored; restarting to use them
  OTA_BAD_SIGNATURE = 0x81,
  OTA_STORAGE_FAILED = 0x82,
  OTA_NOT_UPDATING = 0x83,
  OTA_IMAGE_REJECTED = 0x84,
  OTA_BAD_SETTINGS = 0x85,
};

// Storage and timing, supplied by the sketch (flash + LittleFS) or by the desktop test.
struct OtaSink {
  bool (*begin)(uint32_t size);
  bool (*write)(const uint8_t *data, size_t len);
  bool (*finish)();  // the image is complete and verified: install it on the next boot
  void (*abort)();   // discard a partial image
  bool (*saveWifi)(const char *ssid, const char *pass);
  void (*restartSoon)();  // reboot shortly, after the reply has gone out
  uint32_t (*nowMs)();
};
static OtaSink g_ota;

static br_hmac_key_context g_wifiKey;
static bool g_updating = false;
static uint32_t g_updateSize = 0, g_updateNext = 0, g_updateActivityMs = 0;
static br_hmac_context g_imageMac;
static uint8_t g_held[OTA_CHUNK_MAX];
static size_t g_heldLen = 0;

static void ota_init(const uint8_t key[KEY_LEN]) {
  static const char label[] = "multiput wifi settings";
  br_hmac_context ctx;
  uint8_t wifiKey[32];
  br_hmac_init(&ctx, &g_hmacKey, 0);
  br_hmac_update(&ctx, label, sizeof label - 1);
  br_hmac_out(&ctx, wifiKey);
  br_hmac_key_init(&g_wifiKey, &br_sha256_vtable, wifiKey, sizeof wifiKey);
  (void)key;  // g_hmacKey (from protocol_init) already holds it
  g_updating = false;
  g_heldLen = 0;
}

static void ota_reply(Frame &f, uint8_t code, uint32_t value) {
  f.reply[0] = 'M';
  f.reply[1] = 'R';
  f.reply[2] = code;
  memcpy(f.reply + 3, &value, 4);
  f.replyLen = 7;
}

static void ota_stop() {
  if (g_updating) g_ota.abort();
  g_updating = false;
  g_heldLen = 0;
}

// Call regularly: drops an update that stalled (PC closed, link lost).
static void ota_poll() {
  if (g_updating && g_ota.nowMs() - g_updateActivityMs > OTA_IDLE_MS) ota_stop();
}

static void ota_begin(const uint8_t *b, Frame &f) {
  uint32_t size;
  memcpy(&size, b + 10, 4);
  ota_stop();  // a new BEGIN replaces any update in progress
  if (size == 0 || !g_ota.begin(size)) {
    ota_reply(f, OTA_STORAGE_FAILED, size);
    return;
  }
  static const char label[] = "image";
  br_hmac_init(&g_imageMac, &g_hmacKey, MAC_LEN);
  br_hmac_update(&g_imageMac, g_nonce, NONCE_LEN);
  br_hmac_update(&g_imageMac, label, sizeof label - 1);
  br_hmac_update(&g_imageMac, &size, 4);
  g_updating = true;
  g_updateSize = size;
  g_updateNext = 0;
  g_updateActivityMs = g_ota.nowMs();
  ota_reply(f, OTA_READY, 0);
}

static void ota_data(const uint8_t *b, size_t len, uint32_t offset, Frame &f) {
  if (!g_updating) {
    ota_reply(f, OTA_NOT_UPDATING, 0);
    return;
  }
  g_updateActivityMs = g_ota.nowMs();
  if (offset != g_updateNext || len == 0) {  // a resend or out of order: say where we are
    ota_reply(f, OTA_READY, g_updateNext);
    return;
  }
  if (offset + len > g_updateSize) {
    ota_stop();
    ota_reply(f, OTA_IMAGE_REJECTED, offset);
    return;
  }
  if (g_heldLen && !g_ota.write(g_held, g_heldLen)) {  // the previous chunk is safe to write now
    ota_stop();
    ota_reply(f, OTA_STORAGE_FAILED, offset);
    return;
  }
  memcpy(g_held, b, len);
  g_heldLen = len;
  br_hmac_update(&g_imageMac, b, len);
  g_updateNext += len;
  ota_reply(f, OTA_READY, g_updateNext);
}

static void ota_commit(const uint8_t *b, Frame &f) {
  if (!g_updating) {
    ota_reply(f, OTA_NOT_UPDATING, 0);
    return;
  }
  uint8_t mac[MAC_LEN];
  br_hmac_out(&g_imageMac, mac);
  if (g_updateNext != g_updateSize || !same_mac(mac, b + 10)) {
    uint32_t got = g_updateNext;
    ota_stop();  // the held-back last chunk was never written, so nothing gets installed
    ota_reply(f, OTA_IMAGE_REJECTED, got);
    return;
  }
  bool ok = g_ota.write(g_held, g_heldLen) && g_ota.finish();
  g_updating = false;
  g_heldLen = 0;
  if (!ok) {
    g_ota.abort();
    ota_reply(f, OTA_STORAGE_FAILED, g_updateSize);
    return;
  }
  ota_reply(f, OTA_INSTALLING, g_updateSize);
  g_ota.restartSoon();
}

static bool nul_within(const uint8_t *p, size_t n) {
  return memchr(p, 0, n) != nullptr;
}

static void ota_wifi(const uint8_t *b, Frame &f) {
  uint8_t plain[OTA_WIFI_PAYLOAD];
  for (uint8_t block = 0; block * 32 < OTA_WIFI_PAYLOAD; block++) {
    br_hmac_context ctx;
    uint8_t stream[32];
    br_hmac_init(&ctx, &g_wifiKey, 0);
    br_hmac_update(&ctx, g_nonce, NONCE_LEN);
    br_hmac_update(&ctx, b + 2, 8);  // counter
    br_hmac_update(&ctx, &block, 1);
    br_hmac_out(&ctx, stream);
    for (size_t i = 0; i < 32 && block * 32 + i < OTA_WIFI_PAYLOAD; i++)
      plain[block * 32 + i] = b[10 + block * 32 + i] ^ stream[i];
  }
  const char *ssid = (const char *)plain, *pass = (const char *)plain + 33;
  size_t passLen = nul_within(plain + 33, 64) ? strlen(pass) : 99;
  if (!nul_within(plain, 33) || passLen > 63 || (passLen > 0 && passLen < 8)) {
    ota_reply(f, OTA_BAD_SETTINGS, 0);
    return;
  }
  if (!g_ota.saveWifi(ssid, pass)) {
    ota_reply(f, OTA_STORAGE_FAILED, 0);
    return;
  }
  ota_reply(f, OTA_WIFI_SAVED, 0);
  g_ota.restartSoon();
}

// protocol.h's parse_frame hands over the frame types it doesn't know. Returns false
// for anything that isn't an update frame.
static bool ota_frame(const uint8_t *b, size_t n, Frame &f) {
  switch (b[1]) {
    case 'U':
      if (n < OTA_BEGIN_LEN) return true;  // f.used == 0: wait for more bytes
      f.used = OTA_BEGIN_LEN;
      if (!signed_ok(b, OTA_BEGIN_LEN - MAC_LEN) || !take_counter(b)) ota_reply(f, OTA_BAD_SIGNATURE, 0);
      else ota_begin(b, f);
      return true;
    case 'D': {
      if (n < OTA_DATA_HEADER) return true;
      uint32_t offset;
      uint16_t len;
      memcpy(&offset, b + 2, 4);
      memcpy(&len, b + 6, 2);
      if (len > OTA_CHUNK_MAX) {
        f.used = 1;  // not a valid frame: resynchronise
        return true;
      }
      if (n < OTA_DATA_HEADER + len) return true;
      f.used = OTA_DATA_HEADER + len;
      ota_data(b + OTA_DATA_HEADER, len, offset, f);
      return true;
    }
    case 'C':
      if (n < OTA_COMMIT_LEN) return true;
      f.used = OTA_COMMIT_LEN;
      if (!signed_ok(b, OTA_COMMIT_LEN - MAC_LEN) || !take_counter(b)) ota_reply(f, OTA_BAD_SIGNATURE, 0);
      else ota_commit(b, f);
      return true;
    case 'W':
      if (n < OTA_WIFI_LEN) return true;
      f.used = OTA_WIFI_LEN;
      if (!signed_ok(b, OTA_WIFI_LEN - MAC_LEN) || !take_counter(b)) ota_reply(f, OTA_BAD_SIGNATURE, 0);
      else ota_wifi(b, f);
      return true;
    default:
      return false;
  }
}
