# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Arsmillis (https://github.com/Arsmillis/multiput)
"""multiput --perf-test measuring logic, against a fake Pico.

Run: python3 tests/test_perf.py
"""
import os
import pathlib
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pc"))
import perf  # noqa: E402
import protocol  # noqa: E402
from controller import NEUTRAL_REPORT  # noqa: E402


class FakePico:
    """Answers HELLO with SYNC (optionally skipping some), records signed packets."""
    def __init__(self, answer=lambda n: True, nonce=b"\x01" * 8):
        self.answer, self.nonce, self.hellos, self.signed, self.inbox = answer, nonce, 0, [], b""

    def send(self, data):
        if data == protocol.HELLO:
            self.hellos += 1
            if self.answer(self.hellos):
                self.inbox += protocol.SYNC_MAGIC + self.nonce + struct.pack("<Q", 0)
        else:
            self.signed.append(data)

    def recv(self):
        d, self.inbox = self.inbox, b""
        return d

    def reconnect(self):
        pass


key = os.urandom(32)
fast = dict(probes=5, interval=0.02, timeout=0.05)

pico = FakePico()
rtts, lost = perf.measure(pico, key, **fast)
assert len(rtts) == 5 and lost == 0 and all(r >= 0 for r in rtts)
# Keepalives keep the link "in use": signed "nothing pressed" reports, like multiput sends.
assert pico.signed and all(p[:2] == protocol.SIGNED_MAGIC and p[10:18] == NEUTRAL_REPORT for p in pico.signed)
print("all answered ok")

pico = FakePico(answer=lambda n: n == 1 or n % 2 == 0)  # handshake answered, then every other probe
rtts, lost = perf.measure(pico, key, **fast)
assert len(rtts) + lost == 5 and lost == 2, (len(rtts), lost)
print("lost probes counted ok")

perf.HANDSHAKE_TIMEOUT_S = 0.2
assert perf.measure(FakePico(answer=lambda n: False), key, **fast) is None
print("no answer ok")

class Restarting(FakePico):
    def send(self, data):
        if data == protocol.HELLO and self.hellos == 2:
            self.nonce = b"\x02" * 8  # rebooted after the handshake
        super().send(data)
try:
    perf.measure(Restarting(), key, **fast)
    raise AssertionError("a restarted Pico should stop the test")
except SystemExit as e:
    assert "restarted" in str(e)
print("restart detected ok")

row = perf.summarize([5.0, 3.0, 25.0, 4.0], 1)
assert row["replies"] == "4/5" and row["lost"] == "1" and row["min"] == "3.0" and row["max"] == "25.0"
assert row["median"] == "4.5" and row["over20"] == "1" and row["oneway"] == "~2.2"
assert perf.summarize([], 3) == {"replies": "0/3", "lost": "3"}
text = perf.table([{"link": "Wi-Fi", **row}, {"link": "Bluetooth", "replies": "no answer"}])
lines = text.splitlines()
assert lines[0].startswith("Link") and "Wi-Fi" in lines[2] and "no answer" in lines[3] and lines[3].rstrip().endswith("-")
print("summary table ok")
print("ALL OK")
