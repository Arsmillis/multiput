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
import subprocess
import sys
import threading
import time

try:
    import msvcrt  # keypresses in the multiput window (Windows)
except ImportError:
    msvcrt = None
from pathlib import Path

import events
import hotkey
import settings_store as store
import setup_wizard
from controller import (DEFAULT_MAP, DEFAULT_PAUSE, NEUTRAL_REPORT, PAUSE_HOLD_S, SWITCH_BUTTONS, TURBO_HZ,
                        XBOX_BUTTONS, XINPUT_STATE, ButtonCapture, ButtonModes, ComboCapture, ControllerSlot,
                        PauseToggle, build_report, button_map, button_names, describe_pause, held_buttons_reader,
                        load_xinput, parse_button_list, parse_hold, parse_pause, pause_from_settings, pressed)
from links import SerialLink, UdpLink, find_bt_port
from perf import run_perf_test
from updater import connect, pico_status, run_update
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
    p.add_argument("--controller", type=int, choices=range(4),
                   help="XInput controller slot 0-3 (default: the first connected controller)")
    p.add_argument("--insecure", action="store_true",
                   help="send unsigned packets (Pico must be set up with --allow-unsigned)")
    p.add_argument("--tray", action="store_true",
                   help="run in the system tray (what multiputw.exe does) instead of this console window")
    p.add_argument("--update", action="store_true",
                   help="update the Pico's firmware (and optionally its Wi-Fi network) over the air, "
                        "while it stays in the dock; close multiput first")
    p.add_argument("--pico-status", action="store_true",
                   help="show the Pico's firmware version and diagnostics (e.g. Bluetooth pairing keys), then exit")
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
    s.add_argument("--no-start", action="store_true", help="exit after setup instead of starting multiput")
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

def open_link(args, cfg, saved, stop=None):
    """The link to the Pico. stop (threading.Event): abandon connecting (links.Stopped)."""
    if args.bt:
        return SerialLink(args.bt, stop)
    if args.host:
        return UdpLink(args.host, stop)
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
        return SerialLink(port, stop)
    if saved.get("pico_wifi") is False:
        raise SystemExit("The Pico was set up without Wi-Fi. Use --link bt, or run multiput --setup to add Wi-Fi.")
    return UdpLink(saved.get("host", "multiput.local"), stop)

# Control settings besides the button mapping, with their defaults (saved only when changed).
SETTING_DEFAULTS = {"pause_hold": PAUSE_HOLD_S, "pause_key": hotkey.DEFAULT, "beep": True, "sticky": [], "turbo": []}


def update_mapping(saved, items):
    """Apply remap items to the saved settings (in place, only if all are valid): XBOX=SWITCH,
    PAUSE=VIEW+MENU,XBOX | NONE, PAUSE_HOLD=seconds, PAUSE_KEY=CTRL+ALT+P | NONE, BEEP=ON | OFF,
    STICKY=A,LT | NONE, TURBO=B | NONE, or reset. Raises ValueError."""
    overrides, pause = dict(saved.get("buttons", {})), saved.get("pause")
    settings = {k: saved[k] for k in SETTING_DEFAULTS if k in saved}
    for item in items:
        if item.lower() == "reset":
            overrides, pause, settings = {}, None, {}
            continue
        key, sep, value = item.partition("=")
        if not sep:
            raise ValueError(f"expected NAME=VALUE (e.g. LB=ZL, PAUSE=VIEW+MENU, STICKY=A), got {item!r}")
        key, value = key.strip().upper(), value.strip()
        if key == "PAUSE":
            pause = [list(c) for c in parse_pause(value)]
        elif key == "PAUSE_HOLD":
            settings["pause_hold"] = parse_hold(value)
        elif key == "PAUSE_KEY":
            parsed = hotkey.parse(value)
            settings["pause_key"] = parsed[2] if parsed else ""
        elif key == "BEEP":
            if value.upper() not in ("ON", "OFF"):
                raise ValueError(f"BEEP needs ON or OFF, got {value!r}")
            settings["beep"] = value.upper() == "ON"
        elif key in ("STICKY", "TURBO"):
            settings[key.lower()] = parse_button_list(value, key)
        else:
            overrides[key] = value.upper()
    names = button_names(overrides)  # validates
    both = set(settings.get("sticky", [])) & set(settings.get("turbo", []))
    if both:
        raise ValueError(f"{', '.join(sorted(both))} can't be both STICKY and TURBO")
    overrides = {x: sw for x, sw in names.items() if sw != DEFAULT_MAP[x]}  # keep only real changes
    if overrides:
        saved["buttons"] = overrides
    else:
        saved.pop("buttons", None)
    if pause is None or pause_from_settings(pause) == DEFAULT_PAUSE:
        saved.pop("pause", None)
    else:
        saved["pause"] = pause
    for k, default in SETTING_DEFAULTS.items():
        if k in settings and settings[k] != default:
            saved[k] = settings[k]
        else:
            saved.pop(k, None)


def pause_combos(saved):
    return pause_from_settings(saved["pause"]) if saved and "pause" in saved else DEFAULT_PAUSE


def setting(saved, name):
    return (saved or {}).get(name, SETTING_DEFAULTS[name])


def print_mapping(saved):
    names = button_names(saved.get("buttons", {}))
    print("Xbox    -> Switch")
    for xbox, switch in names.items():
        print(f"{xbox:7s} -> {switch}{'   (changed)' if switch != DEFAULT_MAP[xbox] else ''}")
    changed = lambda name: "   (changed)" if name in saved else ""
    print(f"PAUSE   -> {describe_pause(pause_combos(saved), setting(saved, 'pause_hold'))}{changed('pause')}")
    print()
    print(f"PAUSE_HOLD -> {setting(saved, 'pause_hold'):g} s{' (a single tap)' if setting(saved, 'pause_hold') == 0 else ''}"
          f"{changed('pause_hold')}")
    print(f"PAUSE_KEY  -> {setting(saved, 'pause_key') or 'off'}  (keyboard shortcut, works in games){changed('pause_key')}")
    print(f"BEEP       -> {'ON' if setting(saved, 'beep') else 'OFF'}{changed('beep')}")
    print(f"STICKY     -> {', '.join(setting(saved, 'sticky')) or 'none'}  (each press toggles the button){changed('sticky')}")
    print(f"TURBO      -> {', '.join(setting(saved, 'turbo')) or 'none'}  ({TURBO_HZ} presses/s while held){changed('turbo')}")


CAPTURE_TIMEOUT_S = 30


def wait_for_buttons(capture, read, keyboard):
    """Feed controller readings to a ComboCapture until it has a result.
    None if cancelled (Esc or Enter on the keyboard) or after CAPTURE_TIMEOUT_S."""
    deadline, warned = time.monotonic() + CAPTURE_TIMEOUT_S, False
    while time.monotonic() < deadline:
        if keyboard and keyboard.kbhit() and keyboard.getwch() in ("\x1b", "\r"):
            return None
        down = read()
        if down is None:
            if not warned:
                print("  (No controller connected yet: connect one, or press Esc to cancel.)")
                warned = True
            down = set()
        result = capture.feed(down)
        if result:
            return result
        time.sleep(0.01)
    print("  Timed out.")
    return None


def line_or_button(prompt, read, keyboard):
    """The editor's prompt: returns (typed line, None), or (None, Xbox button) when a button is
    pressed on the controller first. Without a controller reader or console keyboard (not
    Windows), it's a plain input()."""
    if not (read and keyboard):
        return input(prompt), None
    print(prompt, end="", flush=True)
    capture, typed = ButtonCapture(), []
    while True:
        while keyboard.kbhit():
            ch = keyboard.getwch()
            if ch == "\r":
                print()
                return "".join(typed), None
            if ch == "\x03":
                raise KeyboardInterrupt
            if ch in ("\x00", "\xe0"):   # arrow and function keys come as two characters: ignored
                keyboard.getwch()
            elif ch == "\b":
                if typed:
                    typed.pop()
                    print("\b \b", end="", flush=True)
            elif ch.isprintable():
                typed.append(ch)
                print(ch, end="", flush=True)
        button = capture.feed(read() or set())
        if button and not typed:   # a press while typing a line doesn't interrupt it
            print(button)
            return None, button
        time.sleep(0.01)


def map_pressed_button(cfg, saved, xbox):
    """A controller button pressed at the editor's prompt: pick what it sends on the Switch."""
    targets = list(SWITCH_BUTTONS)
    current = button_names(saved.get("buttons", {}))[xbox]
    print(f"{xbox} sends {current} on the Switch. Pick what it should send:")
    print("  " + "  ".join(f"{n}={name}" for n, name in enumerate(targets, 1)))
    choice = input("Number or name (Enter to keep it): ").strip().upper()
    if not choice:
        return
    target = targets[int(choice) - 1] if choice.isdigit() and 1 <= int(choice) <= len(targets) else choice
    update_mapping(saved, [f"{xbox}={target}"])   # ValueError for an unknown name: the editor shows it
    store.save_settings(cfg, saved)


def record_pause(cfg, saved, read, keyboard):
    """P in the editor: record a pause combo by pressing it."""
    print("\nHold the buttons for a pause combo together, then let go (Esc or Enter on the keyboard to cancel)...")
    combo = wait_for_buttons(ComboCapture(), read, keyboard)
    if not combo:
        return
    current = pause_combos(saved)
    print(f"Recorded {' + '.join(combo)}. Pause is now: {describe_pause(current, setting(saved, 'pause_hold'))}.")
    if current:
        how = input("Add it as another pause combo, or replace the current ones? (A/r): ").strip().lower() or "a"
    else:
        how = "r"
    combos = [list(combo)] if how.startswith("r") else [list(c) for c in current] + [list(combo)]
    update_mapping(saved, ["PAUSE=" + ",".join("+".join(c) for c in combos)])
    store.save_settings(cfg, saved)


def edit_mapping(cfg, saved, read=None, keyboard=msvcrt):
    """Interactive editor: used by `multiput --remap`, the M key, the tray, and setup.
    Typed changes, or a button pressed on the controller to remap it; P records a pause combo.
    read: the controller reader (controller.held_buttons_reader by default); keyboard: msvcrt."""
    if read is None and keyboard:
        try:
            read = held_buttons_reader()
        except (OSError, AttributeError):  # no XInput
            pass
    print_mapping(saved)
    print(f"\nXbox names:   {' '.join(XBOX_BUTTONS)}")
    print(f"Switch names: {' '.join(SWITCH_BUTTONS)}")
    print("Examples: A=B B=A | PAUSE=VIEW+MENU,XBOX | PAUSE_HOLD=0 (tap) | PAUSE_KEY=CTRL+ALT+P or NONE")
    print("          BEEP=OFF | STICKY=A,LT | TURBO=B | reset (everything back to the default)")
    pressing = read and keyboard
    if pressing:
        print("Or press a button on the controller to remap it, or type P to record a pause combo.")
    while True:
        prompt = "\nType changes, press a button, P, or Enter to finish: " if pressing else "\nChanges, or Enter to finish: "
        line, button = line_or_button(prompt, read, keyboard)
        try:
            if button:
                map_pressed_button(cfg, saved, button)
            elif not line.strip():
                return
            elif pressing and line.strip().upper() == "P":
                record_pause(cfg, saved, read, keyboard)
            else:
                update_mapping(saved, line.split())
                store.save_settings(cfg, saved)
        except ValueError as e:
            print(f"  {e}")
            continue
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


class Controls:
    """What the main loop needs from the control settings; rebuilt after an M-key edit."""

    def __init__(self, saved, previous=None):
        self.mapping = button_map(saved.get("buttons", {}))
        self.pause = PauseToggle(pause_combos(saved), setting(saved, "pause_hold"))
        self.modes = ButtonModes(setting(saved, "sticky"), setting(saved, "turbo"))
        self.beep = setting(saved, "beep")
        spec = setting(saved, "pause_key")
        if previous and previous.hotkey.spec == (hotkey.parse(spec)[2] if spec else ""):
            self.hotkey = previous.hotkey  # unchanged: keep it registered
        else:
            if previous:
                previous.hotkey.stop()
            self.hotkey = hotkey.Hotkey(spec)
        if previous:  # stay paused, unless there's no longer a way to resume
            self.pause.paused = previous.pause.paused and (bool(self.pause.combos) or self.hotkey.active)

    def describe_pause(self, saved):
        ways = []
        if self.pause.combos:
            ways.append(describe_pause(pause_combos(saved), self.pause.hold))
        if self.hotkey.active:
            ways.append(f"press {self.hotkey.spec} on the keyboard")
        return " or ".join(ways) or "off"


def edit_while_running(cfg, saved, controls, session):
    """M key in the multiput window: edit the mapping and settings, then use them straight
    away. Returns the new Controls."""
    session.send(NEUTRAL_REPORT)  # release everything on the Switch while we're away
    print("\nEditing the mapping. The Switch gets no input until you finish (empty line).\n")
    edit_mapping(cfg, saved)
    new = Controls(saved, controls)
    session.excuse_silence(time.monotonic())
    print("\nMapping updated. Sending to the Switch again." + (" (Still paused.)" if new.pause.paused else ""))
    return new


def beep(paused, enabled=True):
    """Short tone so you know pause toggled without looking at the window (BEEP=OFF: silent)."""
    if not enabled:
        return
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
    if sys.platform != "win32" or _instance_mutex:  # not Windows, or this process already holds it
        return
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    _instance_mutex = kernel32.CreateMutexW(None, False, "Local\\multiput")
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        _instance_mutex = None
        raise SystemExit("multiput is already running (another window, or the performance test). Close it first.")


def release_single_instance():
    """Let another multiput talk to the Pico (the tray app hands the link to the console)."""
    global _instance_mutex
    if _instance_mutex:
        ctypes.WinDLL("kernel32").CloseHandle(ctypes.c_void_p(_instance_mutex))
        _instance_mutex = None


def main():
    args = parse_args()
    print(BANNER + "\n")
    cfg = args.config_dir
    if cfg == store.default_dir() and (old := store.migrate_old_dir(cfg)):
        print(f"Moved your key and settings from {old} to {cfg} (minput is now called multiput).")
    saved = store.load_settings(cfg)
    if args.tray or (FROZEN and sys.stdout is None):  # multiputw.exe has no console
        import tray
        tray.main(args, cfg, store, sys.modules[__name__])
        return
    if args.remap is not None:
        remap(args, cfg, saved)
        return
    if args.update:
        if not (saved and "link" in saved):
            raise SystemExit("Set up the Pico first: multiput --setup")
        claim_single_instance()
        run_update(args, open_link(args, cfg, saved), store.load_key(cfg), saved, store, cfg, FIRMWARE_DIR,
                   setup_wizard.ask_wifi, setup_wizard.ask)
        if FROZEN:
            input("\nPress Enter to close... ")
        return
    if args.pico_status:
        if not (saved and "link" in saved):
            raise SystemExit("Set up the Pico first: multiput --setup")
        claim_single_instance()
        link = open_link(args, cfg, saved)
        print(f"Looking for the Pico over {link.name}...")
        session = connect(link, store.load_key(cfg))
        if session is None:
            raise SystemExit("Couldn't reach the Pico.")
        print(f"Pico status: {pico_status(link) or 'not reported (firmware older than 0.3.1)'}")
        if FROZEN:
            input("\nPress Enter to close... ")
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
        if args.no_start:  # started by the tray app, which carries on by itself
            return
        tray_exe = Path(sys.executable).with_name("multiputw.exe")
        if FROZEN and tray_exe.exists():
            input("\nPress Enter to start multiput in the system tray (or close this window to start it later)... ")
            subprocess.Popen([str(tray_exe)], creationflags=subprocess.DETACHED_PROCESS)
            return
        input("\nPress Enter to start multiput now (or close this window to start it later)... ")

    saved = saved or {}
    claim_single_instance()
    run_loop(args, cfg, saved, None if args.insecure else store.load_key(cfg), keyboard=msvcrt)


def run_loop(args, cfg, saved, key, stop=None, commands=None, keyboard=None, get_state=None):
    """Mirror the controller to the Pico until `stop` (threading.Event) is set.
    commands: a queue.Queue of "pause" (toggle, like the keyboard shortcut; the tray's Pause
    item). keyboard: msvcrt in the console
    (M opens the mapping editor); None in the tray. Status goes through events.say()."""
    controls = Controls(saved)
    get_state = get_state or load_xinput()
    link = open_link(args, cfg, saved, stop)
    session = Session(link, key)
    if key is None:
        events.say("WARNING: sending UNSIGNED packets. Anyone who can reach the Pico can control your Switch.",
                   events.WARNING)
    which = "the first connected controller" if args.controller is None else f"controller {args.controller}"
    events.say(f"Sending {which} to {link.name}." + (" Ctrl+C or close this window to stop." if keyboard else ""))
    if saved.get("buttons"):
        changes = ", ".join(f"{x}->{sw}" for x, sw in saved["buttons"].items())
        events.say(f"Custom button mapping: {changes}.")
    if controls.pause.combos or controls.hotkey.active:
        events.say(f"Pause/resume sending to the Switch: {controls.describe_pause(saved)}.")
    if controls.hotkey.error:
        events.say(f"Keyboard shortcut not available: {controls.hotkey.error}. Change it with PAUSE_KEY.", events.WARNING)
    if controls.modes.sticky or controls.modes.turbo:
        events.say("Sticky: " + (", ".join(sorted(controls.modes.sticky)) or "none") +
                   " | Turbo: " + (", ".join(sorted(controls.modes.turbo)) or "none") + ".")
    if keyboard:
        events.say("Press M in this window to change the button mapping.")
    if not session.ready:
        events.say("Waiting for the Pico...")

    state = XINPUT_STATE()
    slot = ControllerSlot(get_state, args.controller)
    last_report, last_sent, connected = None, 0.0, None
    try:
        while not (stop and stop.is_set()):
            now = time.monotonic()
            session.poll(now)
            toggled = controls.hotkey.fired()  # the keyboard shortcut works even without a controller
            while commands is not None and not commands.empty():
                command = commands.get_nowait()
                if command == "pause":
                    toggled = not toggled
            if keyboard and keyboard.kbhit() and keyboard.getwch().lower() == "m":
                controls = edit_while_running(cfg, saved, controls, session)
                last_report = None  # send the current state with the new settings right away
                continue
            ok = slot.read(state, now)
            if ok != connected:
                if ok:
                    events.say(f"Controller connected (slot {slot.current}).", events.CONTROLLER_UP)
                else:
                    events.say("Controller not connected; waiting...", events.CONTROLLER_LOST)
                connected = ok
                controls.modes.reset()  # release sticky buttons when the controller goes away
            if toggled:
                controls.pause.toggle()
            down = pressed(state.Gamepad) if ok else set()
            if (ok and controls.pause.update(down, now)) or toggled:
                if controls.pause.paused:
                    events.say(f"Paused: the Switch gets no input (the PC still does). To resume: "
                               f"{controls.describe_pause(saved)}.", events.PAUSED)
                else:
                    events.say("Resumed: sending to the Switch again.", events.RESUMED)
                beep(controls.pause.paused, controls.beep)
            if not ok:
                time.sleep(POLL_S)  # no packets: the Pico releases everything after its timeout
                continue
            held = controls.modes.apply(down, now)
            if controls.pause.paused:
                report = NEUTRAL_REPORT  # still sent, so the link stays alive
            else:
                # While a pause combo is held, keep its buttons off the Switch.
                report = build_report(state.Gamepad, controls.mapping, controls.pause.held_buttons(down), held)
            # Send on any change (turbo changes the report while the controller is still) and as a keepalive.
            if session.ready and (report != last_report or now - last_sent >= KEEPALIVE_S):
                session.send(report)
                last_report, last_sent = report, now
            time.sleep(POLL_S)
    finally:
        if session.ready:
            session.send(NEUTRAL_REPORT)  # leave nothing pressed on the console
        link.close()
        controls.hotkey.stop()


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
    if code and FROZEN and sys.stdin is not None:  # multiputw.exe has no console to wait in
        input("Press Enter to close... ")
    sys.exit(code)

if __name__ == "__main__":
    run()
