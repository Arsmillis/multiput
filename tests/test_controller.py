# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Arsmillis (https://github.com/Arsmillis/multiput)
"""Button mapping, --remap, and the pause combo.

Run: python3 tests/test_controller.py
"""
import contextlib
import io
import json
import pathlib
import struct
import sys
import tempfile
import types

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pc"))
import controller as c  # noqa: E402
import multiput  # noqa: E402
import settings_store as store  # noqa: E402


def pad(buttons=0, lt=0, rt=0):
    g = c.XINPUT_GAMEPAD()
    g.wButtons, g.bLeftTrigger, g.bRightTrigger = buttons, lt, rt
    return g


def switch_buttons(report):
    return struct.unpack_from("<H", report)[0]


# Default mapping is by label, and matches the original hard-coded mapping.
default = c.button_map({})
assert switch_buttons(c.build_report(pad(c.X_A))) == c.S_A
assert switch_buttons(c.build_report(pad(c.X_B | c.X_GUIDE))) == c.S_B | c.S_HOME
assert switch_buttons(c.build_report(pad(lt=255, rt=255))) == c.S_ZL | c.S_ZR
assert switch_buttons(c.build_report(pad(lt=c.TRIGGER_THRESHOLD))) == 0  # at threshold: not pressed
assert c.build_report(pad()) [:3] == c.NEUTRAL_REPORT[:3]
print("default mapping ok")

# Remapping: swap, disable, reach Capture, case-insensitive; unknown names are errors.
m = c.button_map({"a": "b", "B": "A", "VIEW": "capture", "LT": "NONE"})
assert switch_buttons(c.build_report(pad(c.X_A), m)) == c.S_B
assert switch_buttons(c.build_report(pad(c.X_B), m)) == c.S_A
assert switch_buttons(c.build_report(pad(c.X_BACK), m)) == c.S_CAPTURE
assert switch_buttons(c.build_report(pad(lt=255), m)) == 0
for bad in [{"Q": "A"}, {"A": "Q"}, {"UP": "A"}]:
    try:
        c.button_map(bad)
        raise AssertionError(f"accepted {bad}")
    except ValueError:
        pass
print("remapping ok")

# Pause: holding the combo for 1 s toggles once per hold; other buttons don't count.
t = c.PauseToggle()  # default combo: View + Menu
combo = set(c.DEFAULT_PAUSE[0])
assert not t.update(combo, 0.0) and not t.update(combo, 0.9) and not t.paused
assert t.update(combo | {"A"}, 1.0) and t.paused         # extra buttons held is fine
assert not t.update(combo, 5.0) and t.paused             # still the same hold: no second toggle
assert not t.update({"VIEW"}, 5.1)                       # released (one button is enough)
assert not t.update(combo, 6.0) and t.update(combo, 7.0) and not t.paused  # new hold: resume
assert not t.update({"VIEW"}, 0.0) and not t.update({"VIEW"}, 10.0)      # half the combo never toggles
# While the combo is held, its buttons are kept off the Switch; the rest still go through.
r = c.build_report(pad(c.X_BACK | c.X_START | c.X_A), default, t.held_buttons({"VIEW", "MENU", "A"}))
assert switch_buttons(r) == c.S_A
# Custom combos: a single button, or none at all (pausing off).
t = c.PauseToggle(c.parse_pause("xbox"))
assert not t.update({"XBOX"}, 0.0) and t.update({"XBOX"}, 1.0) and t.paused
t = c.PauseToggle(c.parse_pause("NONE"))
assert not t.held(set(c.XBOX_BUTTONS)) and not t.update(set(c.XBOX_BUTTONS), 0.0) and not t.update(set(c.XBOX_BUTTONS), 9.0)
assert c.parse_pause("LB + RB") == (("LB", "RB"),) and c.parse_pause("A+A") == (("A",),)
# Several alternative combos: any one of them toggles; duplicates collapse.
assert c.parse_pause("view+menu, xbox,XBOX") == (("VIEW", "MENU"), ("XBOX",))
t = c.PauseToggle(c.parse_pause("VIEW+MENU,XBOX"))
assert not t.update({"XBOX"}, 0.0) and t.update({"XBOX"}, 1.0) and t.paused          # by the second combo
assert not t.update(set(), 1.1)
assert not t.update({"VIEW", "MENU"}, 2.0) and t.update({"VIEW", "MENU"}, 3.0) and not t.paused  # by the first
assert not t.update({"VIEW"}, 4.0) and not t.update({"VIEW", "XBOX"}, 4.5)            # switching combos mid-hold
assert not t.update({"VIEW", "MENU"}, 5.0)                                              # = one continuous hold
assert t.update({"VIEW", "MENU"}, 5.6)                                                  # 1 s after it began
assert t.held_buttons({"XBOX", "A"}) == {"XBOX"} and t.held_buttons({"VIEW", "A"}) == set()
assert t.held_buttons({"VIEW", "MENU", "XBOX"}) == {"VIEW", "MENU", "XBOX"}
# Settings from before alternatives existed (one combo as a flat list) still load.
assert c.pause_from_settings(["XBOX"]) == (("XBOX",),) and c.pause_from_settings([]) == ()
assert c.pause_from_settings([["LB", "RB"], ["XBOX"]]) == (("LB", "RB"), ("XBOX",))
for bad in ["", "+", "LB+JUMP", "UP", "XBOX,", ",XBOX", "XBOX,,LB"]:
    try:
        c.parse_pause(bad)
        raise AssertionError(f"accepted {bad!r}")
    except ValueError:
        pass
assert c.describe_pause((("VIEW", "MENU"),)) == "hold VIEW + MENU for 1 s" and c.describe_pause(()) == "off"
assert c.describe_pause((("VIEW", "MENU"), ("XBOX",))) == "hold VIEW + MENU or XBOX for 1 s"
print("pause toggle ok")

# multiput --remap saves only real changes, merges with existing settings, and `reset` clears them.
cfg = pathlib.Path(tempfile.mkdtemp())
store.save_settings(cfg, {"link": "wifi", "host": "multiput.local"})
def run_remap(*items):
    with contextlib.redirect_stdout(io.StringIO()) as out:
        multiput.remap(types.SimpleNamespace(remap=list(items)), cfg, store.load_settings(cfg))
    return json.loads((cfg / "settings.json").read_text()), out.getvalue()
saved, out = run_remap("a=b", "B=A", "X=X")
assert saved == {"link": "wifi", "host": "multiput.local", "buttons": {"A": "B", "B": "A"}}, saved
assert "A       -> B   (changed)" in out and "X       -> X\n" in out and "PAUSE   -> hold VIEW + MENU for 1 s\n" in out
saved, out = run_remap("RB=ZR", "PAUSE=lb+rb,xbox")
assert saved["buttons"] == {"A": "B", "B": "A", "RB": "ZR"} and saved["pause"] == [["LB", "RB"], ["XBOX"]]
assert "PAUSE   -> hold LB + RB or XBOX for 1 s   (changed)" in out
saved, _ = run_remap("PAUSE=VIEW+MENU")  # back to the default: not stored
assert "pause" not in saved
saved, _ = run_remap("PAUSE=NONE")
assert saved["pause"] == []
assert multiput.pause_combos(saved) == ()
# An old settings.json with a single flat combo is still shown and used correctly.
store.save_settings(cfg, {"link": "wifi", "host": "multiput.local", "pause": ["XBOX"]})
saved = store.load_settings(cfg)
with contextlib.redirect_stdout(io.StringIO()) as out:
    multiput.print_mapping(saved)
assert multiput.pause_combos(saved) == (("XBOX",),) and "PAUSE   -> hold XBOX for 1 s   (changed)" in out.getvalue()
saved, _ = run_remap("reset")
assert saved == {"link": "wifi", "host": "multiput.local"}
before = (cfg / "settings.json").read_text()
for bad in [("A",), ("A=JUMP",), ("B=A", "PAUSE=JUMP")]:  # nothing is saved if any item is invalid
    try:
        run_remap(*bad)
        raise AssertionError(f"accepted {bad}")
    except ValueError:
        pass
assert (cfg / "settings.json").read_text() == before
# --remap before any setup creates settings.json, and multiput still knows setup hasn't run.
cfg = pathlib.Path(tempfile.mkdtemp())
saved, _ = run_remap("A=B")
assert saved == {"buttons": {"A": "B"}}
print("--remap ok")

# Interactive editor (multiput --remap with no items, and the offer at the end of setup):
# invalid lines are explained and ignored, valid ones are saved, Enter finishes.
cfg = pathlib.Path(tempfile.mkdtemp())
lines = iter(["A=JUMP", "A=B PAUSE=XBOX", ""])
multiput.input = lambda prompt: next(lines)
with contextlib.redirect_stdout(io.StringIO()) as out:
    multiput.edit_mapping(cfg, {})
assert "unknown Switch button 'JUMP'" in out.getvalue()
assert json.loads((cfg / "settings.json").read_text()) == {"buttons": {"A": "B"}, "pause": [["XBOX"]]}
del multiput.input
print("interactive editor ok")

# M key while running: the Switch is released first, the new mapping and pause combo apply
# immediately, the edit gap isn't treated as a lost Pico, and pause can't get stuck on.
class FakeSession:
    def __init__(self):
        self.sent, self.excused = [], None
    def send(self, report):
        self.sent.append(report)
    def excuse_silence(self, now):
        self.excused = now
import hotkey  # noqa: E402

class FakeHotkey:  # stands in for the Windows shortcut (not available on Linux)
    def __init__(self, spec):
        self.spec, self.error, self.active, self.stopped = (hotkey.parse(spec)[2] if spec else ""), None, bool(spec), False
    def fired(self):
        return False
    def stop(self):
        self.stopped = True
real_hotkey = hotkey.Hotkey
hotkey.Hotkey = FakeHotkey

def edit(saved, previous, *lines):
    it = iter([*lines, ""])
    multiput.input = lambda prompt: next(it)
    sess = FakeSession()
    with contextlib.redirect_stdout(io.StringIO()):
        new = multiput.edit_while_running(cfg, saved, previous, sess)
    del multiput.input
    return new, sess

cfg = pathlib.Path(tempfile.mkdtemp())
saved = {"link": "wifi", "host": "multiput.local"}
controls = multiput.Controls(saved)
controls.pause.paused = True
new, sess = edit(saved, controls, "A=B PAUSE=NONE PAUSE_KEY=NONE")
assert sess.sent == [c.NEUTRAL_REPORT] and sess.excused is not None
assert switch_buttons(c.build_report(pad(c.X_A), new.mapping)) == c.S_B
assert new.pause.combos == () and not new.pause.paused   # no way left to resume: not stuck paused
assert controls.hotkey.stopped                           # the old shortcut was released
assert json.loads((cfg / "settings.json").read_text())["buttons"] == {"A": "B"}
new.pause.paused = True
kept, _ = edit(saved, new, "PAUSE=XBOX")
assert kept.pause.paused and kept.pause.combos == (frozenset({"XBOX"}),)   # resumable with the new combo
kept2, _ = edit(saved, kept, "PAUSE=NONE PAUSE_KEY=CTRL+ALT+P")
assert kept2.pause.paused and kept2.hotkey.active          # no combo, but the keyboard shortcut can resume
same, _ = edit(saved, kept2, "B=A")
assert same.hotkey is kept2.hotkey                          # unchanged shortcut: kept registered, not re-created
class QuietLink:
    reconnects = 0
    def send(self, d): pass
    def recv(self): return b""
    def reconnect(self): QuietLink.reconnects += 1
import protocol  # noqa: E402
real = protocol.Session(QuietLink(), None)
real.poll(100.0)
real.excuse_silence(160.0)   # a minute in the editor
real.poll(160.1)
assert QuietLink.reconnects == 0
real.poll(160.1 + protocol.LINK_TIMEOUT_S)   # genuinely quiet afterwards: still detected
assert QuietLink.reconnects == 1
print("M-key editing ok")

# Sticky buttons: each press toggles the button on the Switch; turbo: on/off at TURBO_HZ while held.
m = c.ButtonModes(sticky=["A", "LT"], turbo=["B"])
assert m.apply({"A"}, 0.0) == {"A"}            # press: on
assert m.apply(set(), 0.01) == {"A"}           # released physically: still on
assert m.apply({"A"}, 0.02) == set()           # press again: off
assert m.apply({"A"}, 0.03) == set()           # still held: no second toggle
assert m.apply({"X"}, 0.04) == {"X"}           # other buttons pass through
period = 1 / c.TURBO_HZ
assert "B" in m.apply({"B"}, 1.0) and "B" not in m.apply({"B"}, 1.0 + period * 0.6)
assert "B" in m.apply({"B"}, 1.0 + period) and m.apply(set(), 1.0 + period * 1.1) == set()
m.apply({"LT"}, 2.0)
m.reset()                                      # controller disconnected: everything released
assert m.apply(set(), 2.1) == set()
r = c.build_report(pad(c.X_X), c.button_map({}), (), {"A"})   # `down` overrides the physical buttons
assert switch_buttons(r) == c.S_A
print("sticky and turbo ok")

# Pause hold time: 0 = a single tap; any value toggles once per press/hold; the keyboard toggles too.
t = c.PauseToggle((("XBOX",),), hold=0)
assert t.update({"XBOX"}, 0.0) and t.paused and not t.update({"XBOX"}, 5.0)
assert not t.update(set(), 5.1) and t.update({"XBOX"}, 5.2) and not t.paused
t = c.PauseToggle(hold=0.5)
assert not t.update({"VIEW", "MENU"}, 0.0) and t.update({"VIEW", "MENU"}, 0.5)
t.toggle()
assert not t.paused
assert c.describe_pause((("XBOX",),), 0) == "tap XBOX" and c.describe_pause((("XBOX",),), 2) == "hold XBOX for 2 s"
assert c.parse_hold("0") == 0 and c.parse_hold("0.25") == 0.25
for bad in ["-1", "11", "soon", ""]:
    try:
        c.parse_hold(bad)
        raise AssertionError(f"accepted PAUSE_HOLD={bad!r}")
    except ValueError:
        pass
assert c.parse_button_list("a, lt+A", "STICKY") == ["A", "LT"] and c.parse_button_list("none", "TURBO") == []
for bad in ["", "JUMP", "A,UP"]:
    try:
        c.parse_button_list(bad, "STICKY")
        raise AssertionError(f"accepted STICKY={bad!r}")
    except ValueError:
        pass
print("pause hold ok")

# Keyboard shortcut specs: modifiers + key; letters/digits/Space need Ctrl, Alt or Win.
assert hotkey.parse("ctrl + alt + p") == (0x2 | 0x1, ord("P"), "CTRL+ALT+P")
assert hotkey.parse("SHIFT+F12") == (0x4, 0x70 + 11, "SHIFT+F12") and hotkey.parse("pause")[1] == 0x13
assert hotkey.parse("NONE") is None and hotkey.parse("WIN+1")[1] == ord("1")
for bad in ["P", "SHIFT+A", "CTRL+X+P", "CTRL+F25", "CTRL+", "SPACE", "HYPER+P"]:
    try:
        hotkey.parse(bad)
        raise AssertionError(f"accepted PAUSE_KEY={bad!r}")
    except ValueError:
        pass
assert real_hotkey("").active is False                         # no shortcut: nothing registered
print("keyboard shortcut parsing ok")

# The new settings in --remap / the editor: saved only when changed; reset clears them.
cfg = pathlib.Path(tempfile.mkdtemp())
store.save_settings(cfg, {"link": "wifi"})
saved, out = run_remap("PAUSE_HOLD=0", "PAUSE_KEY=shift+f12", "BEEP=off", "STICKY=A,LT", "TURBO=B")
assert saved == {"link": "wifi", "pause_hold": 0.0, "pause_key": "SHIFT+F12", "beep": False,
                 "sticky": ["A", "LT"], "turbo": ["B"]}, saved
assert "PAUSE   -> tap VIEW + MENU" in out and "PAUSE_KEY  -> SHIFT+F12" in out and "BEEP       -> OFF" in out
assert "STICKY     -> A, LT" in out and "TURBO      -> B" in out
saved, _ = run_remap("PAUSE_HOLD=1", "BEEP=ON", "PAUSE_KEY=CTRL+ALT+P", "STICKY=NONE")  # back to defaults
assert saved == {"link": "wifi", "turbo": ["B"]}, saved
saved, _ = run_remap("PAUSE_KEY=NONE")
assert saved["pause_key"] == ""
before = (cfg / "settings.json").read_text()
for bad in [("STICKY=B",), ("BEEP=LOUD",), ("PAUSE_KEY=P",), ("TURBO=A", "STICKY=A")]:
    try:
        run_remap(*bad)
        raise AssertionError(f"accepted {bad}")
    except ValueError:
        pass
assert (cfg / "settings.json").read_text() == before         # nothing saved from a rejected change
saved, _ = run_remap("reset")
assert saved == {"link": "wifi"}
print("new settings ok")

# Picking the controller: the first connected XInput slot, re-picked if it disconnects;
# empty slots are scanned at most once a second (slow on some machines); --controller N pins one.
class Slots:
    def __init__(self):
        self.connected, self.calls = set(), []
    def __call__(self, slot, ptr):
        self.calls.append(slot)
        return 0 if slot in self.connected else 1167
pads, state = Slots(), c.XINPUT_STATE()
auto = c.ControllerSlot(pads)
assert not auto.read(state, 0.0) and pads.calls == [0, 1, 2, 3]   # nothing connected: one scan
pads.calls.clear()
assert not auto.read(state, 0.5) and pads.calls == []              # no rescan within SCAN_S
pads.connected = {2}
assert not auto.read(state, 0.9)                                   # still waiting for the next scan
assert auto.read(state, 1.0) and auto.current == 2                 # found in slot 2
pads.calls.clear()
assert auto.read(state, 1.001) and pads.calls == [2]               # then only that slot is read
pads.connected = {1}                                               # it disconnects; another appears
assert auto.read(state, 2.5) and auto.current == 1                 # picked again at once
pinned = c.ControllerSlot(pads, fixed=3)
pads.calls.clear()
assert not pinned.read(state, 5.0) and pads.calls == [3] and pinned.current == 3   # never looks elsewhere
print("controller auto-pick ok")
print("ALL OK")
