# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Arsmillis (https://github.com/Arsmillis/multiput)
"""Tests for patching the settings block into a .uf2 and for the --setup flow.

Run: python3 tests/test_setup.py
Uses the real build/firmware/multiput-*.uf2 if built (tools/build_firmware.sh), plus a
synthetic UF2 where the settings block straddles two UF2 blocks.
"""
import contextlib
import io
import json
import os
import pathlib
import struct
import sys
import tempfile
import types

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pc"))
import firmware  # noqa: E402
import settings_store as store  # noqa: E402
import setup_wizard  # noqa: E402

SIZE = struct.calcsize(firmware.SETTINGS_FORMAT)
assert SIZE == 147, "must match sizeof(Settings) in settings.h"


def blank_settings():
    return firmware.SETTINGS_MAGIC + bytes(SIZE - 16)


def make_uf2(flash, payload=256, base=0x10000000):
    blocks = [flash[i:i + payload] for i in range(0, len(flash), payload)]
    out = b""
    for n, data in enumerate(blocks):
        head = struct.pack("<8I", *firmware.UF2_MAGICS, 0x2000, base + n * payload, len(data), n, len(blocks), 0xE48BFF56)
        out += head + data.ljust(476, b"\0") + struct.pack("<I", firmware.UF2_MAGIC_END)
    return out


def check_patch(uf2):
    assert firmware.read_settings(uf2) == blank_settings(), "firmware should ship with a blank settings block"
    key = os.urandom(32)
    packed = firmware.pack_settings(key, "MyWifi", "hunter2hunter2")
    patched = firmware.patch_uf2(uf2, packed)
    assert firmware.read_settings(patched) == packed
    assert len(patched) == len(uf2)
    assert sum(a != b for a, b in zip(uf2, patched)) <= SIZE  # nothing outside the block changed
    magic, configured, flags, ssid, pw, k = struct.unpack(firmware.SETTINGS_FORMAT, packed)
    assert (configured, flags, ssid.rstrip(b"\0"), pw.rstrip(b"\0"), k) == (1, 0, b"MyWifi", b"hunter2hunter2", key)
    # Re-patching an already configured file works (re-running setup).
    assert firmware.read_settings(firmware.patch_uf2(patched, blank_settings())) == blank_settings()


# Synthetic: the block starts 100 bytes before a 256-byte payload boundary.
flash = os.urandom(300) + blank_settings() + os.urandom(300)
check_patch(make_uf2(flash))
print("synthetic UF2 (block split across UF2 blocks) ok")

for name in ("multiput.uf2",):
    path = ROOT / "build" / "firmware" / name
    if path.exists():
        check_patch(path.read_bytes())
        print(f"{name} ok")
    else:
        print(f"{name} not built; skipped (run tools/build_firmware.sh)")

# Validation
for bad in [dict(ssid="x" * 33), dict(password="short"), dict(password="x" * 64)]:
    try:
        firmware.pack_settings(os.urandom(32), **bad)
        raise AssertionError(f"accepted {bad}")
    except ValueError:
        pass
firmware.pack_settings(os.urandom(32), "OpenCafe", "")  # open network is fine
for bad in [b"not a uf2", make_uf2(os.urandom(1024)), make_uf2(blank_settings() * 2)]:
    try:
        firmware.patch_uf2(bad, blank_settings())
        raise AssertionError("accepted a bad file")
    except ValueError:
        pass
print("validation ok")

# --setup end to end (non-interactive, --output instead of a real Pico drive).
cfg = pathlib.Path(tempfile.mkdtemp())
out = cfg / "configured.uf2"
uf2 = make_uf2(flash)
fw = cfg / "multiput.uf2"
fw.write_bytes(uf2)
args = types.SimpleNamespace(no_wifi=False, link="wifi", ssid="Home", password="password123", allow_unsigned=False, new_key=False,
                             firmware=None, output=out, drive=None, host=None, port=None)
assert setup_wizard.run_setup(args, cfg, cfg) is False  # nothing flashed
key = store.load_key(cfg)
assert firmware.read_settings(out.read_bytes()) == firmware.pack_settings(key, "Home", "password123")
assert json.loads((cfg / "settings.json").read_text()) == {"link": "wifi", "host": "multiput.local", "ssid": "Home", "pico_wifi": True}
assert b"password123" not in (cfg / "settings.json").read_bytes() + (cfg / "multiput.key").read_bytes()
# Re-running setup keeps the key unless --new-key.
setup_wizard.run_setup(args, cfg, cfg)
assert store.load_key(cfg) == key
args.new_key = True
setup_wizard.run_setup(args, cfg, cfg)
assert store.load_key(cfg) != key
# Bluetooth only (no Wi-Fi on the Pico), with the COM port given up front; flash to a fake drive folder.
drive = cfg / "drive"
drive.mkdir()
args = types.SimpleNamespace(no_wifi=True, link="bt", ssid=None, password=None, allow_unsigned=True, new_key=False,
                             firmware=None, output=None, drive=drive, host=None, port="COM7")
assert setup_wizard.run_setup(args, cfg, cfg) is True
flashed = firmware.read_settings((drive / "multiput.uf2").read_bytes())
assert flashed[17] == firmware.SETTINGS_ALLOW_UNSIGNED and flashed[18:51] == bytes(33)  # no Wi-Fi name
assert json.loads((cfg / "settings.json").read_text()) == {"link": "bt", "port": "COM7", "ssid": "Home", "pico_wifi": False}
# Wi-Fi set up, but Bluetooth chosen as the link: both kept, so either can be used later.
args = types.SimpleNamespace(no_wifi=False, link="bt", ssid="Home", password="password123", allow_unsigned=False,
                             new_key=False, firmware=None, output=out, drive=None, host=None, port="COM7")
setup_wizard.run_setup(args, cfg, cfg)
assert json.loads((cfg / "settings.json").read_text()) == {"link": "bt", "port": "COM7", "ssid": "Home",
                                                           "pico_wifi": True, "host": "multiput.local"}
# --no-wifi with --link wifi is refused before anything is flashed or saved.
before = (cfg / "settings.json").read_text()
out.unlink()
args.no_wifi, args.link = True, "wifi"
try:
    setup_wizard.run_setup(args, cfg, cfg)
    raise AssertionError("--no-wifi --link wifi should be refused")
except SystemExit as e:
    assert "needs Wi-Fi" in str(e)
assert not out.exists() and (cfg / "settings.json").read_text() == before
print("setup flow ok")

# --- Regressions from code review ---
# --new-key must not replace the saved key unless flashing succeeded.
key_before = store.load_key(cfg)
args = types.SimpleNamespace(no_wifi=False, link="wifi", ssid="Home", password="password123", allow_unsigned=False, new_key=True,
                             firmware=cfg / "missing.uf2", output=None, drive=drive, host=None, port=None)
try:
    setup_wizard.run_setup(args, cfg, cfg)
    raise AssertionError("missing firmware should fail")
except FileNotFoundError:
    pass
assert store.load_key(cfg) == key_before
print("failed setup keeps old key ok")

# Wi-Fi name: blank is rejected; invalid command-line values raise instead of looping.
key = os.urandom(32)
for ssid, password in [("", "password123"), ("x" * 33, None)]:
    try:
        setup_wizard.ask_wifi(types.SimpleNamespace(ssid=ssid, password=password, allow_unsigned=False), key)
        raise AssertionError(f"accepted ssid {ssid!r}")
    except ValueError:
        pass
# Interactive: each invalid answer re-asks only that question.
answers = iter(["", "x" * 33, "Home"])
passwords = iter(["short", "password123"])
setup_wizard.ask = lambda prompt, default=None: next(answers)
setup_wizard.getpass.getpass = lambda prompt: next(passwords)
packed, _ = setup_wizard.ask_wifi(types.SimpleNamespace(ssid=None, password=None, allow_unsigned=False), key)
assert packed == firmware.pack_settings(key, "Home", "password123")
print("wifi prompts ok")

# Flash: a write error while the Pico unmounts counts as success; a drive that stays means failure.
setup_wizard.time.sleep = lambda s: None
missing_drive = cfg / "gone"  # writing here raises FileNotFoundError, like a vanished drive
seen = iter([missing_drive, missing_drive, None])
setup_wizard.find_pico_drive = lambda: next(seen)
setup_wizard.flash(missing_drive, b"x")
setup_wizard.find_pico_drive = lambda: missing_drive
try:
    setup_wizard.flash(missing_drive, b"x")
    raise AssertionError("a drive that stays should be a failure")
except OSError:
    pass
print("flash error handling ok")

# The last network name is the default at the next setup; other saved settings survive re-setup.
cfg2 = pathlib.Path(tempfile.mkdtemp())
store.save_settings(cfg2, {"link": "wifi", "host": "multiput.local", "ssid": "HomeNet", "buttons": {"A": "B"}})
(cfg2 / "multiput.uf2").write_bytes(uf2)
offered = []
def answer_blank(prompt, default=None):
    offered.append(default)
    return default  # what pressing Enter does
setup_wizard.ask = answer_blank
setup_wizard.getpass.getpass = lambda prompt: "password123"
args = types.SimpleNamespace(no_wifi=False, link="wifi", ssid=None, password=None, allow_unsigned=False, new_key=False,
                             firmware=None, output=cfg2 / "o.uf2", drive=None, host=None, port=None)
setup_wizard.run_setup(args, cfg2, cfg2)
assert offered == ["y", "HomeNet"], offered  # "Set up Wi-Fi?" (Enter = yes), then the remembered name
saved = json.loads((cfg2 / "settings.json").read_text())
assert saved == {"link": "wifi", "host": "multiput.local", "ssid": "HomeNet", "buttons": {"A": "B"}, "pico_wifi": True}, saved
assert b"password123" not in (cfg2 / "settings.json").read_bytes()
print("remembered network name ok")

# Setup offers the auto-detected COM port after pairing (Enter accepts it).
setup_wizard.find_bt_port = lambda: "COM5"
setup_wizard.input = lambda prompt: ""
setup_wizard.ask = lambda prompt, default=None: default
with contextlib.redirect_stdout(io.StringIO()):
    assert setup_wizard.ask_bt_port() == "COM5"
del setup_wizard.input
print("setup port detection ok")

# multiput uses the detected port at startup and saves it if Windows renumbered it.
import multiput  # noqa: E402
opened = []
multiput.SerialLink = lambda port: opened.append(port) or port
cfg3 = pathlib.Path(tempfile.mkdtemp())
saved3 = {"link": "bt", "port": "COM3"}
store.save_settings(cfg3, saved3)
none = types.SimpleNamespace(bt=None, host=None, link=None)
multiput.find_bt_port = lambda: "COM5"
with contextlib.redirect_stdout(io.StringIO()):
    multiput.open_link(none, cfg3, saved3)
assert opened == ["COM5"] and store.load_settings(cfg3)["port"] == "COM5"
multiput.find_bt_port = lambda: None            # not detected: fall back to the saved port
multiput.open_link(none, cfg3, store.load_settings(cfg3))
assert opened[-1] == "COM5"
multiput.open_link(types.SimpleNamespace(bt="COM8", host=None, link=None), cfg3, saved3)  # --bt always wins
assert opened[-1] == "COM8"
try:
    multiput.open_link(none, cfg3, {"link": "bt"})  # nothing detected, nothing saved
    raise AssertionError("should explain how to fix it")
except SystemExit as e:
    assert "Pair it in Windows" in str(e)
print("startup port detection ok")

# --link picks the link for this run and is remembered.
opened.clear()
multiput.UdpLink = lambda host: opened.append(("udp", host)) or host
multiput.find_bt_port = lambda: "COM5"
cfg4 = pathlib.Path(tempfile.mkdtemp())
saved4 = {"link": "wifi", "host": "multiput.local", "port": "COM5", "pico_wifi": True}
store.save_settings(cfg4, saved4)
with contextlib.redirect_stdout(io.StringIO()):
    multiput.open_link(types.SimpleNamespace(bt=None, host=None, link="bt"), cfg4, saved4)
assert opened[-1] == "COM5" and store.load_settings(cfg4)["link"] == "bt"
multiput.open_link(types.SimpleNamespace(bt=None, host=None, link=None), cfg4, store.load_settings(cfg4))
assert opened[-1] == "COM5"                                   # remembered
with contextlib.redirect_stdout(io.StringIO()):
    multiput.open_link(types.SimpleNamespace(bt=None, host=None, link="wifi"), cfg4, store.load_settings(cfg4))
assert opened[-1] == ("udp", "multiput.local") and store.load_settings(cfg4)["link"] == "wifi"
try:
    multiput.open_link(types.SimpleNamespace(bt=None, host=None, link="wifi"), cfg4,
                     {"link": "bt", "port": "COM5", "pico_wifi": False})
    raise AssertionError("Wi-Fi should be refused for a Bluetooth-only Pico")
except SystemExit as e:
    assert "without Wi-Fi" in str(e)
print("--link switching ok")

# Outside Windows there are no drive letters: refuse instead of waiting forever.
if os.name != "nt":
    try:
        setup_wizard.wait_for_pico_drive()
        raise AssertionError("should refuse outside Windows")
    except SystemExit as e:
        assert "needs Windows" in str(e)
    print("non-Windows refusal ok")

# One-time move from the old name's folder (minput -> multiput).
base = pathlib.Path(tempfile.mkdtemp())
old = base / store.OLD_NAME
old.mkdir()
(old / "minput.key").write_text("ab" * 32 + "\n")
store.save_settings(old, {"link": "wifi", "host": "minput.local", "buttons": {"A": "B"}})
new = base / "multiput"
assert store.migrate_old_dir(new) == old and not old.exists()
assert store.load_key(new) == bytes.fromhex("ab" * 32)
assert store.load_settings(new) == {"link": "wifi", "host": "multiput.local", "buttons": {"A": "B"}}
assert store.migrate_old_dir(new) is None                      # only once
base2 = pathlib.Path(tempfile.mkdtemp())
store.save_settings(base2 / store.OLD_NAME, {"link": "wifi", "host": "192.168.1.50"})
store.migrate_old_dir(base2 / "multiput")
assert store.load_settings(base2 / "multiput")["host"] == "192.168.1.50"  # a custom IP is kept
print("old-name migration ok")

# VERSION is the single source of the version number; it must be MAJOR.MINOR.PATCH.
import re  # noqa: E402
import version  # noqa: E402
assert re.fullmatch(r"\d+\.\d+\.\d+", (ROOT / "VERSION").read_text().strip()), "VERSION must be X.Y.Z"
assert version.VERSION == (ROOT / "VERSION").read_text().strip() and version.VERSION in version.BANNER
assert version.parse("0.10.2") == (0, 10, 2) and version.parse("dev") is None and version.parse("1.2") is None
assert version.parse("0.10.0") > version.parse("0.9.9")   # compared as numbers, not text
assert "(up to date)" in version.firmware_message("1.2.3", "1.2.3")
assert "older than" in version.firmware_message("0.9.9", "0.10.0")
assert "newer than" in version.firmware_message("0.10.0", "0.9.9")
assert "development build" in version.firmware_message("dev", "0.1.0")
assert "0.1.0 or older" in version.firmware_message(None, "0.2.0")
assert "multiput update" in version.firmware_message("0.3.0", "0.4.0")   # can update in place
assert "over USB" in version.firmware_message("0.2.0", "0.4.0")          # too old: USB setup
print("version ok")
print("ALL OK")
