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
