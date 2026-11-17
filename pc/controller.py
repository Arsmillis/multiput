# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Arsmillis (https://github.com/Arsmillis/multiput)
"""Reading the Xbox controller (XInput) and turning its state into a Switch report.

The report is the 8-byte HID input report of a HORIPAD S, which the Pico passes
to the Switch unchanged.
"""

import ctypes
import struct

TRIGGER_THRESHOLD = 30  # 0-255; analog trigger -> digital ZL/ZR

# XInput button bits
X_UP, X_DOWN, X_LEFT, X_RIGHT = 0x0001, 0x0002, 0x0004, 0x0008
X_START, X_BACK, X_LTHUMB, X_RTHUMB = 0x0010, 0x0020, 0x0040, 0x0080
X_LB, X_RB, X_GUIDE = 0x0100, 0x0200, 0x0400
X_A, X_B, X_X, X_Y = 0x1000, 0x2000, 0x4000, 0x8000

# Switch (HORIPAD) button bits
S_Y, S_B, S_A, S_X = 1 << 0, 1 << 1, 1 << 2, 1 << 3
S_L, S_R, S_ZL, S_ZR = 1 << 4, 1 << 5, 1 << 6, 1 << 7
S_MINUS, S_PLUS, S_LCLICK, S_RCLICK, S_HOME = 1 << 8, 1 << 9, 1 << 10, 1 << 11, 1 << 12
S_CAPTURE = 1 << 13

# Button names, as used by `multiput --remap XBOX=SWITCH`. The d-pad and sticks aren't remappable.
XBOX_BUTTONS = {
    "A": X_A, "B": X_B, "X": X_X, "Y": X_Y, "LB": X_LB, "RB": X_RB,
    "LT": None, "RT": None,  # analog triggers: pressed past TRIGGER_THRESHOLD
    "VIEW": X_BACK, "MENU": X_START, "LS": X_LTHUMB, "RS": X_RTHUMB, "XBOX": X_GUIDE,
}
SWITCH_BUTTONS = {
    "A": S_A, "B": S_B, "X": S_X, "Y": S_Y, "L": S_L, "R": S_R, "ZL": S_ZL, "ZR": S_ZR,
    "MINUS": S_MINUS, "PLUS": S_PLUS, "LSTICK": S_LCLICK, "RSTICK": S_RCLICK,
    "HOME": S_HOME, "CAPTURE": S_CAPTURE, "NONE": 0,
}
# By label: pressing "A" on the Xbox pad presses "A" on the Switch.
# (To map by position instead: multiput --remap A=B B=A X=Y Y=X)
DEFAULT_MAP = {
    "A": "A", "B": "B", "X": "X", "Y": "Y", "LB": "L", "RB": "R", "LT": "ZL", "RT": "ZR",
    "VIEW": "MINUS", "MENU": "PLUS", "LS": "LSTICK", "RS": "RSTICK", "XBOX": "HOME",
}

# Hold any one of these combos for PAUSE_HOLD_S to stop (or resume) sending input to the
# Switch. Changeable with `multiput --remap PAUSE=VIEW+MENU,XBOX` (alternatives separated
# by commas, buttons of a combo joined by '+'; NONE turns pausing off).
DEFAULT_PAUSE = (("VIEW", "MENU"),)
PAUSE_HOLD_S = 1.0  # default; `PAUSE_HOLD=0.5` changes it, `PAUSE_HOLD=0` makes it a single tap
MAX_PAUSE_HOLD_S = 10.0
TURBO_HZ = 10       # TURBO buttons: presses per second while held

# (up, right, down, left) -> HID hat value; 8 = centered
HAT = {
    (1, 0, 0, 0): 0, (1, 1, 0, 0): 1, (0, 1, 0, 0): 2, (0, 1, 1, 0): 3,
    (0, 0, 1, 0): 4, (0, 0, 1, 1): 5, (0, 0, 0, 1): 6, (1, 0, 0, 1): 7,
}

class XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [("wButtons", ctypes.c_ushort), ("bLeftTrigger", ctypes.c_ubyte),
                ("bRightTrigger", ctypes.c_ubyte), ("sThumbLX", ctypes.c_short),
                ("sThumbLY", ctypes.c_short), ("sThumbRX", ctypes.c_short),
                ("sThumbRY", ctypes.c_short)]

class XINPUT_STATE(ctypes.Structure):
    # dwPaddingReserved: XInputGetStateEx (ordinal 100) writes 4 bytes more than the
    # documented XINPUT_STATE. Plain XInputGetState just leaves it untouched.
    _fields_ = [("dwPacketNumber", ctypes.c_uint), ("Gamepad", XINPUT_GAMEPAD),
                ("dwPaddingReserved", ctypes.c_uint)]

def load_xinput():
    """Return a get_state(index, state_ptr) function, preferring the variant that reports Guide."""
    try:
        dll = ctypes.WinDLL("xinput1_4")
        try:
            return dll[100]  # XInputGetStateEx (undocumented ordinal): includes the Guide button
        except AttributeError:
            return dll.XInputGetState
    except OSError:
        return ctypes.WinDLL("xinput9_1_0").XInputGetState

def axis(v, invert=False):
    """XInput -32768..32767 -> HID 0..255 (128 = center)."""
    b = (v + 32768) >> 8
    return 255 - b if invert else b

def button_names(overrides):
    """DEFAULT_MAP with the user's overrides applied: {xbox name: switch name}.
    Names are case-insensitive; unknown ones raise ValueError."""
    names = dict(DEFAULT_MAP)
    for xbox, switch in overrides.items():
        xbox, switch = xbox.upper(), switch.upper()
        if xbox not in XBOX_BUTTONS:
            raise ValueError(f"unknown Xbox button {xbox!r}; use one of: {' '.join(XBOX_BUTTONS)}")
        if switch not in SWITCH_BUTTONS:
            raise ValueError(f"unknown Switch button {switch!r}; use one of: {' '.join(SWITCH_BUTTONS)}")
        names[xbox] = switch
    return names


def button_map(overrides):
    """{xbox name: switch button bit} for build_report."""
    return {xbox: SWITCH_BUTTONS[switch] for xbox, switch in button_names(overrides).items()}


def pressed(g):
    """Names of the Xbox buttons currently held (d-pad not included)."""
    down = {name for name, bit in XBOX_BUTTONS.items() if bit and g.wButtons & bit}
    if g.bLeftTrigger > TRIGGER_THRESHOLD:
        down.add("LT")
    if g.bRightTrigger > TRIGGER_THRESHOLD:
        down.add("RT")
    return down


def parse_pause(text):
    """"VIEW+MENU,XBOX" -> (("VIEW", "MENU"), ("XBOX",)); "NONE" -> () (pausing off).
    Raises ValueError."""
    if text.strip().upper() == "NONE":
        return ()
    combos = []
    for alternative in text.split(","):
        names = tuple(dict.fromkeys(n.strip().upper() for n in alternative.split("+") if n.strip()))
        if not names or any(n not in XBOX_BUTTONS for n in names):
            raise ValueError(f"PAUSE needs combos of Xbox button names joined by '+', separated by ',' "
                             f"(e.g. VIEW+MENU,XBOX), or NONE; use: {' '.join(XBOX_BUTTONS)}")
        if names not in combos:
            combos.append(names)
    return tuple(combos)


def pause_from_settings(value):
    """The saved "pause" value -> combos. Also reads the older single-combo form
    (["VIEW", "MENU"]) written before alternatives existed."""
    if value and all(isinstance(v, str) for v in value):
        return (tuple(value),)
    return tuple(tuple(c) for c in value)


def describe_pause(combos, hold=PAUSE_HOLD_S):
    if not combos:
        return "off"
    buttons = " or ".join(" + ".join(c) for c in combos)
    return f"tap {buttons}" if hold == 0 else f"hold {buttons} for {hold:g} s"


def parse_hold(text):
    """PAUSE_HOLD value: seconds, 0 (a single tap) up to MAX_PAUSE_HOLD_S. Raises ValueError."""
    try:
        hold = float(text)
    except ValueError:
        hold = -1
    if not 0 <= hold <= MAX_PAUSE_HOLD_S:
        raise ValueError(f"PAUSE_HOLD needs seconds from 0 (a single tap) to {MAX_PAUSE_HOLD_S:g}, got {text!r}")
    return hold


def parse_button_list(text, what):
    """STICKY/TURBO value: Xbox buttons separated by ',' (or '+'), or NONE. Raises ValueError."""
    if text.strip().upper() == "NONE":
        return []
    names = list(dict.fromkeys(n.strip().upper() for n in text.replace("+", ",").split(",") if n.strip()))
    if not names or any(n not in XBOX_BUTTONS for n in names):
        raise ValueError(f"{what} needs Xbox button names separated by ',' (e.g. {what}=A,LT) or NONE; "
                         f"use: {' '.join(XBOX_BUTTONS)}")
    return names


class ButtonModes:
    """Sticky and turbo buttons, applied to the held Xbox buttons before mapping.
    Sticky: each press toggles the button on or off on the Switch (for players who can't
    hold a button). Turbo: while held, the Switch sees TURBO_HZ presses per second."""

    def __init__(self, sticky=(), turbo=()):
        self.sticky, self.turbo = frozenset(sticky), frozenset(turbo)
        self.latched, self.prev = set(), set()

    def reset(self):
        """Release everything (e.g. the controller disconnected)."""
        self.latched.clear()
        self.prev = set()

    def apply(self, down, now):
        """The buttons the Switch should see, given the physically held ones."""
        for name in (down - self.prev) & self.sticky:  # newly pressed sticky buttons toggle
            self.latched ^= {name}
        self.prev = set(down)
        out = (down - self.sticky - self.turbo) | self.latched
        if int(now * TURBO_HZ * 2) % 2 == 0:  # first half of each turbo period: pressed
            out |= down & self.turbo
        return out


class PauseToggle:
    """Flips `paused` each time any of `combos` is held for `hold` seconds (once per hold;
    hold 0 = on the press itself). No combos: never toggles by buttons."""

    def __init__(self, combos=DEFAULT_PAUSE, hold=PAUSE_HOLD_S):
        self.combos = tuple(frozenset(c) for c in combos if c)
        self.hold = hold
        self.paused, self.since, self.fired = False, None, False

    def toggle(self):
        """Pause or resume from outside the controller (the keyboard shortcut)."""
        self.paused = not self.paused

    def held(self, down):
        return any(c <= down for c in self.combos)

    def held_buttons(self, down):
        """Buttons of the combos currently held; kept off the Switch while held."""
        return frozenset().union(*(c for c in self.combos if c <= down))

    def update(self, down, now):
        """Feed the held buttons every poll; returns True when `paused` just changed."""
        if not self.held(down):
            self.since, self.fired = None, False
            return False
        if self.since is None:
            self.since = now
        if not self.fired and now - self.since >= self.hold:
            self.fired, self.paused = True, not self.paused
            return True
        return False


class ControllerSlot:
    """Which XInput slot (0-3) to read: a fixed one (--controller N), or the first connected
    controller, picked again if it disconnects. While nothing is connected, slots are scanned
    at most every SCAN_S: polling empty slots is slow on some Windows machines."""
    SCAN_S = 1.0

    def __init__(self, get_state, fixed=None):
        self.get_state, self.fixed = get_state, fixed
        self.current, self.last_scan = fixed, None

    def read(self, state, now):
        """Fill `state` from the controller; returns False if none is connected."""
        if self.fixed is not None:
            return self.get_state(self.fixed, ctypes.byref(state)) == 0
        if self.current is not None and self.get_state(self.current, ctypes.byref(state)) == 0:
            return True
        self.current = None
        if self.last_scan is not None and now - self.last_scan < self.SCAN_S:
            return False
        self.last_scan = now
        for slot in range(4):
            if self.get_state(slot, ctypes.byref(state)) == 0:
                self.current = slot
                return True
        return False


NEUTRAL_REPORT = struct.pack("<HBBBBBB", 0, 8, 128, 128, 128, 128, 0)  # nothing pressed


def build_report(g, mapping=None, ignore=(), down=None):
    """XINPUT_GAMEPAD -> 8-byte HORIPAD HID report. mapping comes from button_map();
    buttons named in `ignore` are left out (the pause combo while it's held). `down`
    overrides which buttons count as held (ButtonModes' sticky/turbo result)."""
    mapping = mapping or button_map({})
    buttons = 0
    for name in (pressed(g) if down is None else set(down)) - set(ignore):
        buttons |= mapping[name]
    w = g.wButtons
    hat = HAT.get((bool(w & X_UP), bool(w & X_RIGHT), bool(w & X_DOWN), bool(w & X_LEFT)), 8)
    # HID Y axis grows downward; XInput Y grows upward.
    return struct.pack("<HBBBBBB", buttons, hat,
                       axis(g.sThumbLX), axis(g.sThumbLY, True),
                       axis(g.sThumbRX), axis(g.sThumbRY, True), 0)
