# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Arsmillis (https://github.com/Arsmillis/multiput)
"""`multiput --update`: update the Pico's firmware, and optionally its Wi-Fi network,
over the link it's already on, so it can stay in the console's dock.

The frame formats and the Pico side are in pico/multiput_pico/ota.h.
"""

import hashlib
import hmac
import struct
import sys
import time

from controller import NEUTRAL_REPORT
from protocol import MAC_LEN, Session
from version import OTA_SINCE, VERSION, parse

BEGIN, DATA, COMMIT, WIFI, REPLY = b"MU", b"MD", b"MC", b"MW", b"MR"
REPLY_LEN = 7
CHUNK = 512
READY, INSTALLING, WIFI_SAVED = 0, 1, 2
ERRORS = {
    0x81: "the Pico rejected the signature (was it set up with a different key? run multiput setup over USB)",
    0x82: "the Pico couldn't store the update",
    0x83: "the Pico wasn't expecting update data",
    0x84: "the Pico rejected the image (incomplete or corrupted on the way); nothing was installed",
    0x85: "the Pico rejected the Wi-Fi settings",
}
KEEPALIVE_S = 0.05
DATA_TIMEOUT_S = 0.5
DATA_RETRIES = 20
CONNECT_TIMEOUT_S = 15.0
RESTART_TIMEOUT_S = 45.0  # installing the image and booting again
# Over Bluetooth, longer: a firmware change wipes the Pico's Bluetooth pairing keys (the
# arduino-pico core keeps them inside the firmware image), so Windows' first reconnect fails
# to authenticate and it re-pairs by itself, which took 74 s in testing.
BT_RESTART_TIMEOUT_S = 180.0


class UpdateError(Exception):
    pass


def image_mac(key, nonce, image):
    return hmac.new(key, nonce + b"image" + struct.pack("<I", len(image)) + image, hashlib.sha256).digest()[:MAC_LEN]


def wifi_payload(ssid, password):
    """ssid[33] pass[64] reserved[1], as ota.h expects."""
    return struct.pack("<33s64sB", ssid.encode(), password.encode(), 0)


def wifi_encrypt(key, nonce, counter, plain):
    wifi_key = hmac.new(key, b"multiput wifi settings", hashlib.sha256).digest()
    stream = b"".join(hmac.new(wifi_key, nonce + struct.pack("<Q", counter) + bytes([block]), hashlib.sha256).digest()
                      for block in range(4))
    return bytes(p ^ s for p, s in zip(plain, stream))


class Transfer:
    """Talks to the Pico during an update: sends frames, waits for REPLY frames, and keeps
    sending signed "nothing pressed" reports so the link stays "in use" (the Pico keeps
    the other link paused, and the console just sees an idle controller)."""

    def __init__(self, link, session):
        self.link, self.session, self.rx, self.last_keepalive = link, session, b"", 0.0
        link.recv()  # drop anything still waiting, so an old reply can't pass for a new one

    def keepalive(self):
        now = time.monotonic()
        if now - self.last_keepalive >= KEEPALIVE_S:
            self.session.send(NEUTRAL_REPORT)
            self.last_keepalive = now

    def reply(self, timeout):
        """(code, value) of the next REPLY frame, or None after `timeout` seconds."""
        deadline = time.monotonic() + timeout
        self.keepalive()  # also when replies come back instantly (rate-limited to KEEPALIVE_S)
        while True:
            self.rx += self.link.recv()
            at = self.rx.find(REPLY)
            if at >= 0 and len(self.rx) >= at + REPLY_LEN:
                code, value = self.rx[at + 2], struct.unpack_from("<I", self.rx, at + 3)[0]
                self.rx = self.rx[at + REPLY_LEN:]
                return code, value
            if at < 0:
                self.rx = self.rx[-1:]  # keep a possible partial "M"
            if time.monotonic() > deadline:
                return None
            self.keepalive()
            time.sleep(0.0005)

    def expect(self, frame, want, timeout, what):
        self.link.send(frame)
        r = self.reply(timeout)
        if r is None:
            raise UpdateError(f"no answer from the Pico ({what})")
        code, value = r
        if code != want:
            raise UpdateError(ERRORS.get(code, f"unexpected reply {code:#x}") + f" ({what})")
        return value


def send_firmware(link, session, image, progress=None):
    """Send and install an image. Raises UpdateError; on any failure nothing is installed."""
    t = Transfer(link, session)
    t.expect(session.signed_frame(BEGIN, struct.pack("<I", len(image))), READY, 3.0, "starting the update")
    offset, retries = 0, 0
    while offset < len(image):
        chunk = image[offset:offset + CHUNK]
        link.send(DATA + struct.pack("<IH", offset, len(chunk)) + chunk)
        r = t.reply(DATA_TIMEOUT_S)
        if r is None:
            retries += 1
            if retries > DATA_RETRIES:
                raise UpdateError(f"the Pico stopped answering at {offset} of {len(image)} bytes")
            continue
        code, value = r
        if code != READY:
            raise UpdateError(ERRORS.get(code, f"unexpected reply {code:#x}"))
        offset, retries = min(value, len(image)), 0  # the Pico says what it needs next
        if progress:
            progress(offset, len(image))
    t.expect(session.signed_frame(COMMIT, image_mac(session.key, session.nonce, image)), INSTALLING, 5.0,
             "finishing the update")


def send_wifi(link, session, ssid, password):
    """Store a new Wi-Fi network on the Pico (it restarts to use it). Raises UpdateError."""
    plain = wifi_payload(ssid, password)
    frame = session.signed_frame(WIFI, build=lambda counter: wifi_encrypt(session.key, session.nonce, counter, plain))
    Transfer(link, session).expect(frame, WIFI_SAVED, 3.0, "changing the Wi-Fi network")


def connect(link, key, timeout=CONNECT_TIMEOUT_S):
    """A ready Session whose firmware version check has finished, or None."""
    session, deadline = Session(link, key), time.monotonic() + timeout
    while not (session.ready and session.version_asked == -1):
        session.poll(time.monotonic())
        if time.monotonic() > deadline:
            return None
        time.sleep(0.005)
    return session


def can_update_in_place(firmware):
    """False for firmware from before over-the-air updates (or that can't say)."""
    if firmware is None:
        return False
    v = parse(firmware)
    return v is None or v >= OTA_SINCE  # development builds are assumed to be current


def run_update(args, link, key, saved, store, cfg, firmware_dir, ask_wifi, ask=None):
    """The `multiput --update` flow. ask/ask_wifi are setup_wizard's prompts."""
    ask = ask or (lambda prompt, default=None: input(f"{prompt} [{default}]: ").strip() or default)
    print("multiput update\n")
    print(f"Looking for the Pico over {link.name}...")
    session = connect(link, key)
    if session is None:
        raise SystemExit(f"Couldn't reach the Pico over {link.name}. Is it powered (in the dock, or plugged in)? "
                         "To set it up over USB instead: multiput --setup")
    fw = session.firmware_version
    if not can_update_in_place(fw):
        raise SystemExit(f"This Pico's firmware ({fw or '0.1.0 or older'}) can't be updated in place. Run multiput "
                         "setup once over USB (Start menu: multiput setup); after that, multiput --update works "
                         "with the Pico where it is.")

    image_path = args.firmware or firmware_dir / "multiput.bin"
    if image_path.suffix.lower() != ".bin":
        raise SystemExit(f"--update needs the firmware's .bin image, not {image_path.name}.")
    if fw != VERSION or args.firmware:
        if ask(f"\nInstall firmware {VERSION if not args.firmware else image_path.name} (the Pico has {fw})? (Y/n)",
               "y").lower().startswith("y"):
            image = image_path.read_bytes()

            def progress(done, total):
                print(f"\r  Sending firmware: {done * 100 // total}%", end="", flush=True)

            try:
                send_firmware(link, session, image, progress)
            except UpdateError as e:
                print()
                raise SystemExit(f"Update failed: {e}. The Pico keeps its current firmware.")
            print("\nFirmware sent and verified. The Pico is installing it and restarting...")
            over_bt = hasattr(link, "ser")  # links.SerialLink
            if over_bt:
                print("Over Bluetooth, Windows can take a minute or two to reconnect after a firmware update:\n"
                      "the update resets the Pico's Bluetooth pairing, and Windows re-pairs by itself.")
            time.sleep(3)
            link.reconnect()
            session = connect(link, key, BT_RESTART_TIMEOUT_S if over_bt else RESTART_TIMEOUT_S)
            if session is None:
                raise SystemExit("The Pico was updated but hasn't reconnected yet. Start multiput as usual in a "
                                 "minute; if it still can't connect" + (" over Bluetooth, remove 'multiput' in "
                                 "Windows' Bluetooth settings and pair it again" if over_bt else
                                 " and the Pico's LED stays off, re-flash it over USB with multiput setup") + ".")
    else:
        print(f"\nFirmware is up to date ({fw}).")

    if args.ssid is not None or (ask("\nChange the Pico's Wi-Fi network? (y/N)", "n") or "n").lower().startswith("y"):
        packed, ssid = ask_wifi(args, key, saved.get("ssid"))
        password = packed[51:115].rstrip(b"\0").decode()  # firmware.pack_settings layout
        try:
            send_wifi(link, session, ssid, password)
        except UpdateError as e:
            raise SystemExit(f"Changing the Wi-Fi network failed: {e}. The Pico keeps its current network.")
        saved["ssid"], saved["pico_wifi"] = ssid, True
        store.save_settings(cfg, saved)
        print(f"The Pico is restarting on '{ssid}'.")
        if saved.get("link") == "wifi":
            print("multiput reaches it over Wi-Fi, so this PC must be on that network too "
                  "(or use Bluetooth: multiput --link bt).")
    print("\nUpdate done.")
    sys.stdout.flush()
