# multiput

**Send one controller's input to your PC and a console at once.**

```
Xbox controller ──(USB/Bluetooth)──► Windows PC ── PC games read it normally
                                        │
                                   multiput.exe (XInput → signed packets over Wi-Fi)
                                        ▼
                         Pico W ──(USB)──► console, e.g. Switch 2 dock (seen as a wired controller)
```

Each press goes to both devices once: the PC gets it directly from the controller, and the console gets it from the Pico. See [Tested consoles](#tested-consoles) for which consoles work; the rest of this guide uses the Switch 2.
For why the Pico W, its hardware requirements, and the end-to-end flow, see [docs/how-it-works.md](docs/how-it-works.md).

## Contents
- [multiput](#multiput)
  - [Contents](#contents)
  - [Personal Intro \& AI Use](#personal-intro--ai-use)
  - [Tested consoles](#tested-consoles)
  - [Install](#install)
    - [What you need](#what-you-need)
    - [Steps](#steps)
  - [Use](#use)
  - [Security](#security)
  - [Mapping](#mapping)
  - [Notes](#notes)
  - [Wi-Fi or Bluetooth](#wi-fi-or-bluetooth)
  - [Building from source](#building-from-source)
  - [Repository](#repository)
- [License](#license)

## Personal Intro & AI Use

Hey everyone, I wanted to provide a quick introduction to myself here before getting too deep into the project itself,
providing a bit of the "human element" so to speak. My name's Arsmillis, I work as a software engineer -- really a Site
Reliability Engineer -- in my day-to-day, and I have plenty of other hobbies aside from learning Japanese: reading books
of all sorts (currently reading _The Wildwood Chronicles_ by Colin Meloy), a bit of running and cycling, anime, video
games, traveling, cooking, learning, and overall trying to appreciate what everyone loves about life. Like many of you
reading this, all of that obviously comes _after_ caring for family and friends.

All that being said, I started this project on the side while working on a separate, Japanese-to-English OCR application.
I eventually wanted to use said app when playing games on console and hit a bit of a wall on getting my controller to
properly interface with both the PC and console. This was my solution to that particular problem, one that I realized
could prove beneficial to others in similar situations.

As for the AI use: as you can imagine, living life and having other hobbies leaves me with relatively little spare time
to spend on projects such as these, so I **_do_** use AI to help me code and research more quickly; however I **_do not_**
think AI can truly replace the imagination and caring that people give when they endeavor to create. It sure does
save me _a lot_ of time when coding though. I personally review and try to fully understand all code written here as I also
"play director" with how the app gets made; but once again let me remind you: this is *not* my full-time job or the only
thing I work on in my free time. Please keep that in mind for those of you that would immediately dismiss this tool due
to AI usage. I understand not liking AI -- I have my own reservations -- but it still has its appropriate uses.

## Tested consoles
| Console | Status | Notes |
|---|---|---|
| **Nintendo Switch 2** (docked) | **Works**, tested | Pico in a USB port on the dock; it appears as a wired HORIPAD S controller. No console settings needed. Tested 2026-11 over Wi‑Fi and Bluetooth. |
| Nintendo Switch 2 (handheld) | Not tested | Would need a USB‑C OTG adapter on the console's USB‑C port. |
| Nintendo Switch (original) | Not tested | It accepts the same HORIPAD wired controllers, so it's expected to work. |
| PlayStation, Xbox | Not possible | These consoles only accept controllers with a licensed authentication chip. |

If you try multiput on another console, open an issue with what worked and what didn't.

## Install

### What you need
- A **Raspberry Pi Pico W**: the original, not the Pico 2 W or a Pico without the "W". No soldering needed.
- A **micro‑USB to USB‑A data cable**. Charge-only cables won't work.
- A **Windows 10 or 11 PC** and an **Xbox controller** connected to it.
- A **2.4 GHz Wi‑Fi network** that the PC is also on (the PC itself can use 5 GHz or Ethernet).

### Steps
1. **Run the installer.** Download `multiput-setup-0.1.0.exe` and double-click it.
   - Windows may show "Windows protected your PC", because the installer isn't code-signed. Click **More info → Run anyway**.
   - multiput installs for your user only (no admin prompt) into `%LOCALAPPDATA%\Programs\multiput`.
   - Keep **Create a desktop shortcut** ticked.
2. **Set up the Pico.** On the last page, leave **Set up the Pico now** ticked and click **Finish**. A setup window opens:
   1. Press Enter to set up Wi‑Fi (or type `n` for Bluetooth only), then type your Wi‑Fi name and password. The password stays hidden while you type.
   2. When asked which link multiput should use, press Enter for Wi‑Fi (or type `b` for Bluetooth; see [Wi‑Fi or Bluetooth](#wi-fi-or-bluetooth)).
   3. When it says *Waiting for the Pico*, hold the **BOOTSEL** button on the Pico, plug it into the PC, then let go. Setup finds it and flashes it, and the Pico restarts by itself.
   4. Setup asks whether to customize the button mapping. Press Enter to keep the default, or type `y` to change buttons or the pause combos (see [Mapping](#mapping)). You can always do this later.
3. **Plug the Pico into a USB port on the Switch 2 dock.** The Switch sees the controller straight away. Its LED blinks fast while it joins Wi‑Fi, then slowly while it waits for the PC. The Switch 2 needs no setting changed.
4. **Start multiput.** Back in the setup window, press Enter to start now, or later double-click the **multiput** desktop shortcut. When the window says `Controller connected.` and the Pico's LED is solid, presses go to both devices.

**Later:**
- To set up the Pico again (new Wi‑Fi network or new Pico), use **Start menu → multiput setup (flash the Pico)**. It offers the network name you used last time; just press Enter to keep it.
- To uninstall, go to Settings → Apps → Installed apps → multiput → Uninstall. Your key and settings stay in `%APPDATA%\multiput`; delete that folder too if you won't reinstall.

## Use
Double-click the **multiput** desktop shortcut. A window opens and shows:
```
Sending controller 0 to multiput.local (192.168.1.50:41234). Ctrl+C or close this window to stop.
Pico session started.
Controller connected.
```
**Pause the Switch side:** hold **View + Menu** for 1 second (or any of the combos you chose; see [Mapping](#mapping)). multiput beeps (low tone), and the Switch sees no buttons pressed until you hold a pause combo again (high tone). Your PC game keeps working the whole time, because it reads the controller directly. While a combo is held, its buttons aren't sent to the Switch, so View + Menu doesn't press − and + there.

**Change the mapping without restarting:** press **M** in the multiput window (see [Mapping](#mapping)).

Close the window to stop. You can start multiput before the Pico is plugged in. It shows `Looking for the Pico at multiput.local...` or `Waiting for the Pico...` until it finds it.

If the Pico drops out mid-session, the window shows `Lost contact with the Pico; reconnecting...` and then `Reconnected to the Pico.` on its own. Meanwhile the PC game keeps working, and the Switch side releases all inputs.

The Pico's LED:
- **Blinking fast:** joining Wi‑Fi. If it never stops, the Wi‑Fi name or password is wrong: run setup again. (Bluetooth still works meanwhile.)
- **Blinking slowly:** waiting for the PC.
- **Solid:** receiving input.
- **Triple blink, repeating:** the firmware was never configured. Run setup instead of copying the generic `.uf2` yourself.

## Security
Every packet is signed with a key that only your PC and your Pico have (HMAC‑SHA256, via BearSSL), so nobody on your network can send inputs to your Switch. Each packet also carries a counter, and the Pico picks a fresh random session value every time it boots, so recorded packets can't be replayed. The full protocol is described in `pico/multiput_pico/protocol.h`.
- **Where things live.** Setup creates the key and keeps it in `%APPDATA%\multiput\multiput.key`. Your Wi‑Fi password is never saved on the PC: setup writes it straight into the Pico's firmware.
- **Physical access.** Anyone who can physically take the Pico can read its flash, which includes your Wi‑Fi password and the key. The RP2040 has no secure storage, so encrypting them on the Pico wouldn't help: the decryption key would have to sit right next to them. Treat the Pico like any device that knows your Wi‑Fi password.
- **Changing the key:** run setup with `--new-key` (see [Development](docs/development.md)). This re-flashes the Pico with the new key.
- **Not protected against:** someone on the network jamming or dropping packets. The Pico then just releases all inputs.

## Mapping
Buttons map by label by default (Xbox A → Switch A, B → B, X → X, Y → Y). LB/RB → L/R, LT/RT → ZL/ZR, View → −, Menu → +, stick clicks → stick clicks, Xbox button → Home.

**Remapping:** while multiput is running, click its window and press **M**. Otherwise, open **Start menu → multiput button mapping** (or run `multiput --remap`). It shows the current mapping and lets you type changes until you press Enter on an empty line. Changes are saved straight away. With **M**, they also take effect immediately; the Switch gets no input while the editor is open. Otherwise they're used the next time multiput starts.

Changes are `XBOX=SWITCH` pairs, plus `PAUSE=` for the pause combos. Put several changes on one line separated by spaces. In `PAUSE=`, join the buttons of a combo with `+`, and list alternative combos with `,`: holding any one of them pauses or resumes, so you can keep one that suits each game. If any change on a line is invalid, none of them are applied.
```
A=B B=A X=Y Y=X      map by position instead of by label
VIEW=CAPTURE         View becomes the Switch's Capture button
LT=NONE              LT does nothing on the Switch
PAUSE=XBOX           pause by holding the Xbox button for 1 s
PAUSE=LB+RB          pause by holding LB + RB for 1 s
PAUSE=VIEW+MENU,XBOX pause by holding either View + Menu or the Xbox button
PAUSE=NONE           turn pausing off
reset                everything back to the default
```
You can also pass them straight on the command line, e.g. `multiput --remap A=B B=A PAUSE=VIEW+MENU,XBOX`. From a source checkout use `py pc\multiput.py --remap`; for an installed copy without the shortcut, use `"%LOCALAPPDATA%\Programs\multiput\multiput.exe" --remap`.

| | Names |
|---|---|
| **Xbox** | `A` `B` `X` `Y` `LB` `RB` `LT` `RT` `VIEW` `MENU` `LS` `RS` `XBOX` |
| **Switch** | `A` `B` `X` `Y` `L` `R` `ZL` `ZR` `MINUS` `PLUS` `LSTICK` `RSTICK` `HOME` `CAPTURE` `NONE` |

The d-pad and sticks always map straight across. Pause combos use Xbox (physical) button names, whatever those buttons are remapped to, and a combo's buttons aren't sent to the Switch while it's held. Remapping only affects the Switch; PC games still see the Xbox controller as it is.

## Notes
- If no valid input arrives for 250 ms (Wi‑Fi hiccup, multiput closed, controller off), the Pico releases every input, so buttons never get stuck. If the Pico loses Wi‑Fi, it keeps retrying in the background (every 10 s) without disturbing Bluetooth. multiput notices within about 4 s when the Pico stops answering, and reconnects on its own, even if the Pico came back with a new IP address or the Bluetooth link dropped.
- Latency over Wi‑Fi is about 3 ms per button press on a decent 2.4 GHz network ([measurements](docs/performance.md)). Run **Start menu → multiput performance test** to check your own setup.

## Wi-Fi or Bluetooth
The Pico listens on both; multiput picks which one to use, and you can switch any time without re-flashing:
```
multiput --link bt      use Bluetooth (remembered from now on)
multiput --link wifi    back to Wi‑Fi
```
- **Wi‑Fi** (default) is the steadiest: measured at about 3 ms per button press, rarely more. The PC and Pico must be on the same network.
- **Bluetooth** needs no network, for example when travelling. It's about as fast typically (about 3.5 ms), but about 1 press in 10 is delayed by over 10 ms, and occasionally by over a frame, so prefer Wi‑Fi for fast games. See [Performance](docs/performance.md) for the measurements and how to test your own setup. First pair **multiput** in Windows under Settings → Bluetooth & devices → Add device, with the Pico powered. multiput finds its COM port by itself, and re-checks it every start in case Windows renumbers it.

The two links share one radio, so the Pico gives way on the one you're not using. While Wi‑Fi carries input, Bluetooth stops accepting connections and stops advertising. While Bluetooth carries input, Wi‑Fi goes into power-save. After switching, the old link is noticed as idle within about 2 seconds, and then the other one is ready.

If you set up the Pico without Wi‑Fi, only Bluetooth is available; run setup again to add Wi‑Fi. Bluetooth pairing uses "Just Works" with no PIN, so anyone nearby can connect while the Pico is listening; the signing is what stops them from sending inputs.

## Building from source
**You need:** Windows with [WSL](https://learn.microsoft.com/windows/wsl/install) (`wsl --install`), Python 3.11+ on Windows, and `gcc`/`g++` in WSL (`sudo apt install build-essential`). Clone the repo onto a **Windows drive** (for example `C:\src\multiput`), so that WSL and Windows build from the same files.

**Build everything** (from a Windows terminal in the repo folder):
```
tools\build.bat
```
This runs three steps and stops at the first failure:
1. **Pico firmware** in WSL → `build\firmware\multiput.uf2` (one firmware for both links). The first run installs `arduino-cli` and the Pico board core (about 500 MB) for you.
2. **Tests** in WSL.
3. **`multiput.exe` and the installer** → `build\installer\multiput-setup-<version>.exe`. The first run installs Inno Setup with winget. PyInstaller goes in a private venv under `build\`, not your global Python.

Everything the build prints is also saved to `build\logs\build.log`, which is replaced on each run. The full compiler output for the firmware is in `build\logs\firmware.log`; the terminal shows only errors and warnings from multiput's own files.

**Run a single step:**
| Step | Command |
|---|---|
| Firmware only (WSL) | `tools/build_firmware.sh` |
| Tests only (WSL) | `tools/run_tests.sh` |
| Installer only (Windows; needs the firmware) | `tools\build_installer.bat` |
| Run from source without installing (Windows) | `py pc\multiput.py --setup`, then `py pc\multiput.py`, or double-click `multiput.bat`. Bluetooth also needs `py -m pip install pyserial`. |

**After building:** run `build\installer\multiput-setup-<version>.exe` and follow the [Install steps](#steps), the same as a downloaded install.
- **Changed only PC code?** Reinstall, or close multiput and run it from source (`multiput.bat`).
- **Changed the firmware?** Reflash the Pico with **Start menu → multiput setup (flash the Pico)**. Your saved key is reused.
- **Sharing your build?** Send only the installer `.exe`, never anything from `%APPDATA%\multiput` (your key) or a `.uf2` made with `--output` (your Wi‑Fi password).

See [Development](docs/development.md) for building from the Arduino IDE, every command-line option, and a file-by-file map.

## Repository
| Folder | What's in it |
|---|---|
| `pc/` | The Windows program (`multiput.exe`); `multiput.py` is the entry point. |
| `pico/multiput_pico/` | The Pico W firmware (an Arduino sketch). |
| `tools/` | Build scripts: `build_firmware.sh` (WSL/Linux) and `build_installer.bat` (Windows). |
| `tests/` | Protocol and setup tests. |
| `docs/` | [How it works](docs/how-it-works.md): why a Pico W, hardware requirements, and what happens to one button press. [Performance](docs/performance.md): measured Wi‑Fi and Bluetooth delay, and how to test yours. [Development](docs/development.md): command-line options, running from source, building, tests, and a file-by-file map. |
| `build/` | Everything generated: firmware, exe, installer (git-ignored). |

`multiput.bat` in the root runs multiput from source without installing it.

## License
multiput is open source under the [Apache License 2.0](LICENSE). You may use, change and share it, including commercially. **Attribution is required:** if you redistribute multiput, or anything built from it, you must keep the copyright and license notices, mark the files you changed, and include the attribution in [`NOTICE`](NOTICE), as section 4 of the license describes. Each source file starts with its license and copyright line.

The firmware and installer also contain third-party components under their own licenses; see [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md). In particular, the firmware may only be used on Raspberry Pi hardware such as the Pico W.
