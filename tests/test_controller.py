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
cfg = pathlib.Path(tempfile.mkdtemp())
saved = {"link": "wifi", "host": "multiput.local"}
paused = c.PauseToggle()
paused.paused = True
sess = FakeSession()
lines = iter(["A=B PAUSE=NONE", ""])
multiput.input = lambda prompt: next(lines)
with contextlib.redirect_stdout(io.StringIO()):
    new_map, new_pause = multiput.edit_while_running(cfg, saved, paused, sess)
del multiput.input
assert sess.sent == [c.NEUTRAL_REPORT] and sess.excused is not None
assert switch_buttons(c.build_report(pad(c.X_A), new_map)) == c.S_B
assert new_pause.combos == () and not new_pause.paused   # pausing turned off: not stuck paused
assert json.loads((cfg / "settings.json").read_text())["buttons"] == {"A": "B"}
lines = iter(["PAUSE=XBOX", ""])
multiput.input = lambda prompt: next(lines)
still = c.PauseToggle()
still.paused = True
with contextlib.redirect_stdout(io.StringIO()):
    _, kept = multiput.edit_while_running(cfg, saved, still, FakeSession())
del multiput.input
assert kept.paused and kept.combos == (frozenset({"XBOX"}),)   # stays paused, resumable with the new combo
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
print("ALL OK")
