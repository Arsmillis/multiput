// SPDX-License-Identifier: Apache-2.0
// Copyright (C) 2026 Arsmillis (https://github.com/Arsmillis/multiput)
// Thin wrapper around SerialBT/BTstack for transport_bt.h, kept in its own file on
// purpose: BTstack's headers and Adafruit TinyUSB's headers both declare
// hid_report_type_t, so they can't be included in the same translation unit.
#include <BluetoothLock.h>
#include <SerialBT.h>
#include <btstack.h>
#include <hal_flash_bank.h>
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

// Bluetooth pairing keys. The arduino-pico core keeps them inside the firmware image
// (__bluetooth_tlv), so installing new firmware wipes them; multiput_pico.ino saves them
// before an over-the-air update and restores them afterwards. These go through the same
// flash routines the Bluetooth stack itself uses (safe with interrupts and the other core).
extern "C" const hal_flash_bank_t *pico_flash_bank_instance(void);

uint32_t btKeysBankSize() {
  return pico_flash_bank_instance()->get_size(nullptr);
}

void btKeysRead(int bank, uint32_t offset, uint8_t *buf, uint32_t len) {
  pico_flash_bank_instance()->read(nullptr, bank, offset, buf, len);
}

void btKeysErase(int bank) {
  pico_flash_bank_instance()->erase(nullptr, bank);
}

void btKeysWrite(int bank, uint32_t offset, const uint8_t *buf, uint32_t len) {
  pico_flash_bank_instance()->write(nullptr, bank, offset, buf, len);
}
