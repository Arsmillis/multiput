# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Arsmillis (https://github.com/Arsmillis/multiput)
"""The mirroring loop (multiput.run_loop) as the tray app runs it: on a thread, with a stop
event and a command queue, against the simulated Pico and a fake controller.

Run: python3 tests/test_loop.py   (needs g++/gcc and the arduino-pico core; see tests/pico_sim.py)
"""
import os
import pathlib
import queue
import sys
import tempfile
import threading
import time
import types

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pc"))
sys.path.insert(0, str(ROOT / "tests"))
import controller as c  # noqa: E402
import events  # noqa: E402
import links  # noqa: E402
import multiput  # noqa: E402
import pico_sim  # noqa: E402
import protocol  # noqa: E402
import settings_store as store  # noqa: E402
from pico_sim import LiveLink, ask  # noqa: E402

pico_sim.start()
key = os.urandom(32)
ask(f"init {key.hex()} 0 1 2")
ask("fwversion " + multiput.VERSION)

heard = []
events.set_handler(lambda text, kind, subject: heard.append((kind, text)))

pad_buttons = {"value": c.X_A}
def fake_xinput(slot, state_ptr):  # one controller, in slot 1, holding pad_buttons
    if slot != 1:
        return 1167
    st = state_ptr._obj
    st.dwPacketNumber += 1
    st.Gamepad.wButtons = pad_buttons["value"]
    return 0

link = LiveLink()
multiput.open_link = lambda args, cfg, saved, stop=None: link
cfg = pathlib.Path(tempfile.mkdtemp())
saved = {"link": "wifi", "pause_key": ""}
store.save_settings(cfg, saved)
args = types.SimpleNamespace(controller=None)
stop, commands = threading.Event(), queue.Queue()
worker = threading.Thread(target=multiput.run_loop, args=(args, cfg, saved, key),
                          kwargs=dict(stop=stop, commands=commands, controllers=c.Controllers(c.ControllerSlot(fake_xinput))), daemon=True)
worker.start()

def wait_for(check, what, timeout=5):
    deadline = time.monotonic() + timeout
    while not check():
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out waiting for {what}; heard: {heard}")
        time.sleep(0.01)

kinds = lambda: [k for k, _ in heard]
reports = lambda: [f[10:18] for f in link.out if f[:2] == protocol.SIGNED_MAGIC]
wait_for(lambda: events.PICO_UP in kinds() and events.CONTROLLER_UP in kinds(), "the Pico and controller")
assert any("slot 1" in t for k, t in heard if k == events.CONTROLLER_UP)
wait_for(lambda: any(c.struct.unpack_from("<H", r)[0] == c.S_A for r in reports()), "A reaching the Pico")
print("loop sends input ok")

commands.put("pause")                                  # the tray's Pause menu item
wait_for(lambda: events.PAUSED in kinds(), "paused")
link.out.clear()
time.sleep(0.15)                                       # paused: only "nothing pressed" goes out (keepalive)
assert reports() and all(r == c.NEUTRAL_REPORT for r in reports())
commands.put("pause")
wait_for(lambda: events.RESUMED in kinds(), "resumed")
print("pause command ok")

stop.set()                                             # the tray needs the link (update, quit)
worker.join(2)
assert not worker.is_alive() and getattr(link, "closed", False)
assert reports()[-1] == c.NEUTRAL_REPORT               # left nothing pressed on the console
print("stop ok")

# A stop also abandons a connection that is still being retried (Pico not reachable yet).
stopper = threading.Event()
links.socket = types.SimpleNamespace(gethostbyname=lambda h: (_ for _ in ()).throw(OSError("not found")),
                                     socket=links.socket.socket, AF_INET=links.socket.AF_INET,
                                     SOCK_DGRAM=links.socket.SOCK_DGRAM)
threading.Timer(0.2, stopper.set).start()
t0 = time.monotonic()
try:
    links.UdpLink("multiput.local", stop=stopper)
    raise AssertionError("should have been abandoned")
except links.Stopped:
    assert time.monotonic() - t0 < 1.5
print("abandoned connecting ok")
events.set_handler(None)
print("ALL OK")
