# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Arsmillis (https://github.com/Arsmillis/multiput)
"""PC side of the wire protocol; the Pico side and the full description are in
pico/multiput_pico/protocol.h.

Session asks the Pico for a session (HELLO -> SYNC), signs every report, and keeps
checking that the Pico still answers, reconnecting the link when it goes quiet.
"""

import hashlib
import hmac
import struct
import time

from version import firmware_message

HELLO = b"MH"
SYNC_MAGIC, SYNC_LEN = b"MN", 18   # + nonce[8] + last_counter[8]
SIGNED_MAGIC = b"MS"               # + counter[8] + report[8] + mac[16]
UNSIGNED_MAGIC = b"MI"             # + report[8]
VERSION_MAGIC = b"MV"              # PC -> Pico: request; Pico -> PC: + length[1] + version
KEY_LEN, MAC_LEN = 32, 16

HELLO_RETRY_S = 0.5     # how often to ask the Pico for a session until it answers
HELLO_ALIVE_S = 1.0     # once connected: a HELLO this often; the Pico's SYNC reply shows it's still there
VERSION_RETRY_S = 0.5    # re-ask this often: a reply can be lost (UDP, or the Pico's reply rate limit)
VERSION_TIMEOUT_S = 2.5  # no VERSION reply to any request by then: firmware 0.1.0 or older (it can't answer)
LINK_TIMEOUT_S = 4.0    # no SYNC for this long -> reconnect the link (new IP, dropped Bluetooth)

def sign_packet(key, nonce, counter, report):
    body = SIGNED_MAGIC + struct.pack("<Q", counter) + report
    return body + hmac.new(key, nonce + body, hashlib.sha256).digest()[:MAC_LEN]

class Session:
    """Signs reports for the Pico and keeps its nonce and counter in sync."""

    def __init__(self, link, key, clock=time.monotonic):
        self.clock = clock  # only to measure how long link.reconnect() blocks
        self.link, self.key = link, key  # key None = unsigned (--insecure)
        self.nonce, self.counter = None, 0
        self.rx, self.last_hello = b"", None
        self.last_heard = None  # when the Pico last sent a SYNC
        self.firmware_version = None  # reported by the Pico; None until it answers (or never, for 0.1.0)
        self.version_asked = None     # when VERSION was requested (-1: answered or given up)
        self.version_nonce = None     # the Pico session it was requested for
        self.version_sent = None      # when the last request went out (they're repeated until answered)
        self.lost = False

    @property
    def ready(self):
        return self.key is None or self.nonce is not None

    def poll(self, now):
        if self.last_heard is None:
            self.last_heard = now
        self.rx += self.link.recv()
        while len(self.rx) >= 2:
            if self.rx[:2] == VERSION_MAGIC:
                if len(self.rx) < 3 or len(self.rx) < 3 + self.rx[2]:
                    break
                version = self.rx[3:3 + self.rx[2]].decode(errors="replace")
                self.rx = self.rx[3 + self.rx[2]:]
                if self.version_asked is not None and self.firmware_version is None:
                    self.firmware_version = version
                    self.version_asked = -1  # answered
                    print(firmware_message(version))
                continue
            if self.rx[:2] != SYNC_MAGIC:
                self.rx = self.rx[1:]
                continue
            if len(self.rx) < SYNC_LEN:
                break
            nonce, (last,) = self.rx[2:10], struct.unpack_from("<Q", self.rx, 10)
            self.rx = self.rx[SYNC_LEN:]
            self.last_heard = now
            if self.lost:
                print("Reconnected to the Pico.")
                self.lost = False
            if nonce != self.nonce:
                if self.nonce is not None:
                    print("Pico restarted; new session.")
                elif self.counter == 0:
                    print("Pico session started.")
                if nonce != self.version_nonce:
                    # a new Pico session: first connection, or it restarted (maybe re-flashed)
                    self.link.send(VERSION_MAGIC)
                    self.firmware_version, self.version_asked, self.version_nonce = None, now, nonce
                    self.version_sent = now
                self.nonce, self.counter = nonce, last
            else:
                self.counter = max(self.counter, last)

        if self.version_asked not in (None, -1):
            if now - self.version_asked >= VERSION_TIMEOUT_S:
                self.version_asked = -1  # no answer to any request: firmware too old to answer
                print(firmware_message(None))
            elif self.version_sent is None or now - self.version_sent >= VERSION_RETRY_S:
                self.link.send(VERSION_MAGIC)
                self.version_sent = now
        if now - self.last_heard >= LINK_TIMEOUT_S:
            if self.nonce is not None and not self.lost:  # only after having been connected
                print("Lost contact with the Pico; reconnecting... (inputs on the Switch are released meanwhile)")
                self.lost = True
            started = self.clock()
            self.link.reconnect()
            # Reconnecting can block for seconds (opening a Bluetooth COM port does, while
            # Windows connects). Count the next timeout from when it finished; otherwise a
            # slow but successful reconnect is torn down on the very next poll, before the
            # Pico can answer, and the link never comes back.
            now += self.clock() - started
            self.nonce = None  # stop sending until the Pico answers again
            self.last_heard = now  # next attempt after another timeout
        interval = HELLO_ALIVE_S if self.nonce is not None else HELLO_RETRY_S
        if self.last_hello is None or now - self.last_hello >= interval:
            self.link.send(HELLO)
            self.last_hello = now

    def excuse_silence(self, now):
        """multiput deliberately stopped polling (e.g. while the mapping editor was open):
        don't count that gap as the Pico going quiet."""
        self.last_heard = now

    def signed_frame(self, magic, payload=b"", build=None):
        """A signed frame: magic || counter || payload || mac, using the next counter.
        build(counter) can make the payload from the counter (for ota.h's WIFI encryption)."""
        self.counter += 1
        if build:
            payload = build(self.counter)
        body = magic + struct.pack("<Q", self.counter) + payload
        return body + hmac.new(self.key, self.nonce + body, hashlib.sha256).digest()[:MAC_LEN]

    def send(self, report):
        if self.key is None:
            self.link.send(UNSIGNED_MAGIC + report)
            return
        self.counter += 1
        self.link.send(sign_packet(self.key, self.nonce, self.counter, report))
