// SPDX-License-Identifier: Apache-2.0
// Copyright (C) 2026 Arsmillis (https://github.com/Arsmillis/multiput)
// Wi-Fi link: UDP datagrams on PORT, discoverable as HOSTNAME.local.
// Connects in the background (never blocks), so USB and Bluetooth work even when
// the network isn't reachable. Disabled when setup was given no Wi-Fi name.
#pragma once
#include <WiFi.h>
#include <WiFiUdp.h>
#include <LEAmDNS.h>

static const char *HOSTNAME = "multiput";
static const uint16_t PORT = 41234;
static const uint32_t WIFI_RETRY_MS = 10000;  // re-attempt a lost/failed connection this often

static WiFiUDP udp;
static bool wifiEnabled = false;   // a Wi-Fi name was configured
static bool netStarted = false;    // mDNS + UDP started (after the first connection)
static bool wasConnected = false;
static int powerSave = -1;         // power mode last applied: -1 unknown, 0 full power, 1 power-save
static uint32_t wifiAttemptMs = 0;

void wifiBegin() {
  wifiEnabled = settings.ssid[0] != '\0';
  if (!wifiEnabled) return;
  WiFi.mode(WIFI_STA);
  WiFi.setHostname(HOSTNAME);
  WiFi.beginNoBlock(settings.ssid, settings.pass);
  wifiAttemptMs = millis();
}

// Configured but not connected yet (for the LED).
bool wifiJoining() {
  return wifiEnabled && WiFi.status() != WL_CONNECTED;
}

// Replies go to the sender of the datagram currently being handled.
void wifiReply(const uint8_t *data, size_t len) {
  udp.beginPacket(udp.remoteIP(), udp.remotePort());
  udp.write(data, len);
  udp.endPacket();
}

// btInUse: Bluetooth is carrying the PC's input, so stay out of the radio's way.
void wifiPoll(bool btInUse) {
  if (!wifiEnabled) return;
  bool connected = WiFi.status() == WL_CONNECTED;
  if (!connected) {
    wasConnected = false;
    powerSave = -1;
    // Joining scans the air, which would disturb Bluetooth; wait until it's free.
    if (!btInUse && millis() - wifiAttemptMs > WIFI_RETRY_MS) {
      WiFi.beginNoBlock(settings.ssid, settings.pass);
      wifiAttemptMs = millis();
    }
    return;
  }
  if (!netStarted) {
    MDNS.begin(HOSTNAME);
    udp.begin(PORT);
    netStarted = true;
  } else if (!wasConnected) {
    MDNS.notifyAPChange();  // reconnected, maybe with a new IP: announce multiput.local again
  }
  wasConnected = true;
  // Full power keeps Wi-Fi latency low (power-save holds packets back by tens of ms);
  // power-save while Bluetooth is in use leaves the shared radio to Bluetooth.
  int wanted = btInUse ? 1 : 0;
  if (powerSave != wanted) {
    if (wanted) WiFi.defaultLowPowerMode();
    else WiFi.noLowPowerMode();
    powerSave = wanted;
  }
  MDNS.update();
  uint8_t buf[600];  // up to an over-the-air DATA frame (8 + 512 bytes)
  while (int len = udp.parsePacket()) {  // drain the queue
    if (len > (int)sizeof buf) {
      udp.flush();
      continue;
    }
    udp.read(buf, len);
    handleFrame(buf, len, LINK_WIFI);  // one frame per datagram
  }
}
