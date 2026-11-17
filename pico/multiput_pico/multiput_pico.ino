// SPDX-License-Identifier: Apache-2.0
// Copyright (C) 2026 Arsmillis (https://github.com/Arsmillis/multiput)
// Pico W: receive signed controller state from the PC and present it to the
// Switch 2 as a wired HORIPAD-style controller.
//
// Board: "Raspberry Pi Pico W" (arduino-pico core by Earle Philhower)
// Tools > USB Stack: "Adafruit TinyUSB"
// Tools > IP/Bluetooth Stack: "IPv4 + Bluetooth" (the firmware uses both links)
// Wi-Fi name/password and the signing key are not compiled in: `multiput --setup`
// writes them into the .uf2 (see settings.h). No Wi-Fi name = Bluetooth only.
//
// Both links are listened on; the PC picks one. While one carries signed input,
// the other steps back so they don't compete for the shared radio: Bluetooth stops
// accepting connections while Wi-Fi is in use, and Wi-Fi goes into power-save
// (and stops reconnect attempts) while Bluetooth is in use.

#include <Adafruit_TinyUSB.h>
#include <LittleFS.h>
#include <Updater.h>
#include "settings.h"
#include "protocol.h"

#ifndef ENABLE_CLASSIC
#error "Set Tools > IP/Bluetooth Stack to \"IPv4 + Bluetooth\": this firmware uses both Wi-Fi and Bluetooth"
#endif

// Set from the VERSION file by tools/build_firmware.sh (e.g. -DMULTIPUT_VERSION=0.2.0;
// a version like 0.2.0 is a single preprocessor token, so it needs no quoting).
#ifndef MULTIPUT_VERSION
#define MULTIPUT_VERSION dev
#endif
#define MP_STR2(x) #x
#define MP_STR(x) MP_STR2(x)
static const char FIRMWARE_VERSION[] = MP_STR(MULTIPUT_VERSION);

const uint32_t TIMEOUT_MS = 250;       // no valid packet this long -> release all inputs
const uint32_t SYNC_INTERVAL_MS = 100; // rate limit for SYNC replies
const uint32_t IN_USE_MS = 2000;       // a link is "in use" while signed input arrived within this

// Blank settings block, patched in the .uf2 by the PC tool. `volatile` stops the
// compiler from baking the blank values into the code; `used` keeps it in the image.
extern "C" __attribute__((used, aligned(256))) const volatile Settings MULTIPUT_SETTINGS = {
  {'m', 'u', 'l', 't', 'i', 'p', 'u', 't', '-', 'c', 'o', 'n', 'f', 'i', 'g', '1'}, 0, 0, {0}, {0}, {0}
};
Settings settings;  // the settings in use, loaded in setup() (see choose_settings in settings.h)
uint32_t builtinHash = 0;
uint32_t restartAtMs = 0;
static const char *SETTINGS_FILE = "/settings.bin";
static const char *BT_KEYS_FILE = "/btkeys.bin";  // pairing keys saved across an update
static const char *BT_KEYS_LOG = "/btkeys.log";   // what happened to them last (for `multiput --pico-status`)
char keysLastSave[40] = "none", keysLastRestore[40] = "none";
uint32_t lastStatusMs = 0;

// HORI HORIPAD S report descriptor (a Switch-compatible wired controller).
static const uint8_t desc_hid_report[] = {
  0x05, 0x01, 0x09, 0x05, 0xA1, 0x01,
  // 16 buttons
  0x15, 0x00, 0x25, 0x01, 0x35, 0x00, 0x45, 0x01, 0x75, 0x01, 0x95, 0x10,
  0x05, 0x09, 0x19, 0x01, 0x29, 0x10, 0x81, 0x02,
  // hat switch
  0x05, 0x01, 0x25, 0x07, 0x46, 0x3B, 0x01, 0x75, 0x04, 0x95, 0x01,
  0x65, 0x14, 0x09, 0x39, 0x81, 0x42,
  0x65, 0x00, 0x95, 0x01, 0x81, 0x01,
  // sticks: X, Y, Z, Rz
  0x26, 0xFF, 0x00, 0x46, 0xFF, 0x00, 0x09, 0x30, 0x09, 0x31, 0x09, 0x32, 0x09, 0x35,
  0x75, 0x08, 0x95, 0x04, 0x81, 0x02,
  // vendor byte in, 8 bytes out
  0x06, 0x00, 0xFF, 0x09, 0x20, 0x95, 0x01, 0x81, 0x02,
  0x0A, 0x21, 0x26, 0x95, 0x08, 0x91, 0x02,
  0xC0
};

Adafruit_USBD_HID usb_hid;
uint32_t lastPacketMs = 0;
uint32_t lastSyncMs = 0;
uint32_t lastVersionMs = 0;

enum Link { LINK_WIFI, LINK_BT };
uint32_t lastSignedMs[2];
bool everSigned[2];

// Only accepted (signed) input counts, so an unsigned HELLO from some other device
// can't keep a link "in use" and lock the PC out of the other one.
bool inUse(Link link) {
  return everSigned[link] && millis() - lastSignedMs[link] < IN_USE_MS;
}

// Implemented in transport_wifi.h / transport_bt.h.
void wifiReply(const uint8_t *data, size_t len);
void btReply(const uint8_t *data, size_t len);

// Called by a transport for each received frame; returns bytes consumed.
// Replies go back over the link the frame came in on.
size_t handleFrame(const uint8_t *buf, size_t len, Link link) {
  Frame f = parse_frame(buf, len);
  if (f.accepted) {
    lastPacketMs = lastSignedMs[link] = millis();
    everSigned[link] = true;
  }
  if (f.replyLen) {  // over-the-air update reply: one per frame, not rate-limited (it paces the transfer)
    if (link == LINK_WIFI) wifiReply(f.reply, f.replyLen);
    else btReply(f.reply, f.replyLen);
  } else if (f.wantSync && millis() - lastSyncMs >= SYNC_INTERVAL_MS) {
    uint8_t sync[SYNC_LEN];
    build_sync(sync);
    if (link == LINK_WIFI) wifiReply(sync, SYNC_LEN);
    else btReply(sync, SYNC_LEN);
    lastSyncMs = millis();
  } else if (f.wantStatus && millis() - lastStatusMs >= SYNC_INTERVAL_MS) {
    uint8_t reply[3 + 128];
    char text[128];
    int n = snprintf(text, sizeof text, "fw=%s; bt keys=%s; last save=%s; last restore=%s", FIRMWARE_VERSION,
                     btKeysPresent() ? "present" : "none", keysLastSave, keysLastRestore);
    n = n < 0 ? 0 : (n >= (int)sizeof text ? (int)sizeof text - 1 : n);
    reply[0] = 'M';
    reply[1] = 'G';
    reply[2] = (uint8_t)n;
    memcpy(reply + 3, text, n);
    if (link == LINK_WIFI) wifiReply(reply, 3 + n);
    else btReply(reply, 3 + n);
    lastStatusMs = millis();
  } else if (f.wantVersion && millis() - lastVersionMs >= SYNC_INTERVAL_MS) {
    // Its own rate limit: the PC asks right after a SYNC, which must not block the answer.
    uint8_t reply[3 + VERSION_MAX];
    size_t len = build_version(reply, FIRMWARE_VERSION);
    if (link == LINK_WIFI) wifiReply(reply, len);
    else btReply(reply, len);
    lastVersionMs = millis();
  }
  return f.used;
}

#include "transport_wifi.h"
#include "transport_bt.h"

// Blank firmware (never run through --setup): triple-blink forever and never
// appear on the Switch.
void haltNotConfigured() {
  for (;;) {
    for (int i = 0; i < 3; i++) {
      digitalWrite(LED_BUILTIN, HIGH);
      delay(100);
      digitalWrite(LED_BUILTIN, LOW);
      delay(100);
    }
    delay(800);
  }
}

bool storeSettings(const Settings &s) {
  SavedSettings out = {s, builtinHash};
  File f = LittleFS.open(SETTINGS_FILE, "w");
  if (!f) return false;
  bool ok = f.write((const uint8_t *)&out, sizeof out) == sizeof out;
  f.close();
  return ok;
}

void loadSettings() {
  Settings builtin;
  for (size_t i = 0; i < sizeof(Settings); i++)
    ((uint8_t *)&builtin)[i] = ((const volatile uint8_t *)&MULTIPUT_SETTINGS)[i];
  builtinHash = settings_hash(builtin);
  SavedSettings saved;
  bool haveSaved = false;
  LittleFS.begin();  // formats the storage area on first use
  File f = LittleFS.open(SETTINGS_FILE, "r");
  if (f) {
    haveSaved = f.read((uint8_t *)&saved, sizeof saved) == sizeof saved;
    f.close();
  }
  switch (choose_settings(builtin, haveSaved ? &saved : nullptr)) {
    case USE_BUILTIN:  // a fresh USB setup: keep it for over-the-air updates
      settings = builtin;
      storeSettings(settings);
      break;
    case USE_SAVED:
      settings = saved.s;
      break;
    default:
      haltNotConfigured();
  }
  settings.ssid[sizeof settings.ssid - 1] = '\0';
  settings.pass[sizeof settings.pass - 1] = '\0';
}

// Bluetooth pairing keys live inside the firmware image (an arduino-pico core detail), so
// installing new firmware wipes them and Windows would have to re-pair, which takes about
// a minute. saveBtKeys() copies them to storage just before an update is installed;
// restoreBtKeys() writes them back on the new firmware's first boot.
void writeKeysLog() {
  File f = LittleFS.open(BT_KEYS_LOG, "w");
  if (!f) return;
  f.printf("%s\n%s\n", keysLastSave, keysLastRestore);
  f.close();
}

void readKeysLog() {
  File f = LittleFS.open(BT_KEYS_LOG, "r");
  if (!f) return;
  String save = f.readStringUntil('\n'), restore = f.readStringUntil('\n');
  f.close();
  strncpy(keysLastSave, save.c_str(), sizeof keysLastSave - 1);
  strncpy(keysLastRestore, restore.c_str(), sizeof keysLastRestore - 1);
}

// Does the key store hold any pairing keys right now? (for the status report)
bool btKeysPresent() {
  uint8_t buf[256];
  uint32_t size = btKeysBankSize();
  for (int bank = 0; bank < BT_KEY_BANKS; bank++)
    for (uint32_t off = 0; off < size; off += sizeof buf) {
      btKeysRead(bank, off, buf, sizeof buf);
      if (!keystore_chunk_empty(buf, sizeof buf, off == 0)) return true;
    }
  return false;
}

void saveBtKeys() {
  File f = LittleFS.open(BT_KEYS_FILE, "w");
  if (!f) {  // not fatal: Windows just re-pairs
    snprintf(keysLastSave, sizeof keysLastSave, "failed: can't open file");
    writeKeysLog();
    return;
  }
  uint8_t buf[256];
  uint32_t size = btKeysBankSize(), written = 0;
  for (int bank = 0; bank < BT_KEY_BANKS; bank++)
    for (uint32_t off = 0; off < size; off += sizeof buf) {
      btKeysRead(bank, off, buf, sizeof buf);
      written += f.write(buf, sizeof buf);
    }
  f.close();
  snprintf(keysLastSave, sizeof keysLastSave, "%s %lu B", written == BT_KEY_BANKS * size ? "saved" : "short write",
           (unsigned long)written);
  writeKeysLog();
}

// Returns true if it restored keys (the caller restarts, so the Bluetooth stack loads them).
bool restoreBtKeys() {
  File f = LittleFS.open(BT_KEYS_FILE, "r");
  if (!f) return false;
  uint8_t buf[256];
  uint32_t size = btKeysBankSize();
  bool sizeOk = f.size() == BT_KEY_BANKS * size;
  bool blank = sizeOk;  // the key store holds no keys (blank, or just the header the stack wrote at boot)
  for (int bank = 0; blank && bank < BT_KEY_BANKS; bank++)
    for (uint32_t off = 0; blank && off < size; off += sizeof buf) {
      btKeysRead(bank, off, buf, sizeof buf);
      blank = keystore_chunk_empty(buf, sizeof buf, off == 0);
    }
  if (!sizeOk) snprintf(keysLastRestore, sizeof keysLastRestore, "discarded: saved size %lu", (unsigned long)f.size());
  else if (!blank) snprintf(keysLastRestore, sizeof keysLastRestore, "kept: keys already present");
  else snprintf(keysLastRestore, sizeof keysLastRestore, "restored %lu B", (unsigned long)(BT_KEY_BANKS * size));
  if (blank) {  // a fresh image: put the saved keys back
    for (int bank = 0; bank < BT_KEY_BANKS; bank++) {
      btKeysErase(bank);
      for (uint32_t off = 0; off < size; off += sizeof buf) {
        f.read(buf, sizeof buf);
        btKeysWrite(bank, off, buf, sizeof buf);
      }
    }
  }
  f.close();
  LittleFS.remove(BT_KEYS_FILE);  // used once; keys already present are never overwritten
  writeKeysLog();
  return blank;
}

// Over-the-air update storage (ota.h): the core's Updater writes the image to
// firmware.bin in LittleFS, and the OTA loader installs it on the next boot.
bool otaBegin(uint32_t size) { return Update.begin(size); }
bool otaWrite(const uint8_t *data, size_t len) { return Update.write((uint8_t *)data, len) == len; }
bool otaFinish() {
  saveBtKeys();  // the new image wipes them; restoreBtKeys() puts them back on its first boot
  return Update.end();
}
void otaAbort() { Update.end(false); }  // incomplete, so discarded rather than installed
bool otaSaveWifi(const char *ssid, const char *pass) {
  Settings s = settings;
  memset(s.ssid, 0, sizeof s.ssid);
  memset(s.pass, 0, sizeof s.pass);
  strncpy(s.ssid, ssid, sizeof s.ssid - 1);
  strncpy(s.pass, pass, sizeof s.pass - 1);
  return storeSettings(s);
}
void otaRestartSoon() { restartAtMs = (millis() + 300) | 1; }  // never 0, which means "no restart pending"
uint32_t otaNowMs() { return millis(); }

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  loadSettings();
  readKeysLog();
  // The Bluetooth stack already opened its key store before setup() (initVariant), so after
  // restoring the keys, restart once for it to load them.
  if (restoreBtKeys()) rp2040.reboot();
  protocol_init(settings.key, settings.flags & SETTINGS_ALLOW_UNSIGNED, rp2040.hwrand32(), rp2040.hwrand32());
  ota_init(settings.key);
  g_ota = {otaBegin, otaWrite, otaFinish, otaAbort, otaSaveWifi, otaRestartSoon, otaNowMs};

  // USB first, so the Switch sees the controller straight away; both links then
  // come up in the background.
  // Present only the HID gamepad (no USB serial) with HORIPAD S IDs.
  // clearConfiguration() resets the whole device descriptor, including the IDs
  // and strings, to Adafruit's defaults (239A:CAFE), so it must come first.
  TinyUSBDevice.clearConfiguration();
  TinyUSBDevice.setID(0x0F0D, 0x00C1);
  TinyUSBDevice.setManufacturerDescriptor("HORI CO.,LTD.");
  TinyUSBDevice.setProductDescriptor("HORIPAD S");
  usb_hid.setPollInterval(1);
  usb_hid.setReportDescriptor(desc_hid_report, sizeof(desc_hid_report));
  usb_hid.begin();
  if (TinyUSBDevice.mounted()) {  // re-enumerate with the new descriptors
    TinyUSBDevice.detach();
    delay(10);
    TinyUSBDevice.attach();
  }
  wifiBegin();
  btStart();
}

void loop() {
  wifiPoll(inUse(LINK_BT));
  btPoll(inUse(LINK_WIFI));
  ota_poll();
  if (restartAtMs && (int32_t)(millis() - restartAtMs) >= 0) rp2040.reboot();  // after an update

  bool live = millis() - lastPacketMs <= TIMEOUT_MS;
  if (!live) g_report = NEUTRAL;  // never leave buttons stuck
  // LED: solid = receiving input; fast blink = joining Wi-Fi; slow blink = waiting for the PC.
  uint32_t blink = wifiJoining() && !inUse(LINK_BT) ? 125 : 500;
  digitalWrite(LED_BUILTIN, live || (millis() / blink) % 2 ? HIGH : LOW);

  if (usb_hid.ready()) usb_hid.sendReport(0, &g_report, sizeof(g_report));
}
