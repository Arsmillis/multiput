# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Arsmillis (https://github.com/Arsmillis/multiput)
"""`multiput --setup`: configure the generic firmware and flash it onto the Pico.

Every prompt can be skipped with a command-line option (see docs/development.md).
"""

import getpass
import os
import string
import time
from pathlib import Path

import firmware
import settings_store as store
from links import find_bt_port

STILL_WAITING_S = 20  # then explain what to check


def ask(prompt, default=None):
    answer = input(f"{prompt} [{default}]: " if default else f"{prompt}: ").strip()
    return answer or default


def find_pico_drive():
    """Drive letter of a Pico in BOOTSEL mode (it shows up as a USB drive named RPI-RP2)."""
    for letter in string.ascii_uppercase:
        try:
            if "RPI-RP2" in Path(f"{letter}:/INFO_UF2.TXT").read_text(errors="ignore"):
                return Path(f"{letter}:/")
        except OSError:
            pass
    return None


def wait_for_pico_drive():
    if os.name != "nt":
        # Drive letters only exist on Windows; under WSL or Linux this would wait forever.
        raise SystemExit("Flashing needs Windows: run setup from a Windows terminal (cmd or PowerShell), "
                         "or pass --drive with the Pico's drive (or --output to write a file).")
    print("\nHold the BOOTSEL button on the Pico, plug it into this PC, then let go.")
    print("Waiting for the Pico (it appears as a drive named RPI-RP2)... Ctrl+C to cancel.")
    start, hinted = time.monotonic(), False
    while (drive := find_pico_drive()) is None:
        if not hinted and time.monotonic() - start > STILL_WAITING_S:
            drives = [f"{c}:" for c in string.ascii_uppercase if os.path.exists(f"{c}:/")]
            print(f"Still waiting. Drives seen: {' '.join(drives) or 'none'}.")
            print("  No RPI-RP2 drive? Unplug the Pico, hold BOOTSEL, and plug it in again (use a data cable).")
            print("  RPI-RP2 drive visible in Explorer? Run setup again with --drive, e.g. --drive E:\\")
            hinted = True
        time.sleep(0.5)
    print(f"Found the Pico at {drive}")
    return drive


def flash(drive, uf2):
    try:
        (drive / "multiput.uf2").write_bytes(uf2)
    except OSError:
        # The Pico reboots as soon as it has the whole file, which can make Windows
        # report an error on close. Only a drive that stays there means failure.
        for _ in range(10):
            if find_pico_drive() is None:
                break
            time.sleep(0.5)
        else:
            raise
    print("Pico flashed. It restarts by itself.")


def ask_wifi(args, key, last_ssid=None):
    """Returns (packed settings, ssid). Re-prompts for whichever value is invalid; a value
    given on the command line is not prompted for, so an invalid one is an error.
    last_ssid (the previous setup's network) is offered as the default."""
    ssid = args.ssid
    while True:
        if ssid is None:
            ssid = ask("Wi-Fi network name (must be a 2.4 GHz network)", last_ssid) or ""
        try:
            firmware.check_ssid(ssid)
            break
        except ValueError as e:
            if args.ssid is not None:
                raise
            print(f"  {e}. Try again.")
            ssid = None
    password = args.password
    while True:
        if password is None:
            password = getpass.getpass("Wi-Fi password (hidden; leave empty for an open network): ")
        try:
            return firmware.pack_settings(key, ssid, password, args.allow_unsigned), ssid
        except ValueError as e:
            if args.password is not None:
                raise
            print(f"  {e}. Try again.")
            password = None


def ask_bt_port():
    print("\nNow pair the Pico with Windows: Settings > Bluetooth & devices > Add device > Bluetooth,")
    print("then choose 'multiput'. Keep the Pico plugged into this PC while you do this.")
    input("Press Enter once it is paired... ")
    for _ in range(10):  # Windows can take a moment to create the COM ports after pairing
        found = find_bt_port()
        if found:
            print(f"Found the paired Pico on {found}.")
            return ask("COM port (press Enter to use it)", found)
        time.sleep(0.5)
    print("Couldn't find the paired Pico's COM port automatically.")
    try:
        from serial.tools import list_ports
        ports = [p for p in list_ports.comports()
                 if "bluetooth" in (p.description or "").lower() or "BTHENUM" in (p.hwid or "").upper()]
    except ImportError:
        ports = []
    for p in ports:
        print(f"  {p.device}: {p.description}")
    print("Windows creates two ports for a paired device; use the 'Outgoing' one "
          "(More Bluetooth settings > COM Ports).")
    port = ask("COM port", ports[0].device if ports else None)
    if not port:
        raise SystemExit("No COM port given. Run multiput --setup again once the Pico is paired.")
    return port


def run_setup(args, cfg, firmware_dir):
    """Configure + flash the Pico and save the PC's settings. Returns True if the Pico was flashed.
    The firmware listens on both links; Wi-Fi is optional, and multiput picks the link to use."""
    print("multiput setup\n")
    print("The Pico can be reached over Wi-Fi and Bluetooth; multiput chooses which one to use.\n")
    if args.no_wifi and args.link == "wifi":
        raise SystemExit("--link wifi needs Wi-Fi on the Pico; drop --no-wifi.")
    key = store.key_for_setup(cfg, new=args.new_key)
    pc = store.load_settings(cfg) or {}  # updated below; other saved settings (e.g. buttons) are kept
    if args.no_wifi:
        use_wifi = False
    elif args.ssid is not None:
        use_wifi = True
    else:
        use_wifi = not ask("Set up Wi-Fi on the Pico? (Y/n; n = Bluetooth only)", "y").lower().startswith("n")
    if use_wifi:
        settings, pc["ssid"] = ask_wifi(args, key, pc.get("ssid"))
    else:
        settings = firmware.pack_settings(key, allow_unsigned=args.allow_unsigned)

    base = args.firmware or firmware_dir / "multiput.uf2"
    uf2 = firmware.patch_uf2(base.read_bytes(), settings)
    if args.output:
        args.output.write_bytes(uf2)
        print(f"Wrote configured firmware to {args.output}. It contains your Wi-Fi password and key: keep it private.")
    else:
        flash(args.drive or wait_for_pico_drive(), uf2)
    store.save_key(cfg, key)  # only now does the Pico (or the output file) have this key

    pc["pico_wifi"] = use_wifi
    if not use_wifi:
        link = "bt"
    else:
        link = args.link or ("bt" if ask("Which link should multiput use? Wi-Fi or Bluetooth (w/b)", "w")
                             .lower().startswith("b") else "wifi")
    pc["link"] = link
    if use_wifi:
        pc["host"] = args.host or pc.get("host") or "multiput.local"
    else:
        pc.pop("host", None)
    if link == "bt":
        pc["port"] = args.port or ask_bt_port()
    store.save_settings(cfg, pc)

    print("\nSetup done. Next:")
    print("  1. Plug the Pico into a USB port on the Switch 2 dock.")
    print("  2. Start multiput (desktop shortcut, or `multiput`) whenever you want to play.")
    if use_wifi:
        print("  To change link later: multiput --link wifi  or  multiput --link bt (pair 'multiput' in Windows first).")
    return not args.output
