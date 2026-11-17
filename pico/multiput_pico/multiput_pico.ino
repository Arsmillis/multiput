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

// Over-the-air update storage (ota.h): the core's Updater writes the image to
// firmware.bin in LittleFS, and the OTA loader installs it on the next boot.
bool otaBegin(uint32_t size) { return Update.begin(size); }
bool otaWrite(const uint8_t *data, size_t len) { return Update.write((uint8_t *)data, len) == len; }
bool otaFinish() { return Update.end(); }
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
