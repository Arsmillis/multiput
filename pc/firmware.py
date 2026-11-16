# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Arsmillis (https://github.com/Arsmillis/multiput)
"""Fill in the settings block inside a generic multiput .uf2 firmware file.

The firmware ships with a blank settings block (pico/multiput_pico/settings.h).
UF2 is the Pico's drag-and-drop format: 512-byte blocks, each carrying up to
476 bytes of flash contents plus its address. We locate the block by its magic
in the flash contents and overwrite it in place; nothing else changes.
"""

import struct

from protocol import KEY_LEN

UF2_BLOCK = 512
UF2_MAGICS = (0x0A324655, 0x9E5D5157)
UF2_MAGIC_END = 0x0AB16F30
UF2_FLAG_NOT_MAIN_FLASH = 0x1

SETTINGS_MAGIC = b"multiput-config1"  # exactly 16 bytes (char magic[16])
SETTINGS_FORMAT = "<16sBB33s64s32s"  # must match struct Settings in settings.h
SETTINGS_ALLOW_UNSIGNED = 0x1


def check_ssid(ssid):
    if not ssid:
        raise ValueError("a Wi-Fi name is required")
    if len(ssid.encode()) > 32:
        raise ValueError("Wi-Fi name is longer than 32 bytes")


def pack_settings(key, ssid="", password="", allow_unsigned=False):
    """ssid/password are empty for the Bluetooth firmware."""
    ssid_b, pass_b = ssid.encode(), password.encode()
    if len(key) != KEY_LEN:
        raise ValueError("key must be 32 bytes")
    if ssid:
        check_ssid(ssid)
    if pass_b and not 8 <= len(pass_b) <= 63:
        raise ValueError("Wi-Fi password must be 8-63 characters (or empty for an open network)")
    flags = SETTINGS_ALLOW_UNSIGNED if allow_unsigned else 0
    return struct.pack(SETTINGS_FORMAT, SETTINGS_MAGIC, 1, flags, ssid_b, pass_b, key)


def _flash_bytes(uf2):
    """Concatenated flash contents and, for each byte, its offset in the file."""
    if len(uf2) % UF2_BLOCK:
        raise ValueError("not a UF2 file (size is not a multiple of 512)")
    blocks = []
    for off in range(0, len(uf2), UF2_BLOCK):
        m0, m1, flags, addr, size = struct.unpack_from("<5I", uf2, off)
        (end,) = struct.unpack_from("<I", uf2, off + UF2_BLOCK - 4)
        if (m0, m1) != UF2_MAGICS or end != UF2_MAGIC_END or size > 476:
            raise ValueError(f"not a valid UF2 block at offset {off}")
        if not flags & UF2_FLAG_NOT_MAIN_FLASH:
            blocks.append((addr, off + 32, size))
    image, where = bytearray(), []
    for _, start, size in sorted(blocks):
        image += uf2[start:start + size]
        where.extend(range(start, start + size))
    return image, where


def _find_settings(image):
    i = image.find(SETTINGS_MAGIC)
    if i < 0 or image.find(SETTINGS_MAGIC, i + 1) >= 0:
        raise ValueError("expected exactly one multiput settings block; is this a multiput firmware file?")
    return i


def patch_uf2(uf2, settings):
    """Return a copy of the .uf2 bytes with the settings block replaced."""
    image, where = _flash_bytes(uf2)
    i = _find_settings(image)
    out = bytearray(uf2)
    for k, b in enumerate(settings):
        out[where[i + k]] = b
    return bytes(out)


def read_settings(uf2):
    """The raw settings block from a .uf2 (used by tests)."""
    image, _ = _flash_bytes(uf2)
    i = _find_settings(image)
    return bytes(image[i:i + struct.calcsize(SETTINGS_FORMAT)])
