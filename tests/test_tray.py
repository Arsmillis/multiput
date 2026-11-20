# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Arsmillis (https://github.com/Arsmillis/multiput)
"""The tray app's status logic (tray.TrayState): events -> icon colour, tooltip, notifications.
The Win32 icon itself needs Windows; this part runs anywhere.

Run: python3 tests/test_tray.py
"""
import itertools
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pc"))
import events  # noqa: E402
import tray  # noqa: E402

s = tray.TrayState("Wi-Fi")
assert s.badge() == ("W", tray.AMBER) and "Looking for the Pico over Wi-Fi" in s.tooltip()
# Routine start-up: no notifications.
assert s.on_event("Waiting for the Pico...", events.INFO) is None
assert s.on_event("Pico session started.", events.PICO_UP) is None
assert s.on_event("Pico firmware 0.5.0 (up to date).", events.FIRMWARE_OK) is None
assert s.badge() == ("W", tray.AMBER) and "Waiting for a controller" in s.tooltip()
assert s.on_event("Controller connected: DualSense Wireless Controller.", events.CONTROLLER_UP,
                  "DualSense Wireless Controller") is None
# The tooltip: multiput, the status, and the controller in use, on separate lines.
assert s.badge() == ("C", tray.GREEN)
assert s.tooltip() == "multiput\nSending to the console over Wi-Fi\nDualSense Wireless Controller", s.tooltip()
# The menu shows the same status, one item per line (menu items can't break lines), without "multiput".
app = object.__new__(tray.TrayApp)
app.state, app.busy = s, None
app.store, app.cfg = types.SimpleNamespace(load_settings=lambda cfg: {"link": "wifi"}), None
header = list(itertools.takewhile(lambda item: item is not None, app.menu()))
assert header == [(0, "Sending to the console over Wi-Fi", tray.MF_GRAYED), (0, "DualSense Wireless Controller", tray.MF_GRAYED)], header
print("start-up ok")

# Things worth a notification.
title, text, warning = s.on_event("Paused: ...", events.PAUSED)
assert title == "Paused" and not warning and s.badge() == ("P", tray.GREY) and s.tooltip().split("\n")[1:] == ["Paused: the console gets no input", "DualSense Wireless Controller"]
assert s.on_event("Resumed: ...", events.RESUMED)[0] == "Resumed" and s.badge() == ("C", tray.GREEN)
title, _, warning = s.on_event("Lost contact with the Pico; ...", events.PICO_LOST)
assert title == "Lost contact with the Pico" and warning and s.badge() == ("W", tray.AMBER) and "Reconnecting" in s.tooltip()
assert s.on_event("Reconnected to the Pico.", events.PICO_UP)[0] == "Reconnected" and s.badge() == ("C", tray.GREEN)
assert s.on_event("Controller not connected; waiting...", events.CONTROLLER_LOST)[0] == "Controller disconnected"
assert s.on_event("Controller not connected; waiting...", events.CONTROLLER_LOST) is None  # only once
assert s.on_event("Pico firmware 0.4.0 is older ...", events.FIRMWARE_UPDATE)[0] == "Pico firmware"
assert s.on_event("Keyboard shortcut not available: ...", events.WARNING)[2] is True
print("notifications ok")

s.fail("Couldn't find the Pico's Bluetooth COM port.")
assert s.badge() == ("F", tray.RED) and s.tooltip().startswith("multiput\nStopped: Couldn't find")   # failed: red F
assert len(tray.TrayState("x" * 200).tooltip()) <= 127                       # Windows' tooltip limit
print("errors and tooltip limit ok")

# From source, the tray opens console tasks with python.exe (not the windowless pythonw.exe).
real = sys.executable
sys.executable = "C:/Python314/pythonw.exe"  # forward slashes: split into folder and name on any OS
cmd = tray.console_command("--update")
sys.executable = real
assert cmd[0].lower().endswith("python.exe") and cmd[1].endswith("multiput.py") and cmd[2] == "--update"
print("console command ok")

# Through TrayApp.on_event (what the icon is actually told): the icon must show the state
# *after* the event. A 0.5.0 pre-release read the state before applying the event, so
# pause showed green and resume showed grey (one step behind).
class FakeIcon:
    def __init__(self):
        self.shown = []
    def refresh(self, *args):
        self.shown.append(args)
app = object.__new__(tray.TrayApp)
app.state, app.icon = tray.TrayState("Wi-Fi"), FakeIcon()
for text, kind in [("Pico session started.", events.PICO_UP), ("Controller connected: Xbox-compatible controller (slot 0).", events.CONTROLLER_UP),
                   ("Paused: ...", events.PAUSED), ("Resumed: ...", events.RESUMED)]:
    app.on_event(text, kind)
shown = [args[0] for args in app.icon.shown]
assert shown[1:] == [("C", tray.GREEN), ("P", tray.GREY), ("C", tray.GREEN)], shown
print("icon follows events ok")

busy = tray.TrayState("Wi-Fi")
busy.busy = True                                  # a console task has the Pico
assert busy.badge() == ("W", tray.AMBER) and busy.tooltip() == "multiput\nBusy in another window"
# The icon's rounded square: solid inside, clear in the corners, smoothed at the edge.
assert tray.rounded_square(8, 8, 16) == 1.0 and tray.rounded_square(0, 0, 16) < 0.3
assert any(0 < tray.rounded_square(x, y, 16) < 1 for y in range(16) for x in range(16))  # soft edge pixels
print("badges ok")

# After a console task that had the Pico (update, performance test, status), the icon must
# leave "busy" and follow the restarted loop again. 0.5.0 never cleared busy, so it stayed on W.
import threading
app = object.__new__(tray.TrayApp)
app.state, app.icon, app.busy = tray.TrayState("Wi-Fi"), FakeIcon(), None
app.commands = __import__("queue").Queue()
app.stop_worker = lambda: None
restarted = threading.Event()
app.start_worker = restarted.set
console_done = threading.Event()
def fake_console(cmd, creationflags=0):
    assert app.state.badge() == ("W", tray.AMBER) and app.state.busy  # busy while the task runs
    console_done.set()
tray.subprocess.run, tray.subprocess.CREATE_NEW_CONSOLE = fake_console, 0
app.run_console(["--update"])
assert restarted.wait(2) and console_done.is_set()
assert not app.state.busy and app.busy is None
for text, kind in [("Pico session started.", events.PICO_UP), ("Controller connected: Xbox-compatible controller (slot 0).", events.CONTROLLER_UP)]:
    app.on_event(text, kind)
assert app.icon.shown[-1][0] == ("C", tray.GREEN), app.icon.shown
print("busy cleared after console task ok")

# Button mapping also stops the loop (the Switch mustn't get the buttons pressed to remap
# them), and a pause on before the task is put back when the loop restarts.
stopped, restarted = threading.Event(), threading.Event()
app.stop_worker, app.start_worker = stopped.set, restarted.set
app.state.paused = True
tray.subprocess.run = lambda cmd, creationflags=0: None
app.run_console(["--remap"])
assert stopped.is_set() and restarted.wait(2)
assert app.commands.get_nowait() == "pause"
print("mapping editor stops the loop ok")
print("ALL OK")
