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

HELLO = b"MH"
SYNC_MAGIC, SYNC_LEN = b"MN", 18   # + nonce[8] + last_counter[8]
SIGNED_MAGIC = b"MS"               # + counter[8] + report[8] + mac[16]
UNSIGNED_MAGIC = b"MI"             # + report[8]
KEY_LEN, MAC_LEN = 32, 16

HELLO_RETRY_S = 0.5     # how often to ask the Pico for a session until it answers
HELLO_ALIVE_S = 1.0     # once connected: a HELLO this often; the Pico's SYNC reply shows it's still there
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
        self.lost = False

    @property
    def ready(self):
        return self.key is None or self.nonce is not None

    def poll(self, now):
        if self.last_heard is None:
            self.last_heard = now
        self.rx += self.link.recv()
        while len(self.rx) >= 2:
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
                self.nonce, self.counter = nonce, last
            else:
                self.counter = max(self.counter, last)

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

    def send(self, report):
        if self.key is None:
            self.link.send(UNSIGNED_MAGIC + report)
            return
        self.counter += 1
        self.link.send(sign_packet(self.key, self.nonce, self.counter, report))
