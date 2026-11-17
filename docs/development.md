# Development

## Repository layout
```
multiput/
├── README.md               user guide: install, use, security, building
├── LICENSE, NOTICE         Apache 2.0 license and the attribution that redistributors must carry
├── THIRD_PARTY_NOTICES.md  licenses of components inside the firmware and installer
├── VERSION                 the version number (single source; see Versioning and releases)
├── CHANGELOG.md            what changed in each version
├── .gitattributes          keeps .sh files LF and .bat files CRLF
├── multiput.bat            run from source without installing (double-click)
├── docs/
│   ├── how-it-works.md     hardware and end-to-end flow
│   ├── performance.md      the performance test: how to run it, and measured results
│   └── development.md      this file
├── pc/                     the Windows program (multiput.exe)
│   ├── multiput.py         entry point: command line, main loop
│   ├── controller.py       reads the Xbox controller (XInput), builds the Switch report, mapping, pause, sticky/turbo
│   ├── hotkey.py           the system-wide keyboard shortcut for pausing (Windows RegisterHotKey)
│   ├── protocol.py         signing and the session with the Pico (PC half of protocol.h)
│   ├── links.py            Wi-Fi (UDP) and Bluetooth (COM port) connections, with reconnecting; finds the Pico's COM port
│   ├── setup_wizard.py     multiput --setup: prompts, finding the Pico drive, flashing
│   ├── firmware.py         writes the settings block into a generic .uf2
│   ├── settings_store.py   the key and saved settings in %APPDATA%\multiput
│   ├── perf.py             multiput --perf-test: round-trip measurement over each link
│   ├── updater.py          multiput --update: firmware and Wi-Fi updates over the air (PC half of ota.h)
│   └── version.py          reads VERSION; the banner shown by --version and at startup
├── pico/multiput_pico/     the Pico W firmware (Arduino sketch; the folder must match the .ino name)
│   ├── multiput_pico.ino   USB controller (HORIPAD S), main loop, settings block
│   ├── protocol.h          wire protocol: frame parsing, signature check, sync
│   ├── ota.h               over-the-air updates: signed image transfer, encrypted Wi-Fi changes
│   ├── settings.h          the settings block that --setup fills in, and which settings win at boot
│   ├── transport_wifi.h    Wi-Fi link (UDP, multiput.local); power-save while Bluetooth is in use
│   ├── transport_bt.h      Bluetooth link; stops listening while Wi-Fi is in use
│   └── transport_bt_serial.cpp   SerialBT wrapper, separate because its headers clash with TinyUSB
├── tools/
│   ├── build_firmware.sh   builds build/firmware/multiput.uf2 (WSL/Linux)
│   ├── build.bat           one-step build: firmware + tests (via WSL), then the installer
│   ├── build_installer.bat builds multiput.exe and the installer (Windows)
│   ├── run_tests.sh        runs all the test files (WSL/Linux)
│   ├── release.sh          publishes or republishes the GitHub release for VERSION (WSL, gh)
│   ├── release_notes.py    release notes from CHANGELOG.md, with checksums
│   └── multiput.iss        Inno Setup installer definition
├── tests/
│   ├── test_protocol.py    PC protocol + links against the Pico's protocol.h compiled for the desktop
│   ├── protocol_sim.cpp    that desktop build of protocol.h and ota.h (with in-memory storage)
│   ├── pico_sim.py         builds and drives it; fake links for the tests
│   ├── test_ota.py         over-the-air updates against ota.h, the settings choice, multiput --update
│   ├── test_setup.py       .uf2 settings patching and the --setup flow
│   ├── test_controller.py  button mapping, --remap, pause combos, M-key editing
│   ├── test_perf.py        the performance test's measuring logic, against a fake Pico
│   └── test_release.py     release notes generation
└── build/                  everything generated (git-ignored)
```

Things that must stay in sync across the two halves:
- the wire protocol: `pc/protocol.py` and `pico/multiput_pico/protocol.h` (`tests/test_protocol.py` checks them against each other);
- the settings block: `pc/firmware.py` (`SETTINGS_FORMAT`) and `pico/multiput_pico/settings.h` (both assert its size, 147 bytes).

## Contributing
**All changes go through a pull request into `main`. Don't push to `main` directly.**
1. Work on a branch, e.g. `git switch -c fix/bt-reconnect`.
2. Run `tools/run_tests.sh` (WSL). If you changed the firmware or the installer, run the full build with `tools\build.bat`.
3. Decide the version your change ships as, following the bump rules in [Versioning and releases](#versioning-and-releases). Set `VERSION` to it, and add your change to `CHANGELOG.md` under `## [X.Y.Z] - YYYY-MM-DD`. If that section doesn't exist yet, create it above the previous release; if another PR already bumped the version for the same release, add to its section. "Unreleased" is only for changes that won't trigger a release on their own.
4. Push the branch and open a pull request into `main`. Merge it once it's reviewed and the tests pass.

Releases are made from `main` after merging (see [Versioning and releases](#versioning-and-releases)).

## Overriding setup
Every setup prompt has a matching option. Anything you leave out is still asked for. Run `multiput --help` for the full list.

| Option | Instead of |
|---|---|
| `--no-wifi` | the "Set up Wi‑Fi?" question, answering no (Bluetooth only) |
| `--link wifi` / `--link bt` | the "Which link should multiput use?" question |
| `--ssid NAME` | the Wi‑Fi name prompt (which defaults to the last network used; the name is saved in `settings.json`, the password never is) |
| `--password PASS` | the hidden password prompt. Avoid it: the password ends up in your shell history. |
| `--port COM5` | the Bluetooth COM port prompt (normally pre-filled by auto-detection) |
| `--drive E:\` | waiting for the Pico's drive to appear |
| `--firmware my.uf2` | the bundled generic firmware (for example, your own build) |
| `--output configured.uf2` | flashing. Writes the configured file instead, which you then drag onto the Pico yourself. It contains your Wi‑Fi password, so delete it afterwards. |
| `--new-key` | reusing the saved key (rotates it) |
| `--allow-unsigned` | the default of rejecting unsigned packets. Not recommended: pair it with `--insecure` when running. |
| `HOST` (positional) | `multiput.local` as the saved Pico address, e.g. `multiput --setup 192.168.1.50` |

Example: `multiput --setup --link wifi --ssid HomeNet --drive E:\`

## Overriding at run time
- `multiput 192.168.1.50`: use this IP instead of the saved address, for networks that block `.local` names.
- `multiput --update`: update the Pico's firmware (the bundled `firmware/multiput.bin`, or `--firmware FILE.bin`) and optionally its Wi‑Fi network (`--ssid`/`--password` skip the prompts), over the current link. It needs firmware 0.3.0 or newer on the Pico; older firmware gets a USB setup once. Protocol and safety details are in `pico/multiput_pico/ota.h`.
- `multiput --pico-status`: show the Pico's firmware version and diagnostics text (firmware 0.3.1 and newer): whether it holds Bluetooth pairing keys, and the outcome of the last save before an update and the last restore after one. It's the unsigned `STATUS` request in `protocol.h`, and it contains no key material.
- `multiput --perf-test`: measure the round trip over each link (see [Performance](performance.md)). It refuses to run alongside multiput; a named mutex (`Local\multiput`) stops two copies running at once.
- `multiput --link wifi` / `--link bt`: switch link; remembered as the default. The Pico listens on both (see the README).
- `multiput --bt COM5`: use Bluetooth on this port, skipping auto-detection. Without it, multiput finds the port of the paired device named `multiput`: Windows stores the device's Bluetooth address under `HKLM\SYSTEM\CurrentControlSet\Services\BTHPORT\Parameters\Devices`, and the outgoing COM port's hardware ID contains that address. It falls back to the saved port if that fails.
- `multiput --controller 1`: use this XInput slot (0–3). Without it, multiput uses the first connected controller and picks again if that one disconnects.
- `multiput --remap XBOX=SWITCH ... PAUSE=A+B,C PAUSE_HOLD=0.5 PAUSE_KEY=CTRL+ALT+P BEEP=OFF STICKY=A TURBO=B`: change the button mapping and pause combos (saved as `"buttons"`, `"pause"`, `"pause_hold"`, `"pause_key"`, `"beep"`, `"sticky"` and `"turbo"` in `settings.json`, only where they differ from the default; `"pause"` is a list of combos, and the older single-combo form `["XBOX"]` is still read). `--remap` alone opens the interactive editor, or just prints the mapping when there's no console. Pressing M in the running multiput window opens the same editor, and changes there apply immediately. `reset` clears everything. See the README's Mapping section for names.
- `multiput --insecure`: send unsigned packets. The Pico must have been set up with `--allow-unsigned`.
- `multiput --config-dir DIR`: keep the key and settings somewhere other than `%APPDATA%\multiput`, for example to run two separate setups.

## Running from source
Python 3.11+ on Windows (older versions poll the controller too slowly); Bluetooth also needs `pip install pyserial`. Build the firmware first (below), then:
```
python pc\multiput.py --setup
python pc\multiput.py
```
For a clickable icon without the installer, double-click `multiput.bat` in the repo root, or right-click it → **Send to → Desktop (create shortcut)**. It passes options through, e.g. `multiput.bat --setup`, and keeps the window open if something fails.

## Building
The README's [Building from source](../README.md#building-from-source) covers the scripted build (`tools\build.bat`, or each step on its own). Details:
- **Firmware:** `tools/build_firmware.sh` installs `arduino-cli` into `~/.local/bin` and the rp2040 board core on first use. It passes the board URL on the command line, so your `arduino-cli` config isn't changed. Set `ARDUINO_CLI` to use a different `arduino-cli`. It warns if the installed core isn't the tested version (6.3.2). After building, it checks that the settings block landed in flash at 147 bytes.
- **From the Arduino IDE:** open `pico/multiput_pico/multiput_pico.ino` and select board **Raspberry Pi Pico W** and USB Stack **Adafruit TinyUSB**. IP/Bluetooth Stack **IPv4 + Bluetooth** (the firmware uses both, so any other stack option stops the compile with an error saying so), and Flash Size **2MB (Sketch: 1MB, FS: 1MB)**. The storage area holds the Pico's settings and incoming over-the-air updates. Use Sketch → Export Compiled Binary, then configure the result with `multiput --setup --firmware <file>.uf2`. Uploading straight from the IDE gives a blank firmware (triple blink).
- **Installer:** `tools\build_installer.bat` builds `multiput.exe` with PyInstaller in `build\venv`, then the installer from `tools/multiput.iss`, installing Inno Setup with winget if needed. To release a new version, bump `AppVersion` in `tools/multiput.iss`.
- **Logs** (all in `build\logs\`, replaced on each run):
  - `build.log`: everything `tools\build.bat` prints. It's written through PowerShell, because `cmd` can't show output and save it at the same time. Use `tools\build.bat --no-log` to skip it.
  - `firmware.log`: the full compiler output, also written when `tools/build_firmware.sh` runs on its own.
  - PyInstaller's missing-module report is in `build\work\multiput\warn-multiput.txt`.
- **Line endings:** `.gitattributes` keeps `*.sh` as LF and `*.bat` as CRLF, since each breaks with the other's line endings.

## Versioning and releases
multiput uses [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`, starting at 0.1.0. While below 1.0, the PC–Pico protocol may still change.

| Bump | When |
|---|---|
| **MAJOR** | The PC and a Pico on the previous version can no longer work together, e.g. a protocol or settings-block change. Below 1.0, bump MINOR for these instead. |
| **MINOR** | New features that stay compatible. |
| **PATCH** | Fixes only. |

**One source of truth:** the `VERSION` file at the repo root. It feeds:
- `multiput --version` and the startup banner, through `pc/version.py`. The file is bundled into `multiput.exe`.
- the installer's version and file name (`multiput-setup-<version>.exe`), passed to Inno Setup by `tools/build_installer.bat`.

- the firmware: `tools/build_firmware.sh` compiles it in (`-DMULTIPUT_VERSION=X.Y.Z`; a version like `0.2.0` is a single preprocessor token, so it needs no quoting). The Pico reports it when asked (a `VERSION` request; see `protocol.h`), and multiput compares it with its own version once per Pico session. Firmware 0.1.0 predates this and never answers, so multiput says it's "0.1.0 or older". Builds from the Arduino IDE report `dev`.

**Releasing:**
1. Merge the pull request. It already carries the `VERSION` bump and its `CHANGELOG.md` section (see [Contributing](#contributing)), so there's no separate release PR. Then update your local `main`: `git switch main && git pull`.
2. In WSL, run `tools/release.sh`. It needs the GitHub CLI (`gh`), signed in with push access. It:
   - checks that `VERSION` and the changelog agree, nothing is uncommitted, and `main` matches GitHub;
   - builds and tests everything with `tools\build.bat`;
   - tags `vX.Y.Z` and pushes the tag;
   - creates the GitHub release with notes from the changelog and SHA-256 checksums;
   - attaches the installer and `multiput.uf2`, then downloads them back to check them.

**Releases only come from `main`:** a real run refuses to start on any other branch, or on a detached HEAD such as a checked-out tag, and names where you are. Just before tagging and publishing, after the build, it checks again that you're still on `main` at the same commit. The commit must also be the current tip of `origin/main`.

`tools/release.sh --dry-run` does the build and writes `build/release-notes.md`, without changing anything on GitHub. It works on any branch, with a note that a real release needs `main`.

**Republishing** (for example after a broken upload, or to fix the notes): run `tools/release.sh` again on the same commit. It rebuilds, replaces the files and notes on the existing release, and leaves the tag alone. If the tag already points at a different commit, the script refuses: a published version shouldn't change contents, so bump `VERSION` and release that instead.

## Tests (WSL/Linux; need Python 3, gcc/g++, and the rp2040 core)
`tools/run_tests.sh` runs them all:
- `python3 tests/test_protocol.py`: the PC's real signing code against the Pico's `protocol.h`, compiled on the desktop with the core's own BearSSL.
- `python3 tests/test_setup.py`: settings patching (including the built `.uf2` files) and the `--setup` flow.
- `python3 tests/test_controller.py`: button mapping, `--remap`, pause combos, and M-key editing.
- `python3 tests/test_perf.py`: the performance test's measuring logic, against a fake Pico.
- `python3 tests/test_release.py`: release notes generation.
