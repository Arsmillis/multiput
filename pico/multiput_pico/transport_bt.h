// SPDX-License-Identifier: Apache-2.0
// Copyright (C) 2026 Arsmillis (https://github.com/Arsmillis/multiput)
// Bluetooth link (Classic SPP serial). The PC opens the paired device's COM port.
//
// SPP pairing on the Pico uses "Just Works" (no PIN), so anyone nearby can connect
// while it is discoverable. Signed packets are what keep them from sending input.
#pragma once

// SerialBT wrapper in transport_bt_serial.cpp (separate file: its headers clash with TinyUSB's).
void btBegin(const char *name);
void btListen(bool on);  // accept connections and be discoverable, or neither
int btRead();            // next byte, or -1 if none
void btWrite(const uint8_t *data, size_t len);
// Pairing keys: 2 banks of btKeysBankSize() bytes (see transport_bt_serial.cpp)
static const int BT_KEY_BANKS = 2;
uint32_t btKeysBankSize();
void btKeysRead(int bank, uint32_t offset, uint8_t *buf, uint32_t len);
void btKeysErase(int bank);
void btKeysWrite(int bank, uint32_t offset, const uint8_t *buf, uint32_t len);

static uint8_t rxBuf[640];  // must hold a whole frame: up to an over-the-air DATA frame (8 + 512 bytes)
static size_t rxLen = 0;
static bool btListening = true;  // SerialBT starts out connectable and discoverable

void btStart() {
  btBegin("multiput");  // pc/links.py (BT_NAME) finds the PC's COM port by this name
}

void btReply(const uint8_t *data, size_t len) {
  btWrite(data, len);
}

// wifiInUse: Wi-Fi is carrying the PC's input, so stop listening and leave it the radio.
// An open Bluetooth connection is unaffected; this only stops new ones.
void btPoll(bool wifiInUse) {
  if (btListening == wifiInUse) {
    btListening = !wifiInUse;
    btListen(btListening);
  }
  // SPP is a byte stream: buffer it and cut it into frames.
  int c;
  while (rxLen < sizeof rxBuf && (c = btRead()) >= 0) rxBuf[rxLen++] = (uint8_t)c;
  size_t off = 0;
  while (off < rxLen) {
    size_t used = handleFrame(rxBuf + off, rxLen - off, LINK_BT);
    if (!used) break;  // partial frame; wait for more bytes
    off += used;
  }
  memmove(rxBuf, rxBuf + off, rxLen - off);
  rxLen -= off;
}
