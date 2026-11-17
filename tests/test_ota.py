# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Arsmillis (https://github.com/Arsmillis/multiput)
"""Over-the-air updates: the PC's real updater against the Pico's ota.h (in the desktop
simulator, with in-memory storage), plus the Pico's settings choice and `multiput --update`.

Run: python3 tests/test_ota.py   (needs g++/gcc and the arduino-pico core; see tests/pico_sim.py)
"""
import contextlib
import io
import json
import os
import pathlib
import re
import struct
import sys
import tempfile
import types

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pc"))
sys.path.insert(0, str(ROOT / "tests"))
import pico_sim  # noqa: E402
import protocol  # noqa: E402
import settings_store as store  # noqa: E402
import setup_wizard  # noqa: E402
import updater  # noqa: E402
from pico_sim import LiveLink, ask  # noqa: E402

pico_sim.start()
quiet = contextlib.redirect_stdout(io.StringIO())


def otastate():
    """The simulator's storage state; values may contain spaces (Wi-Fi passwords)."""
    return dict(re.findall(r"(\w+)=(.*?)(?= \w+=|$)", ask("otastate")))


def fresh_pico(seed, version="0.3.0"):
    """Restart the simulated Pico (new nonce); returns a connected Session and its link."""
    ask(f"init {key.hex()} 0 {seed} {seed + 1}")
    ask(f"fwversion {version}")
    ask("time 0")
    ask("storagefail 0")
    link = LiveLink()
    with quiet:
        session = updater.connect(link, key, timeout=2)
    assert session and session.firmware_version == version
    return session, link


key = os.urandom(32)
image = os.urandom(3000)  # 6 chunks; the last one partial

# A whole update: verified and installed, then the Pico restarts.
session, link = fresh_pico(100)
before = otastate()
updater.send_firmware(link, session, image)
st = otastate()
assert st["finished"] == "1" and st["image"] == image.hex() and int(st["restarts"]) == int(before["restarts"]) + 1
# Keepalives went out between chunks, keeping the link "in use" (signed reports accepted).
assert any(f[:2] == protocol.SIGNED_MAGIC for f in link.out)
print("firmware update ok")

# A lossy link: lost chunks and lost acknowledgements are resent; the image still arrives exactly.
n = {"sent": 0, "replies": 0}
def lose_sent(frame):
    if frame[:2] != updater.DATA:
        return False
    n["sent"] += 1
    return n["sent"] % 3 == 0
def lose_reply(reply):
    n["replies"] += 1
    return reply[:2] == updater.REPLY and n["replies"] % 4 == 0
session, _ = fresh_pico(110)
lossy = LiveLink(lose_sent, lose_reply)
session.link = lossy
updater.DATA_TIMEOUT_S = 0.02
updater.send_firmware(lossy, session, image)
st = otastate()
assert st["finished"] == "1" and st["image"] == image.hex()
print("lossy link ok")

# Data changed on the way: COMMIT fails, nothing is installed (the held-back last chunk is never written).
session, link = fresh_pico(120)
class Tampering(LiveLink):
    def send(self, d):
        if d[:2] == updater.DATA and struct.unpack_from("<I", d, 2)[0] == 1024:
            d = d[:20] + bytes([d[20] ^ 1]) + d[21:]
        super().send(d)
tamper = Tampering()
session.link = tamper
try:
    updater.send_firmware(tamper, session, image)
    raise AssertionError("a tampered image was accepted")
except updater.UpdateError as e:
    assert "rejected the image" in str(e)
st = otastate()
assert st["finished"] == "0" and int(st["written"]) < len(image)  # the last chunk was held back
print("tampered image rejected ok")

# Wrong key, and replays: BEGIN/COMMIT signatures are bound to the key, the counter and the Pico session.
session, link = fresh_pico(130)
impostor = protocol.Session(link, os.urandom(32))
impostor.nonce, impostor.counter = session.nonce, session.counter
try:
    updater.send_firmware(link, impostor, image)
    raise AssertionError("an update signed with the wrong key started")
except updater.UpdateError as e:
    assert "rejected the signature" in str(e)
recorded = LiveLink()
session.link = recorded
updater.send_firmware(recorded, session, image)  # a genuine update, recorded
for frame in recorded.out:                       # replayed in the same session: stale counters
    if frame[:2] == updater.BEGIN:
        replay = LiveLink()
        replay.send(frame)
        assert replay.inbox[:3] == b"MR\x81"
_, later = fresh_pico(140)                       # replayed after the Pico restarted: wrong nonce
later.send(next(f for f in recorded.out if f[:2] == updater.BEGIN))
assert later.inbox[:3] == b"MR\x81"
print("wrong key and replays rejected ok")

# DATA with no update running, DATA past the end, a stalled update, and failing storage.
session, link = fresh_pico(150)
link.send(updater.DATA + struct.pack("<IH", 0, 4) + b"abcd")
assert link.inbox[:3] == b"MR\x83"
link.inbox = b""
link.send(session.signed_frame(updater.BEGIN, struct.pack("<I", 10)))
link.send(updater.DATA + struct.pack("<IH", 0, 12) + b"x" * 12)
assert link.inbox[-7:-4] == b"MR\x84"
link.inbox = b""
link.send(session.signed_frame(updater.BEGIN, struct.pack("<I", 1000)))
link.send(updater.DATA + struct.pack("<IH", 0, 100) + b"y" * 100)
ask("time 10001")                                # 10 s without data: dropped
link.send(updater.DATA + struct.pack("<IH", 100, 100) + b"y" * 100)
assert link.inbox[-7:-4] == b"MR\x83"
ask("storagefail 1")
link.inbox = b""
try:
    updater.send_firmware(link, session, image)
    raise AssertionError("a storage failure was ignored")
except updater.UpdateError as e:
    assert "couldn't store" in str(e)
ask("storagefail 0")
print("bad data, stall and storage failure ok")

# Wi-Fi change: encrypted (the password never appears on the link), signed, validated by the Pico.
session, link = fresh_pico(160)
updater.send_wifi(link, session, "NewNet", "correct horse battery")
st = otastate()
assert st["wifi"] == "NewNet/correct horse battery"
assert not any(b"correct horse" in f or b"NewNet" in f for f in link.out)
updater.send_wifi(link, session, "", "")          # an empty network name turns Wi-Fi off
assert otastate()["wifi"] == "<off>/<none>"
bad = updater.wifi_payload("Net", "short")         # not a valid WPA2 password: refused by the Pico
frame = session.signed_frame(updater.WIFI, build=lambda c: updater.wifi_encrypt(key, session.nonce, c, bad))
link.inbox = b""
link.send(frame)
assert link.inbox[:3] == b"MR\x85" and otastate()["wifi"] == "<off>/<none>"
impostor = protocol.Session(link, os.urandom(32))
impostor.nonce, impostor.counter = session.nonce, session.counter + 100
try:
    updater.send_wifi(link, impostor, "EvilNet", "password123")
    raise AssertionError("a Wi-Fi change with the wrong key was accepted")
except updater.UpdateError as e:
    assert "rejected the signature" in str(e)
assert otastate()["wifi"] == "<off>/<none>"
print("wifi change ok")

# Which settings the Pico runs with (settings.h choose_settings).
cases = {
    ("A", "none", "blank"): "BUILTIN",   # first boot after a USB setup flash
    ("A", "X", "A"): "SAVED",            # later boots, and after an over-the-air Wi-Fi change
    ("B", "X", "A"): "BUILTIN",          # a new USB setup wins over the old saved settings
    ("blank", "X", "A"): "SAVED",        # after an over-the-air firmware update (blank block)
    ("blank", "none", "blank"): "NONE",  # never set up: triple blink
    ("blank", "garbage", "A"): "NONE",   # unreadable settings file, nothing built in
    ("A", "garbage", "A"): "BUILTIN",
}
for (b, s, src), want in cases.items():
    assert ask(f"choose {b} {s} {src}") == want, (b, s, src)
print("settings choice ok")

# `multiput --update`: refuses firmware from before over-the-air updates; otherwise installs the
# bundled image, waits for the Pico to come back, and can change the Wi-Fi network.
updater.time = types.SimpleNamespace(monotonic=updater.time.monotonic,
                                     sleep=lambda s: None if s >= 1 else __import__("time").sleep(s))
cfg = pathlib.Path(tempfile.mkdtemp())
(cfg / "multiput.bin").write_bytes(image)
saved = {"link": "wifi", "host": "multiput.local", "ssid": "HomeNet"}
store.save_settings(cfg, saved)
no = lambda prompt, default=None: "n"
yes = lambda prompt, default=None: "y"
args = types.SimpleNamespace(firmware=None, ssid=None, password=None, allow_unsigned=False)
ask(f"init {key.hex()} 0 170 171")
ask("fwversion 0.2.0")
try:
    with quiet:
        updater.run_update(args, LiveLink(), key, saved, store, cfg, cfg, setup_wizard.ask_wifi, yes)
    raise AssertionError("0.2.0 firmware can't update in place")
except SystemExit as e:
    assert "can't be updated in place" in str(e)
ask("fwversion 0.3.0")
updater.VERSION = "0.3.1"  # the app is newer than the Pico: offer the bundled firmware
before = otastate()
with quiet:
    updater.run_update(args, LiveLink(), key, saved, store, cfg, cfg, setup_wizard.ask_wifi, lambda p, d=None: "y" if "Install" in p else "n")
st = otastate()
assert st["finished"] == "1" and st["image"] == image.hex() and int(st["restarts"]) == int(before["restarts"]) + 1
args.ssid, args.password = "OtherNet", "password123"   # change the network, firmware already current
updater.VERSION = "0.3.0"
with quiet:
    updater.run_update(args, LiveLink(), key, saved, store, cfg, cfg, setup_wizard.ask_wifi, no)
assert otastate()["wifi"] == "OtherNet/password123"
assert json.loads((cfg / "settings.json").read_text())["ssid"] == "OtherNet"
assert b"password123" not in (cfg / "settings.json").read_bytes()
print("multiput --update ok")
print("ALL OK")
