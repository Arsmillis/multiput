// SPDX-License-Identifier: Apache-2.0
// Copyright (C) 2026 Arsmillis (https://github.com/Arsmillis/multiput)
// Thin wrapper around SerialBT/BTstack for transport_bt.h, kept in its own file on
// purpose: BTstack's headers and Adafruit TinyUSB's headers both declare
// hid_report_type_t, so they can't be included in the same translation unit.
#include <BluetoothLock.h>
#include <SerialBT.h>
#include <btstack.h>
#include <stddef.h>
#include <stdint.h>

void btBegin(const char *name) {
  SerialBT.setName(name);
  SerialBT.begin();
}

void btListen(bool on) {
  BluetoothLock lock;  // BTstack calls from the sketch must hold the Bluetooth lock
  gap_connectable_control(on);
  gap_discoverable_control(on);
}

int btRead() {
  return SerialBT.available() ? SerialBT.read() : -1;
}

void btWrite(const uint8_t *data, size_t len) {
  SerialBT.write(data, len);
}
