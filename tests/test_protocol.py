# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Arsmillis (https://github.com/Arsmillis/multiput)
"""End-to-end protocol test: the PC's real protocol.Session/sign_packet and links against the Pico's
protocol.h compiled for the desktop together with the core's own BearSSL sources.

Run: python3 tests/test_protocol.py   (needs g++/gcc and the arduino-pico core; see tests/pico_sim.py)
"""
import os
import pathlib
import struct
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pc"))
sys.path.insert(0, str(ROOT / "tests"))
import controller  # noqa: E402
import links  # noqa: E402
import pico_sim  # noqa: E402
import protocol  # noqa: E402
from pico_sim import FakeLink, ask, deliver  # noqa: E402

pico_sim.start()
ask("fwversion 0.3.0")  # a Pico that reports its version; tests of older firmware set "-"


# XInputGetStateEx writes 20 bytes; the buffer must hold them.
import ctypes  # noqa: E402
assert ctypes.sizeof(controller.XINPUT_STATE) == 20

key = os.urandom(32)
assert ask(f"init {key.hex()} 0 305419896 2271560481") == "ok"

link = FakeLink()
s = protocol.Session(link, key)
s.poll(0.0)
assert link.out == [b"MH"] and not s.ready
deliver(link)
s.poll(0.1)
assert s.ready and s.nonce == struct.pack("<II", 305419896, 2271560481)

g = controller.XINPUT_GAMEPAD()
g.wButtons = controller.X_A
r1 = controller.build_report(g)
s.send(r1)
assert deliver(link) == [r1]
print("signed accepted ok")

# Replay of a captured packet is rejected, and the Pico answers with SYNC.
link.out.append(protocol.sign_packet(key, s.nonce, s.counter, r1))
assert deliver(link) == [] and protocol.SYNC_MAGIC in link.inbox  # the Pico answers a replay with SYNC
s.poll(0.2)
# Wrong key / tampered report rejected.
link.out.append(protocol.sign_packet(os.urandom(32), s.nonce, s.counter + 5, r1))
assert deliver(link) == []
t = bytearray(protocol.sign_packet(key, s.nonce, s.counter + 5, r1))
t[10] ^= 1
link.out.append(bytes(t))
assert deliver(link) == []
# Unsigned rejected when not allowed.
link.out.append(b"MI" + r1)
assert deliver(link) == []
print("replay/forgery/unsigned rejected ok")

# Garbage + several packets in one stream chunk, and a frame split across chunks.
g.wButtons = controller.X_B
r2 = controller.build_report(g)
g.wButtons = 0
r3 = controller.build_report(g)
s.send(r2)
s.send(r3)
link.out.insert(0, b"\x00Mzgarbage")
assert deliver(link) == [r2, r3]
s.send(r1)
pkt = link.out.pop()
link.out.append(pkt[:11])
assert deliver(link) == []
link.out.append(pkt[11:])
assert deliver(link) == [r1]
print("stream framing ok")

# PC program restart: a new Session with counter 0 resyncs via HELLO and continues.
link2 = FakeLink()
s2 = protocol.Session(link2, key)
s2.poll(1.0)
deliver(link2)
s2.poll(1.1)
assert s2.ready and s2.counter == s.counter
s2.send(r2)
assert deliver(link2) == [r2]
# Pico reboot: new nonce; the next packet is rejected, SYNC carries the new nonce, then it works.
ask(f"init {key.hex()} 0 7 8")
s2.send(r3)
assert deliver(link2) == []
s2.poll(1.2)
assert s2.nonce == struct.pack("<II", 7, 8)
s2.send(r3)
assert deliver(link2) == [r3]
print("restart/reboot resync ok")

# Unsigned mode end to end (Pico set up with --allow-unsigned, PC run with --insecure).
ask(f"init {key.hex()} 1 1 2")
link3 = FakeLink()
s3 = protocol.Session(link3, None)
s3.poll(0)
assert s3.ready and link3.out == [b"MH"]  # liveness HELLO, even unsigned
link3.out.clear()
s3.send(r1)
assert deliver(link3) == [r1]
print("unsigned opt-in ok")

# Liveness: once connected, a HELLO goes out every HELLO_ALIVE_S and the Pico's SYNC keeps the link alive.
key = os.urandom(32)
ask(f"init {key.hex()} 0 11 12")
link4 = FakeLink()
s4 = protocol.Session(link4, key)
t = 100.0
s4.poll(t)
deliver(link4)
s4.poll(t + 0.1)
assert s4.ready and link4.out == [protocol.VERSION_MAGIC]  # asked once per Pico session
deliver(link4)
for i in range(1, 10):  # 9 s of healthy link: periodic HELLO answered, no reconnects
    t_i = t + i
    s4.poll(t_i)
    assert link4.out == [b"MH"], link4.out
    deliver(link4)
    s4.poll(t_i + 0.01)
assert link4.reconnects == 0 and s4.ready
# Pico goes silent (new IP / Bluetooth dropped): after LINK_TIMEOUT_S the link reconnects and sending stops.
t = t_i + 0.01
link4.out.clear()
for i in range(1, 6):
    s4.poll(t + i)
assert link4.reconnects == 1 and not s4.ready
link4.out.clear()
# The Pico rebooted meanwhile; it answers again once reachable and input resumes.
ask(f"init {key.hex()} 0 21 22")
s4.poll(t + 6)
deliver(link4)
s4.poll(t + 6.1)
assert s4.ready and s4.nonce == struct.pack("<II", 21, 22)
s4.send(r1)
assert deliver(link4) == [r1]
print("liveness + reconnect ok")

# UdpLink.reconnect picks up a new IP; SerialLink swallows I/O errors and reopens the port.
ips = iter(["10.0.0.5", "10.0.0.9", OSError])
def fake_resolve(host):
    ip = next(ips)
    if ip is OSError:
        raise OSError("not found")
    return ip
links.socket.gethostbyname = fake_resolve
u = links.UdpLink("multiput.local")
assert u.addr == ("10.0.0.5", links.PORT)
u.reconnect()
assert u.addr == ("10.0.0.9", links.PORT)
u.reconnect()  # lookup fails: keep the last known address
assert u.addr == ("10.0.0.9", links.PORT)

class FakeSerialPort:
    opened = 0
    def __init__(self, port, timeout, write_timeout):
        FakeSerialPort.opened += 1
        self.broken = False
    def write(self, d):
        if self.broken:
            raise OSError("link dropped")
    def read(self, n):
        if self.broken:
            raise OSError("link dropped")
        return b""
    def close(self):
        pass
sys.modules["serial"] = types.SimpleNamespace(Serial=FakeSerialPort)
sl = links.SerialLink("COM9")
sl.ser.broken = True
sl.send(b"x")
assert sl.recv() == b""
sl.reconnect()
assert FakeSerialPort.opened == 2 and not sl.ser.broken
print("link reconnect ok")

# A slow reconnect (opening a Bluetooth COM port blocks while Windows connects) must not
# be torn down on the next poll: the timeout counts from when reconnect() returned.
class SlowLink:
    """Reconnecting takes 6 s of (fake) time, like a Bluetooth COM port open."""
    def __init__(self):
        self.t, self.reconnects, self.out, self.inbox = 0.0, 0, [], b""
    def clock(self):
        return self.t
    def send(self, d):
        self.out.append(d)
    def recv(self):
        d, self.inbox = self.inbox, b""
        return d
    def reconnect(self):
        self.reconnects += 1
        self.t += 6.0
slow = SlowLink()
s5 = protocol.Session(slow, key, clock=slow.clock)
s5.poll(slow.t)                          # never connected: starts the timeout
slow.t += protocol.LINK_TIMEOUT_S
s5.poll(slow.t)                          # 4 s of silence -> reconnect (which takes 6 s)
assert slow.reconnects == 1
slow.t += 0.5
s5.poll(slow.t)                          # 0.5 s after the reconnect finished: give the Pico time
assert slow.reconnects == 1, "a slow but successful reconnect was torn down immediately"
ask(f"init {key.hex()} 0 31 32")
slow.out.clear()
slow.out.append(protocol.HELLO)
deliver(slow)                            # the Pico answers on the new connection...
slow.t += 0.5
s5.poll(slow.t)
assert s5.ready and slow.reconnects == 1  # ...and the session resumes
print("slow reconnect ok")

# Bluetooth COM port detection: pick the outgoing port whose hwid has the "multiput" device's address.
PORTS = [("COM4", r"BTHENUM\{00001101-0000-1000-8000-00805F9B34FB}_LOCALMFG&0000\B&1076B237&0&000000000000_00000000"),
         ("COM5", r"BTHENUM\{00001101-0000-1000-8000-00805F9B34FB}_LOCALMFG&0046\B&1076B237&0&28CDC10A6091_C00000000"),
         ("COM9", r"BTHENUM\{00001101-0000-1000-8000-00805F9B34FB}_LOCALMFG&0046\B&1076B237&0&408E2C719169_C00000000")]
PAIRED = {"28cdc10a6091": "multiput", "408e2c719169": "Xbox Wireless Controller", "7cc18062cbf6": "AirPods Pro"}
assert links.match_bt_port(PAIRED, PORTS) == "COM5"           # not the incoming COM4, not another device's port
assert links.match_bt_port({"408e2c719169": "Xbox Wireless Controller"}, PORTS) is None  # Pico not paired
assert links.match_bt_port(PAIRED, PORTS[:1]) is None         # paired, but its port isn't there (yet)
assert links.match_bt_port({}, []) is None
assert links.find_bt_port() is None                          # off Windows: no registry, just None
print("bluetooth port detection ok")

# Firmware version check: asked once per Pico session, answered by firmware >= 0.2.0.
import contextlib  # noqa: E402
import io  # noqa: E402
import version  # noqa: E402

def session_with(fw, r1, r2):
    ask(f"fwversion {fw}")
    ask(f"init {key.hex()} 0 {r1} {r2}")
    link, out = FakeLink(), io.StringIO()
    sess = protocol.Session(link, key)
    with contextlib.redirect_stdout(out):
        sess.poll(200.0)
        deliver(link)      # HELLO -> SYNC
        sess.poll(200.1)   # session starts; VERSION requested
        deliver(link)      # VERSION -> reply (if the firmware answers)
        sess.poll(200.2)
    return sess, link, out

sess, link, out = session_with(version.VERSION, 41, 42)
assert sess.firmware_version == version.VERSION and "(up to date)" in out.getvalue()
sess, link, out = session_with("0.0.1", 43, 44)
assert "is older than this multiput" in out.getvalue()
# Firmware 0.1.0 never answers: give up after VERSION_TIMEOUT_S, say so once.
sess, link, out = session_with("-", 45, 46)
with contextlib.redirect_stdout(out):
    sess.poll(200.1 + protocol.VERSION_TIMEOUT_S)
    sess.poll(205.0)
assert sess.firmware_version is None and out.getvalue().count("0.1.0 or older") == 1
# A reconnect to the same Pico doesn't ask again; a restarted Pico (new nonce) does.
asked = lambda: sum(1 for d in link.out if d == protocol.VERSION_MAGIC)
link.out.clear()
with contextlib.redirect_stdout(io.StringIO()):
    sess.nonce = None                     # what a link timeout does
    sess.poll(206.0); deliver(link); sess.poll(206.1)
    assert asked() == 0
    ask(f"init {key.hex()} 0 47 48")      # Pico rebooted (maybe re-flashed)
    ask("fwversion 9.9.9")
    sess.send(b"\0" * 8); deliver(link)   # rejected -> SYNC with the new nonce
    sess.poll(206.2)
    assert asked() == 1
    deliver(link); sess.poll(206.3)
assert sess.firmware_version == "9.9.9"
# Over Bluetooth the reply can arrive split up and next to a SYNC; an unasked reply is ignored.
reply = b"MV\x050.2.0"
s6 = protocol.Session(FakeLink(), key)
s6.version_asked, s6.version_nonce, s6.nonce = 300.0, b"x" * 8, b"x" * 8
with contextlib.redirect_stdout(io.StringIO()):
    s6.link.inbox = reply[:4]; s6.poll(300.1)
    assert s6.firmware_version is None
    s6.link.inbox = reply[4:] + protocol.SYNC_MAGIC + b"x" * 8 + bytes(8); s6.poll(300.2)
assert s6.firmware_version == "0.2.0"
s7 = protocol.Session(FakeLink(), key)
s7.link.inbox = reply
s7.poll(0.0)
assert s7.firmware_version is None
# The first VERSION reply can be lost (the Pico rate-limits replies, and UDP drops packets):
# the PC asks again instead of concluding the firmware is too old to answer.
ask("fwversion 0.3.0")
ask(f"init {key.hex()} 0 49 50")
dropped = {"n": 0}
def lose_first_version(reply):
    if reply[:2] == protocol.VERSION_MAGIC and dropped["n"] == 0:
        dropped["n"] += 1
        return True
    return False
live = pico_sim.LiveLink(lose_reply=lose_first_version)
s8 = protocol.Session(live, key)
out = io.StringIO()
with contextlib.redirect_stdout(out):
    t = 400.0
    while s8.version_asked != -1 and t < 410:
        s8.poll(t)
        t += 0.1
assert dropped["n"] == 1 and s8.firmware_version == "0.3.0", (dropped, s8.firmware_version, out.getvalue())
assert "0.1.0 or older" not in out.getvalue() and "Pico firmware 0.3.0" in out.getvalue()
print("version reply lost once ok")
print("firmware version check ok")
print("ALL OK")
