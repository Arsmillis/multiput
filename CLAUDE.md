# CLAUDE.md

Guidance for Claude Code and other contributors working in this repo. The [README](README.md) covers using multiput; [docs/development.md](docs/development.md) covers options, building, tests and releasing in full.

## What this is
multiput sends one controller's input to the PC and a console at once:
- **The Windows program** (`pc/`, Python) reads the controller (Xbox through XInput, others through SDL) and sends signed input to a Pico W.
- **The Pico W** (`pico/multiput_pico/`, Arduino with the arduino-pico core) shows up on the console as a wired HORIPAD S controller.
- **Links:** Wi‑Fi (UDP, `multiput.local`) or Bluetooth (an SPP COM port).
- **Tested console:** Nintendo Switch 2.

## Workflow (required)
- **Never push to `main`.** Work on a branch (`feature/...`, `fix/...`, `docs/...`), push it, and open a pull request with `gh pr create`. Don't merge it: the maintainer merges and releases.
- **Feature and fix PRs ship a release.** In the same PR:
  - set `VERSION` (MINOR for features, PATCH for fixes, MAJOR only after 1.0 for incompatible changes);
  - add the change under `## [X.Y.Z] - YYYY-MM-DD` in `CHANGELOG.md`, using the expected release date. If another open PR already bumped to that version, add to its section.
- **Documentation-only PRs need no release:** don't change `VERSION`, and don't add a changelog entry. That covers the README, `docs/`, `CLAUDE.md`, `TODO` and comments.
- **Releasing** is the maintainer's job: `tools/release.sh` after merging. It refuses to run off `main`, or when local `main` differs from `origin/main`.
- **Every source file** starts with the SPDX licence and copyright header (Apache-2.0, Copyright (C) 2026 Arsmillis).

## Commands
The repo is on a Windows drive (`S:\Projects\multiput`, which WSL sees as `/mnt/s/Projects/multiput`), so WSL and Windows share it.
- **Tests (WSL):** `tools/run_tests.sh` runs all the suites. They need gcc/g++ and the arduino-pico core in `~/.arduino15`.
- **Full build (from WSL):** `cmd.exe /c "tools\build.bat"`. It builds the firmware, runs the tests, then builds `multiput.exe`, `multiputw.exe` and the installer. Output goes to `build/` (git-ignored), with logs in `build/logs/`.
- **Firmware only:** `tools/build_firmware.sh`.
- **From source on Windows:** `py pc\multiput.py` (console), or `pythonw pc\multiput.py --tray`. Bluetooth needs pyserial and non-Xbox controllers need pysdl2 + pysdl2-dll; `build\venv\Scripts\python.exe` has them.

## The maintainer's hardware
Their Pico W is in a Switch 2 dock, reachable as `multiput.local` over Wi‑Fi and on COM5 over Bluetooth. Their key and settings are in `%APPDATA%\multiput`.
- **Before building, check multiput isn't running** (`tasklist | findstr /i multiput`). A running `build\dist` exe can't be replaced.
- **Never send signed input to the real Pico while their multiput runs.** Two senders fight over the signing counter. For smoke tests of the main loop, use a throwaway `--config-dir` and host `127.0.0.1`.
- **Ask before opening a Bluetooth connection to the Pico.** If its pairing was reset, Windows pops up pairing prompts. Prefer Wi‑Fi, and `--pico-status` for diagnostics.
- **Leave hardware and visual checks to the maintainer** (the tray icon, notifications, input on the Switch). List them as unchecked items in the PR's test plan.

## Gotchas learned the hard way
- **Windows-only steps:** setup, and anything using drive letters, must run in a Windows terminal, not WSL.
- **Line endings:** `.bat` files must stay CRLF and `.sh` files LF (enforced by `.gitattributes`).
- **`gh pr edit` fails** on GitHub's retired "Projects (classic)". Update PR descriptions with `gh api -X PATCH repos/Arsmillis/multiput/pulls/N -F body=@file`.
- **UDP on Windows:** a datagram bigger than the receive buffer is dropped (`WSAEMSGSIZE`), while Linux truncates it, so the Linux tests can't catch this.
- **The packaged exe buffers plain `print` output** when piped (it ignores `PYTHONUNBUFFERED`). Status messages go through `events.say`, which flushes; time things from source with `python -u`.
- **Bluetooth on the Pico:**
  - arduino-pico starts Bluetooth, including its key store, before `setup()`;
  - the pairing keys live inside the firmware image, so `ota.h`/`multiput_pico.ino` save and restore them across updates.
- **Keep the PC and Pico in sync:**
  - the wire protocol: `pc/protocol.py` and `pc/updater.py` against `protocol.h` and `ota.h`; `tests/test_protocol.py` and `tests/test_ota.py` check them against each other;
  - the 147-byte settings block: `pc/firmware.py` against `settings.h`.
