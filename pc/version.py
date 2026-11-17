# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Arsmillis (https://github.com/Arsmillis/multiput)
"""multiput's version, from the VERSION file at the repo root (bundled into multiput.exe)."""

import sys
from pathlib import Path

URL = "https://github.com/Arsmillis/multiput"
COPYRIGHT = "Copyright (C) 2026 Arsmillis"
LICENSE = "Apache License 2.0"


def read_version():
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))  # _MEIPASS: inside multiput.exe
    try:
        return (base / "VERSION").read_text().strip()
    except OSError:
        return "unknown"


VERSION = read_version()
BANNER = f"multiput {VERSION} - {COPYRIGHT} - {LICENSE} - {URL}"


def parse(version):
    """"0.2.0" -> (0, 2, 0); None if it isn't X.Y.Z (e.g. a "dev" build)."""
    parts = version.split(".")
    return tuple(int(p) for p in parts) if len(parts) == 3 and all(p.isdigit() for p in parts) else None


def firmware_message(firmware, app=VERSION):
    """What to tell the user about the Pico's firmware version (None: it didn't report one)."""
    update = "run multiput setup (Start menu: multiput setup) to update it"
    if firmware is None:
        return f"Pico firmware is 0.1.0 or older (it doesn't report its version): {update}."
    fw, mine = parse(firmware), parse(app)
    if fw is None or mine is None:
        return f"Pico firmware {firmware} (development build)."
    if fw < mine:
        return f"Pico firmware {firmware} is older than this multiput ({app}): {update}."
    if fw > mine:
        return f"Pico firmware {firmware} is newer than this multiput ({app}): update multiput."
    return f"Pico firmware {firmware} (up to date)."
