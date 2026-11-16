# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Arsmillis (https://github.com/Arsmillis/multiput)
"""Where the PC keeps its signing key and connection settings.

Default folder: %APPDATA%\\multiput on Windows (~/.config/multiput elsewhere).
  multiput.key      64 hex chars; the same key is written into the Pico's firmware
  settings.json   {"link": "wifi", "host": "multiput.local", "ssid": "HomeNet"} or
                  {"link": "bt", "port": "COM5"}, plus "buttons": {"A": "B", ...} after
                  `multiput --remap` (only the buttons that differ from the default)
The Wi-Fi password is never stored on the PC; it only goes into the Pico firmware.
The network name is kept only to offer it as the default at the next setup.
"""

import json
import os
import secrets
from pathlib import Path

from protocol import KEY_LEN


def default_dir():
    appdata = os.environ.get("APPDATA")
    return Path(appdata) / "multiput" if appdata else Path.home() / ".config" / "multiput"


OLD_NAME = "minput"  # this project's name before it became multiput (2026-11)


def migrate_old_dir(cfg):
    """One-time move of the key and settings from the folder used under the old name.
    Only for the default folder; returns the old folder if it moved something."""
    old = cfg.parent / OLD_NAME
    if cfg.exists() or not old.is_dir():
        return None
    old.rename(cfg)
    old_key = cfg / f"{OLD_NAME}.key"
    if old_key.exists():
        old_key.rename(cfg / "multiput.key")
    settings = load_settings(cfg)
    if settings and settings.get("host") == f"{OLD_NAME}.local":
        settings["host"] = "multiput.local"  # the re-flashed Pico announces the new name
        save_settings(cfg, settings)
    return old


def load_key(cfg):
    path = cfg / "multiput.key"
    try:
        key = bytes.fromhex(path.read_text().strip())
    except FileNotFoundError:
        raise SystemExit(f"No signing key at {path}. Run setup first: multiput --setup")
    except ValueError:
        key = b""
    if len(key) != KEY_LEN:
        raise SystemExit(f"{path} is corrupt. Run multiput --setup --new-key and re-flash the Pico.")
    return key


def key_for_setup(cfg, new=False):
    """The saved key (so re-flashing keeps old setups working), or a new one if new=True
    or none exists. Not saved here: call save_key only once the Pico has the key."""
    if (cfg / "multiput.key").exists() and not new:
        return load_key(cfg)
    return secrets.token_bytes(KEY_LEN)


def save_key(cfg, key):
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "multiput.key").write_text(key.hex() + "\n")


def load_settings(cfg):
    try:
        return json.loads((cfg / "settings.json").read_text())
    except FileNotFoundError:
        return None


def save_settings(cfg, settings):
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "settings.json").write_text(json.dumps(settings, indent=2) + "\n")
