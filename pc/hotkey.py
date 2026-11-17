# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Arsmillis (https://github.com/Arsmillis/multiput)
"""A system-wide keyboard shortcut (Windows RegisterHotKey) that works while a game has
focus. multiput uses it to pause or resume sending input to the console.

Spec format: modifiers and a key joined by '+', e.g. "CTRL+ALT+P", "SHIFT+F12", "PAUSE".
"""

import ctypes
import sys
import threading

DEFAULT = "CTRL+ALT+P"
MODIFIERS = {"CTRL": 0x2, "ALT": 0x1, "SHIFT": 0x4, "WIN": 0x8}
MOD_NOREPEAT = 0x4000  # one event per press, not auto-repeat while held
NAMED_KEYS = {"PAUSE": 0x13, "SCROLLLOCK": 0x91, "INSERT": 0x2D, "HOME": 0x24, "END": 0x23,
              "PAGEUP": 0x21, "PAGEDOWN": 0x22, "SPACE": 0x20}
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012


def parse(spec):
    """"CTRL+ALT+P" -> (modifier flags, virtual-key code, normalised spec); NONE -> None.
    Letters, digits and Space need Ctrl, Alt or Win, so the shortcut can't take over
    ordinary typing. Raises ValueError."""
    spec = spec.strip().upper().replace(" ", "")
    if spec == "NONE":
        return None
    *mods, key = spec.split("+")
    unknown = [m for m in mods if m not in MODIFIERS]
    if unknown or not key:
        raise ValueError(f"PAUSE_KEY needs modifiers ({'/'.join(MODIFIERS)}) and a key joined by '+', "
                         f"e.g. CTRL+ALT+P, or NONE; got {spec!r}")
    if len(key) == 1 and key.isalnum():
        vk = ord(key)
    elif key.startswith("F") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x70 + int(key[1:]) - 1
    elif key in NAMED_KEYS:
        vk = NAMED_KEYS[key]
    else:
        raise ValueError(f"PAUSE_KEY: unknown key {key!r}; use a letter, a digit, F1-F24 or "
                         f"{', '.join(NAMED_KEYS)}")
    if (len(key) == 1 or key == "SPACE") and not {"CTRL", "ALT", "WIN"} & set(mods):
        raise ValueError(f"PAUSE_KEY {spec}: add CTRL, ALT or WIN, so the shortcut doesn't take over normal typing")
    flags = 0
    for m in mods:
        flags |= MODIFIERS[m]
    return flags, vk, "+".join(list(dict.fromkeys(mods)) + [key])


class Hotkey:
    """Registers the shortcut on its own thread (Windows delivers hotkey messages to the
    registering thread's message queue). fired() reports presses since the last call."""

    def __init__(self, spec):
        self.spec, self.error = spec, None
        self.presses, self.seen, self.tid = 0, 0, None
        parsed = parse(spec) if spec else None
        if parsed is None:
            return
        if sys.platform != "win32":
            self.error = "keyboard shortcuts need Windows"
            return
        self.flags, self.vk, self.spec = parsed
        ready = threading.Event()
        threading.Thread(target=self._run, args=(ready,), daemon=True).start()
        ready.wait(2)

    def _run(self, ready):
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.tid = ctypes.WinDLL("kernel32").GetCurrentThreadId()
        if not user32.RegisterHotKey(None, 1, self.flags | MOD_NOREPEAT, self.vk):
            self.error = f"{self.spec} is already used by another program"
            ready.set()
            return
        ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                self.presses += 1
        user32.UnregisterHotKey(None, 1)

    @property
    def active(self):
        return self.tid is not None and self.error is None

    def fired(self):
        """True if the shortcut was pressed since the last call."""
        if self.presses != self.seen:
            self.seen = self.presses
            return True
        return False

    def stop(self):
        if self.tid is not None and sys.platform == "win32":
            ctypes.WinDLL("user32").PostThreadMessageW(self.tid, WM_QUIT, 0, 0)
            self.tid = None
