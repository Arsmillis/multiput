# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Arsmillis (https://github.com/Arsmillis/multiput)
"""Status messages from the running program. The console prints them; the tray app
(tray.py) installs a handler that also updates its icon and shows notifications."""

INFO = "info"
WARNING = "warning"
PICO_UP = "pico_up"                  # session started, Pico restarted, reconnected
PICO_LOST = "pico_lost"
CONTROLLER_UP = "controller_up"
CONTROLLER_LOST = "controller_lost"
PAUSED = "paused"
RESUMED = "resumed"
FIRMWARE_OK = "firmware_ok"
FIRMWARE_UPDATE = "firmware_update"  # the Pico's firmware differs from this multiput

_handler = None


def set_handler(handler):
    """handler(text, kind); None restores plain printing."""
    global _handler
    _handler = handler


def say(text, kind=INFO):
    if _handler:
        _handler(text, kind)
    else:
        print(text)
