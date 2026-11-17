# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Arsmillis (https://github.com/Arsmillis/multiput)
"""The Pico's protocol code (protocol.h + ota.h) built for the desktop and driven over
stdin (tests/protocol_sim.cpp), plus fake links to talk to it. Shared by the tests.

Needs g++/gcc and the arduino-pico core (set RP2040_CORE if it isn't under ~/.arduino15).
"""
import glob
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pc"))

CORE = pathlib.Path(os.environ.get("RP2040_CORE") or
                    sorted(glob.glob(os.path.expanduser("~/.arduino15/packages/rp2040/hardware/rp2040/*")))[-1])
BS = CORE / "tools/libbearssl/bearssl"
_sim = None


def start():
    """Build the simulator (once per test run) and start it."""
    global _sim
    exe = pathlib.Path(tempfile.mkdtemp()) / "protocol_sim"
    objs = []
    for src in ["mac/hmac.c", "hash/sha2small.c", "codec/dec32be.c", "codec/enc32be.c"]:
        obj = exe.parent / (pathlib.Path(src).stem + ".o")
        subprocess.run(["gcc", "-c", "-O1", f"-I{BS}/inc", f"-I{BS}/src", str(BS / "src" / src), "-o", str(obj)],
                       check=True)
        objs.append(str(obj))
    subprocess.run(["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", f"-I{CORE}/include",
                    f"-I{ROOT}/pico/multiput_pico", str(ROOT / "tests/protocol_sim.cpp"), *objs, "-o", str(exe)],
                   check=True)
    _sim = subprocess.Popen([str(exe)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)


def ask(line):
    _sim.stdin.write(line + "\n")
    _sim.stdin.flush()
    return _sim.stdout.readline().strip()


REPLY_TOKENS = ("S:", "V:", "R:", "G:")  # SYNC, VERSION, update REPLY and STATUS frames go back to the PC


def feed(data):
    """Feed bytes to the simulated Pico; returns (replies for the PC, accepted reports)."""
    res = ask("feed " + data.hex()) if data else "-"
    replies = b"".join(bytes.fromhex(t[2:]) for t in res.split() if t.startswith(REPLY_TOKENS))
    accepted = [bytes.fromhex(t[2:]) for t in res.split() if t.startswith("A:")]
    return replies, accepted


class FakeLink:
    """Collects what the PC sends; deliver() hands it to the Pico in one go."""

    def __init__(self):
        self.out, self.inbox = [], b""
        self.reconnects = 0

    def reconnect(self):
        self.reconnects += 1

    def send(self, d):
        self.out.append(d)

    def recv(self):
        d, self.inbox = self.inbox, b""
        return d

    def close(self):
        self.closed = True


def deliver(link):
    """PC -> Pico as one byte stream (exercises Bluetooth framing); Pico replies go back to the PC."""
    data = b"".join(link.out)
    link.out.clear()
    replies, accepted = feed(data)
    link.inbox += replies
    return accepted


class LiveLink(FakeLink):
    """Every send reaches the Pico at once and its replies come straight back, so PC code
    that waits for answers (the updater) can run unchanged. lose_sent(frame) / lose_reply(bytes)
    return True to drop a message, simulating a lossy link."""

    def __init__(self, lose_sent=None, lose_reply=None):
        super().__init__()
        self.lose_sent = lose_sent or (lambda d: False)
        self.lose_reply = lose_reply or (lambda r: False)
        self.name = "the simulated Pico"

    def send(self, d):
        self.out.append(d)
        if self.lose_sent(d):
            return
        replies, _ = feed(d)
        if replies and not self.lose_reply(replies):
            self.inbox += replies
