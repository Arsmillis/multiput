# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Arsmillis (https://github.com/Arsmillis/multiput)
"""Controllers XInput can't see (PlayStation, Switch Pro, 8BitDo and other generic pads),
read through SDL's game controller API.

SDL presents every controller in the Xbox layout, so this module fills the same
XINPUT_GAMEPAD the XInput path does, and mapping, pause and the report work unchanged.
Xbox controllers are skipped here: XInput reads them.

Optional: needs pysdl2 and pysdl2-dll (both bundled in the installer). Without them,
only Xbox controllers work.
"""

import warnings

import events
from controller import (X_A, X_B, X_BACK, X_DOWN, X_GUIDE, X_LB, X_LEFT, X_LTHUMB, X_RB, X_RIGHT, X_RTHUMB,
                        X_START, X_UP, X_X, X_Y)

_sdl = None  # the initialised sdl2 module, False if unavailable (loaded once per process)


def load():
    """The sdl2 module, initialised for reading controllers in the background; None if
    SDL isn't installed or doesn't start."""
    global _sdl
    if _sdl is None:
        _sdl = False
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")  # pysdl2-dll announces which SDL it uses
                import sdl2
        except (ImportError, RuntimeError):      # pysdl2 raises RuntimeError without an SDL library
            return None
        hints = {
            sdl2.SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS: b"1",  # read while a game has focus
            # By label, like DEFAULT_MAP for Xbox pads: "A" on a Switch Pro Controller presses
            # A on the Switch (SDL would otherwise report its buttons by position).
            sdl2.SDL_HINT_GAMECONTROLLER_USE_BUTTON_LABELS: b"1",
            # Don't switch PlayStation pads into their enhanced report mode: games on the PC
            # that read the basic reports would stop seeing input.
            sdl2.SDL_HINT_JOYSTICK_HIDAPI_PS4_RUMBLE: b"0",
            sdl2.SDL_HINT_JOYSTICK_HIDAPI_PS5_RUMBLE: b"0",
        }
        for name, value in hints.items():
            sdl2.SDL_SetHint(name, value)
        if sdl2.SDL_Init(sdl2.SDL_INIT_GAMECONTROLLER) != 0:
            return None
        # No event queue: state is read directly after SDL_GameControllerUpdate().
        sdl2.SDL_GameControllerEventState(sdl2.SDL_IGNORE)
        sdl2.SDL_JoystickEventState(sdl2.SDL_IGNORE)
        _sdl = sdl2
    return _sdl or None


class SdlPads:
    """The first connected non-Xbox controller, picked again if it disconnects. Same
    read(state, now) interface as controller.ControllerSlot."""
    SCAN_S = 1.0

    def __init__(self, sdl):
        self.sdl, self.pad, self.name, self.last_scan, self.reported = sdl, None, None, None, set()
        self.skip = {sdl.SDL_CONTROLLER_TYPE_XBOX360, sdl.SDL_CONTROLLER_TYPE_XBOXONE}  # XInput reads these
        self.buttons = [
            (sdl.SDL_CONTROLLER_BUTTON_A, X_A), (sdl.SDL_CONTROLLER_BUTTON_B, X_B),
            (sdl.SDL_CONTROLLER_BUTTON_X, X_X), (sdl.SDL_CONTROLLER_BUTTON_Y, X_Y),
            (sdl.SDL_CONTROLLER_BUTTON_BACK, X_BACK), (sdl.SDL_CONTROLLER_BUTTON_GUIDE, X_GUIDE),
            (sdl.SDL_CONTROLLER_BUTTON_START, X_START), (sdl.SDL_CONTROLLER_BUTTON_LEFTSTICK, X_LTHUMB),
            (sdl.SDL_CONTROLLER_BUTTON_RIGHTSTICK, X_RTHUMB), (sdl.SDL_CONTROLLER_BUTTON_LEFTSHOULDER, X_LB),
            (sdl.SDL_CONTROLLER_BUTTON_RIGHTSHOULDER, X_RB), (sdl.SDL_CONTROLLER_BUTTON_DPAD_UP, X_UP),
            (sdl.SDL_CONTROLLER_BUTTON_DPAD_DOWN, X_DOWN), (sdl.SDL_CONTROLLER_BUTTON_DPAD_LEFT, X_LEFT),
            (sdl.SDL_CONTROLLER_BUTTON_DPAD_RIGHT, X_RIGHT),
        ]

    def read(self, state, now):
        """Fill `state` (XINPUT_STATE) from the controller; returns False if none is connected."""
        sdl = self.sdl
        sdl.SDL_GameControllerUpdate()  # also notices controllers being plugged in or removed
        if self.pad is not None and not sdl.SDL_GameControllerGetAttached(self.pad):
            sdl.SDL_GameControllerClose(self.pad)
            self.pad = self.name = None
        if self.pad is None:
            if self.last_scan is not None and now - self.last_scan < self.SCAN_S:
                return False
            self.last_scan = now
            self.open_first()
            if self.pad is None:
                return False
        self.fill(state.Gamepad)
        return True

    def open_first(self):
        sdl = self.sdl
        for i in range(sdl.SDL_NumJoysticks()):
            if not sdl.SDL_IsGameController(i):
                name = (sdl.SDL_JoystickNameForIndex(i) or b"?").decode(errors="replace")
                if name not in self.reported:  # once per controller, not every scan
                    self.reported.add(name)
                    events.say(f"Found {name}, but its button layout is unknown, so it can't be used.",
                               events.WARNING)
                continue
            if sdl.SDL_GameControllerTypeForIndex(i) in self.skip:
                continue
            pad = sdl.SDL_GameControllerOpen(i)
            if pad:
                self.pad = pad
                self.name = (sdl.SDL_GameControllerName(pad) or b"controller").decode(errors="replace")
                return

    def fill(self, g):
        sdl, pad = self.sdl, self.pad
        g.wButtons = sum(bit for button, bit in self.buttons if sdl.SDL_GameControllerGetButton(pad, button))
        axis = lambda a: sdl.SDL_GameControllerGetAxis(pad, a)
        g.bLeftTrigger = trigger(axis(sdl.SDL_CONTROLLER_AXIS_TRIGGERLEFT))
        g.bRightTrigger = trigger(axis(sdl.SDL_CONTROLLER_AXIS_TRIGGERRIGHT))
        g.sThumbLX, g.sThumbLY = axis(sdl.SDL_CONTROLLER_AXIS_LEFTX), up(axis(sdl.SDL_CONTROLLER_AXIS_LEFTY))
        g.sThumbRX, g.sThumbRY = axis(sdl.SDL_CONTROLLER_AXIS_RIGHTX), up(axis(sdl.SDL_CONTROLLER_AXIS_RIGHTY))


def trigger(v):
    """SDL trigger 0..32767 -> XInput 0..255."""
    return max(0, v) * 255 // 32767


def up(v):
    """SDL Y axes grow downward, XInput's upward: flip (-32768 has no positive twin)."""
    return min(32767, -v)


def open_pads():
    """SdlPads for this machine, or None if SDL isn't available."""
    sdl = load()
    return SdlPads(sdl) if sdl else None
