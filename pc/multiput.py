# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Arsmillis (https://github.com/Arsmillis/multiput)
"""multiput: send one controller's input to your PC and a console at once, via a Pico W.

The controller stays connected to this PC, so PC games read it normally.
This program reads the same controller through XInput (which works even when
its window is not focused) and streams signed state to the Pico W, which
presents it to the Switch 2 as a wired controller.

Windows only, Python 3.11+. Wi-Fi uses only the standard library; Bluetooth
needs pyserial.

  multiput --setup     configure and flash the Pico (runs automatically the first time)
  multiput             mirror the controller using the saved settings
  multiput --help      all options (see docs/development.md)

Modules: controller (XInput -> report), protocol (signing, session), links (Wi-Fi /
Bluetooth), setup_wizard + firmware (--setup), settings_store (key and settings).
"""

import argparse
import ctypes
import sys
import threading
import time

try:
    import msvcrt  # keypresses in the multiput window (Windows)
except ImportError:
    msvcrt = None
from pathlib import Path

import settings_store as store
from controller import (DEFAULT_MAP, DEFAULT_PAUSE, NEUTRAL_REPORT, SWITCH_BUTTONS, XBOX_BUTTONS, PauseToggle,
                        XINPUT_STATE, build_report, button_map, button_names, describe_pause, load_xinput,
                        parse_pause, pause_from_settings, pressed)
from links import SerialLink, UdpLink, find_bt_port
from perf import run_perf_test
from protocol import Session
from setup_wizard import run_setup
from version import BANNER, VERSION

POLL_S = 0.001      # how often we read the controller
KEEPALIVE_S = 0.05  # resend unchanged state this often (Pico times out at 250 ms)
FROZEN = getattr(sys, "frozen", False)  # running as the packaged multiput.exe
# Generic firmware: next to multiput.exe when installed, build/firmware/ in the repo.
FIRMWARE_DIR = (Path(sys.executable).parent / "firmware" if FROZEN
                else Path(__file__).resolve().parent.parent / "build" / "firmware")

def parse_args():
    p = argparse.ArgumentParser(prog="multiput", description="Send one controller's input to your PC and a console at once.",
                                epilog=BANNER)
    p.add_argument("--version", action="version", version=BANNER)
    p.add_argument("host", nargs="?", help="Pico hostname or IP (Wi-Fi); overrides the saved setting")
    p.add_argument("--link", choices=["wifi", "bt"],
                   help="use Wi-Fi or Bluetooth to reach the Pico; remembered as the default from now on")
    p.add_argument("--bt", metavar="COMx", help="use this Bluetooth serial port; overrides the saved setting")
    p.add_argument("--controller", type=int, default=0, choices=range(4), help="XInput controller slot (default 0)")
    p.add_argument("--insecure", action="store_true",
                   help="send unsigned packets (Pico must be set up with --allow-unsigned)")
    p.add_argument("--perf-test", action="store_true",
                   help="measure the round trip to the Pico over Wi-Fi and Bluetooth, then exit (close multiput first)")
    p.add_argument("--remap", nargs="*", metavar="XBOX=SWITCH",
                   help="change the button mapping and exit, e.g. --remap A=B B=A PAUSE=VIEW+MENU,XBOX; "
                        "`--remap reset` restores the default; `--remap` alone opens an interactive editor")
    p.add_argument("--config-dir", type=Path, default=store.default_dir(),
                   help="where the key and settings live (default: %%APPDATA%%\\multiput)")
    s = p.add_argument_group("setup options (skip the matching --setup prompts)")
    s.add_argument("--setup", action="store_true", help="configure and flash the Pico")
    s.add_argument("--no-wifi", action="store_true", help="don't set up Wi-Fi on the Pico (Bluetooth only)")
    s.add_argument("--ssid", help="Wi-Fi network name")
    s.add_argument("--password", help="Wi-Fi password (prefer the hidden prompt: this ends up in shell history)")
    s.add_argument("--port", metavar="COMx", help="Bluetooth COM port to save")
    s.add_argument("--firmware", type=Path, help="generic .uf2 to configure (default: the bundled one)")
    s.add_argument("--drive", type=Path, help="Pico drive, e.g. E:\\ (default: detect it)")
    s.add_argument("--output", type=Path, help="write the configured .uf2 to this file instead of flashing")
    s.add_argument("--new-key", action="store_true", help="generate a new signing key instead of reusing the saved one")
    s.add_argument("--allow-unsigned", action="store_true",
                   help="make the Pico also accept unsigned packets (not recommended)")
    return p.parse_args()

def open_link(args, cfg, saved):
    if args.bt:
        return SerialLink(args.bt)
    if args.host:
        return UdpLink(args.host)
    link = args.link or saved.get("link", "wifi")
    if link != saved.get("link"):
        saved["link"] = link
        store.save_settings(cfg, saved)
        print(f"Using {'Bluetooth' if link == 'bt' else 'Wi-Fi'} (remembered for next time).")
    if link == "bt":
        # Re-detect every start: Windows can renumber the port after re-pairing.
        port = find_bt_port() or saved.get("port")
        if not port:
            raise SystemExit("Couldn't find the Pico's Bluetooth COM port. Pair it in Windows, "
                             "then run multiput --setup (or pass --bt COMx).")
        if port != saved.get("port"):
            print(f"Using {port} (the paired Pico's port; saved for next time).")
            saved["port"] = port
            store.save_settings(cfg, saved)
        return SerialLink(port)
    if saved.get("pico_wifi") is False:
        raise SystemExit("The Pico was set up without Wi-Fi. Use --link bt, or run multiput --setup to add Wi-Fi.")
    return UdpLink(saved.get("host", "multiput.local"))

def update_mapping(saved, items):
    """Apply remap items to the saved settings (in place, only if all are valid):
    XBOX=SWITCH, PAUSE=VIEW+MENU,XBOX / PAUSE=NONE, or reset. Raises ValueError."""
    overrides, pause = dict(saved.get("buttons", {})), saved.get("pause")
    for item in items:
        if item.lower() == "reset":
            overrides, pause = {}, None
            continue
        key, sep, value = item.partition("=")
        if not sep:
            raise ValueError(f"expected XBOX=SWITCH (e.g. LB=ZL) or PAUSE=VIEW+MENU, got {item!r}")
        key, value = key.strip().upper(), value.strip()
        if key == "PAUSE":
            pause = [list(c) for c in parse_pause(value)]
        else:
            overrides[key] = value.upper()
    names = button_names(overrides)  # validates
    overrides = {x: sw for x, sw in names.items() if sw != DEFAULT_MAP[x]}  # keep only real changes
    if overrides:
        saved["buttons"] = overrides
    else:
        saved.pop("buttons", None)
    if pause is None or pause_from_settings(pause) == DEFAULT_PAUSE:
        saved.pop("pause", None)
    else:
        saved["pause"] = pause


def pause_combos(saved):
    return pause_from_settings(saved["pause"]) if saved and "pause" in saved else DEFAULT_PAUSE


def print_mapping(saved):
    names = button_names(saved.get("buttons", {}))
    print("Xbox    -> Switch")
    for xbox, switch in names.items():
        print(f"{xbox:7s} -> {switch}{'   (changed)' if switch != DEFAULT_MAP[xbox] else ''}")
    print(f"PAUSE   -> {describe_pause(pause_combos(saved))}{'   (changed)' if 'pause' in saved else ''}")


def edit_mapping(cfg, saved):
    """Interactive editor: used by `multiput --remap` and offered at the end of setup."""
    print_mapping(saved)
    print(f"\nXbox names:   {' '.join(XBOX_BUTTONS)}")
    print(f"Switch names: {' '.join(SWITCH_BUTTONS)}")
    while True:
        line = input("\nChanges (e.g. A=B B=A, PAUSE=VIEW+MENU, PAUSE=VIEW+MENU,XBOX, PAUSE=NONE, reset), "
                     "or Enter to finish: ").strip()
        if not line:
            return
        try:
            update_mapping(saved, line.split())
        except ValueError as e:
            print(f"  {e}")
            continue
        store.save_settings(cfg, saved)
        print()
        print_mapping(saved)


def remap(args, cfg, saved):
    """--remap ITEMS: apply and save. --remap alone: the interactive editor (or just
    the mapping, when there's no console to type into)."""
    saved = saved or {}
    if args.remap:
        update_mapping(saved, args.remap)
        store.save_settings(cfg, saved)
        print_mapping(saved)
    elif sys.stdin.isatty():
        edit_mapping(cfg, saved)
    else:
        print_mapping(saved)


def edit_while_running(cfg, saved, pause, session):
    """M key in the multiput window: edit the mapping, then use it straight away.
    Returns the new (mapping, PauseToggle)."""
    session.send(NEUTRAL_REPORT)  # release everything on the Switch while we're away
    print("\nEditing the mapping. The Switch gets no input until you finish (empty line).\n")
    edit_mapping(cfg, saved)
    new_pause = PauseToggle(pause_combos(saved))
    new_pause.paused = pause.paused and bool(new_pause.combos)  # never stay paused with no way to resume
    session.excuse_silence(time.monotonic())
    print("\nMapping updated. Sending to the Switch again." + (" (Still paused.)" if new_pause.paused else ""))
    return button_map(saved.get("buttons", {})), new_pause


def beep(paused):
    """Short tone so you know pause toggled without looking at the window."""
    try:
        import winsound
    except ImportError:
        return
    threading.Thread(target=winsound.Beep, args=(440 if paused else 880, 120), daemon=True).start()


_instance_mutex = None


def claim_single_instance():
    """Only one multiput may talk to the Pico at a time: two would fight over the signing
    counter (and Bluetooth allows one program per COM port). The mutex is released when
    the process exits."""
    global _instance_mutex
    if sys.platform != "win32":
        return
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    _instance_mutex = kernel32.CreateMutexW(None, False, "Local\\multiput")
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        raise SystemExit("multiput is already running (another window, or the performance test). Close it first.")


def main():
    args = parse_args()
    print(BANNER + "\n")
    cfg = args.config_dir
    if cfg == store.default_dir() and (old := store.migrate_old_dir(cfg)):
        print(f"Moved your key and settings from {old} to {cfg} (minput is now called multiput).")
    saved = store.load_settings(cfg)
    if args.remap is not None:
        remap(args, cfg, saved)
        return
    if args.perf_test:
        if not (saved and "link" in saved):
            raise SystemExit("Set up the Pico first: multiput --setup")
        claim_single_instance()
        run_perf_test(args, saved, store.load_key(cfg))
        if FROZEN:
            input("\nPress Enter to close... ")
        return
    if args.setup or (not (saved and "link" in saved) and not (args.host or args.bt)):
        if not run_setup(args, cfg, FIRMWARE_DIR):
            return
        saved = store.load_settings(cfg)
        if input("\nCustomize the button mapping now? (y/N): ").strip().lower().startswith("y"):
            edit_mapping(cfg, saved)
        input("\nPress Enter to start multiput now (or close this window to start it later)... ")

    saved = saved or {}
    claim_single_instance()
    key = None if args.insecure else store.load_key(cfg)
    mapping = button_map(saved.get("buttons", {}))
    pause = PauseToggle(pause_combos(saved))
    get_state = load_xinput()
    link = open_link(args, cfg, saved)
    session = Session(link, key)
    if key is None:
        print("WARNING: sending UNSIGNED packets. Anyone who can reach the Pico can control your Switch.")
    print(f"Sending controller {args.controller} to {link.name}. Ctrl+C or close this window to stop.")
    if saved.get("buttons"):
        changes = ", ".join(f"{x}->{sw}" for x, sw in saved["buttons"].items())
        print(f"Custom button mapping: {changes}.")
    if pause.combos:
        print(f"Pause/resume sending to the Switch: {describe_pause(pause_combos(saved))}.")
    if msvcrt:
        print("Press M in this window to change the button mapping.")
    if not session.ready:
        print("Waiting for the Pico...")

    state = XINPUT_STATE()
    last_packet, last_sent, connected = None, 0.0, None
    while True:
        now = time.monotonic()
        session.poll(now)
        if msvcrt and msvcrt.kbhit() and msvcrt.getwch().lower() == "m":
            mapping, pause = edit_while_running(cfg, saved, pause, session)
            last_packet = None  # send the current state with the new mapping right away
            continue
        ok = get_state(args.controller, ctypes.byref(state)) == 0
        if ok != connected:
            connected = ok
            print("Controller connected." if ok else "Controller not connected; waiting...")
        if not ok:
            time.sleep(POLL_S)  # no packets: the Pico releases everything after its timeout
            continue
        down = pressed(state.Gamepad)
        if pause.update(down, now):
            print(f"Paused: the Switch gets no input (the PC still does). To resume: {describe_pause(pause_combos(saved))}."
                  if pause.paused else "Resumed: sending to the Switch again.")
            beep(pause.paused)
            last_packet = None  # send the new state right away
        if session.ready and (state.dwPacketNumber != last_packet or now - last_sent >= KEEPALIVE_S):
            if pause.paused:
                report = NEUTRAL_REPORT  # still sent, so the link stays alive
            else:
                # While a pause combo is held, keep its buttons off the Switch.
                report = build_report(state.Gamepad, mapping, pause.held_buttons(down))
            session.send(report)
            last_packet, last_sent = state.dwPacketNumber, now
        time.sleep(POLL_S)

def run():
    """Entry point. When started by double-click, keep error messages on screen."""
    code = 0
    if sys.version_info < (3, 11):
        # Older Pythons sleep ~15.6 ms on Windows instead of the 1 ms poll interval,
        # which would quietly add up to 16 ms of input delay.
        sys.exit("multiput needs Python 3.11 or newer.")
    try:
        main()
    except KeyboardInterrupt:
        pass
    except SystemExit as e:
        if isinstance(e.code, str):
            print(e.code, file=sys.stderr)
            code = 1
        else:
            code = e.code or 0
    except (OSError, ValueError) as e:  # e.g. Pico drive or Bluetooth link lost, bad firmware file
        print(f"Error: {e}", file=sys.stderr)
        code = 1
    if code and FROZEN:
        input("Press Enter to close... ")
    sys.exit(code)

if __name__ == "__main__":
    run()
