# Changelog

All notable changes are listed here. Versions follow [Semantic Versioning](https://semver.org/); see `docs/development.md` (Versioning and releases) for when each number goes up.

## [Unreleased]

## [0.7.0] - 2026-11-19
### Added
- PlayStation (DualShock 4, DualSense), Switch Pro and generic controllers, read through SDL 2 (bundled). Xbox controllers stay on XInput.
  - multiput uses the first controller that connects, Xbox controllers first, and keeps it until it disconnects.
  - Every controller uses the Xbox button names in the mapping, by position; Switch Pro buttons map by label, so A presses A on the Switch.
  - A controller whose layout SDL doesn't know is reported once.
### Changed
- The tray's tooltip shows the controller in use on its own line, under the status (e.g. "DualSense Wireless Controller", or "Xbox-compatible controller (slot 0)"), and "multiput" on a line of its own.
- Status messages name the controller: "Controller connected: Xbox-compatible controller (slot 0)." instead of "Controller connected (slot 0)."
- `--controller N` now means "only this Xbox controller", and leaves other controllers out.

## [0.6.0] - 2026-11-18
### Added
- Mapping by pressing buttons: in the mapping editor (tray menu, Start menu, M key, or `multiput --remap`):
  - press a button on the controller to remap it, then pick what it sends from a numbered list (typing changes still works at the same prompt);
  - type **P**, then hold a pause combo on the controller and let go to record it, as another combo or replacing the current ones.

  Buttons already held when the editor opens are ignored until released.
### Changed
- The tray's Button mapping now stops sending to the console while the editor is open (as the M key already did), so buttons pressed to remap them don't reach the console. A pause that was on stays on afterwards, also after Update, Performance test and Pico status.

## [0.5.1] - 2026-11-18
### Fixed
- The tray icon stayed on "W" (busy) after Update the Pico, Performance test or Pico status finished, even once input was reaching the console again.

## [0.5.0] - 2026-11-17
### Added
- multiput runs in the system tray (`multiputw.exe`, opened by the desktop and Start menu shortcuts):
  - **icon:** a letter on a coloured square: **C** green (connected and sending), **W** orange (waiting, reconnecting, or busy), **P** grey (paused), **F** red (failed); hover for details;
  - **notifications** for losing and regaining contact with the Pico, pause and resume, a disconnected controller, and outdated Pico firmware;
  - **menu:** pause, switch link, button mapping (applied as soon as the editor closes), update the Pico, performance test, Pico status, open the log, and quit. Tasks that need the Pico to themselves open in a console window, and the tray reconnects when they finish.

  The console version is still there (Start menu: multiput (console window)). Output from the tray version goes to `%APPDATA%\multiput\multiput.log`.

## [0.4.1] - 2026-11-17
### Changed
- multiput uses the first connected controller, in any of the four XInput slots, instead of always slot 0. If it disconnects, multiput picks the next one it finds. `--controller N` still pins a slot.

## [0.4.0] - 2026-11-17
### Added
- Pause with the keyboard: Ctrl+Alt+P pauses or resumes sending to the console, even while a game has focus. Change it with `PAUSE_KEY=` (e.g. `SHIFT+F12`, or `NONE`).
- Adjustable pause hold time with `PAUSE_HOLD=` (seconds; `0` pauses with a single tap of the combo).
- `BEEP=OFF` silences the pause and resume beep.
- Sticky buttons (`STICKY=A,LT`): tap once to hold the button on the console, tap again to release. For players who can't hold a button down.
- Turbo buttons (`TURBO=B`): while held, the console sees 10 presses a second.
- All of these are set in the mapping editor (M key, Start menu, or `multiput --remap`) and take effect immediately with the M key.

## [0.3.1] - 2026-11-16
### Added
- `multiput --pico-status` shows the Pico's firmware version and diagnostics, such as whether it holds Bluetooth pairing keys and what happened to them at the last update.

### Fixed
- Replies from the Pico over Wi‑Fi longer than 64 bytes were silently dropped on Windows. Until now, every reply fit in 64 bytes.
- A firmware update no longer resets the Pico's Bluetooth pairing. The Pico saves its pairing keys before installing an update and restores them afterwards, so Windows reconnects straight away instead of re-pairing for about a minute. This takes effect for updates *from* 0.3.1 on: updating a 0.3.0 Pico to 0.3.1 still resets the pairing once.

## [0.3.0] - 2026-11-16
### Added
- Over-the-air updates: `multiput --update` (Start menu: multiput update) installs new firmware and can change the Wi‑Fi network while the Pico stays in the dock, over Wi‑Fi or Bluetooth. Updates are signed with your key and checked as a whole before installing, Wi‑Fi details are encrypted, and a failed update leaves the current firmware running.

### Changed
- The Pico keeps its settings in its own flash storage, so updates no longer need the Wi‑Fi password again.
- New flash layout (1 MB firmware, 1 MB storage). Coming from 0.2.0 or earlier, run multiput setup over USB once; after that, updates work in place.

### Fixed
- The firmware version check could wrongly say "0.1.0 or older" after a reconnect: the Pico dropped the version request under its reply rate limit, and multiput only asked once. Version replies now have their own rate limit, and multiput asks again before concluding anything.

## [0.2.0] - 2026-11-16
- `tools/release.sh` to publish or republish a GitHub release (with `--dry-run`).
- The Pico firmware reports its version, and multiput says when the firmware is older (or newer) than itself. Firmware 0.1.0 can't report one, so multiput suggests updating it.

## [0.1.0] - 2026-11-16
First release.

### Added
- Mirror one Xbox (XInput) controller to the PC and a console: the controller stays connected to the PC, and a Pico W in the console's USB port shows up there as a wired HORIPAD S controller. Tested on the Nintendo Switch 2.
- One Pico firmware for Wi‑Fi and Bluetooth; the PC picks the link with `--link`, and the Pico pauses the idle link so they don't compete for the radio.
- Signed input (HMAC-SHA256) with per-boot sessions and replay protection.
- Guided setup that configures and flashes the Pico, remembers the Wi‑Fi name, and auto-detects the Bluetooth COM port.
- Button remapping and pause combos (several alternatives), from setup, the Start menu, `--remap`, or the M key while running.
- Automatic reconnect after Wi‑Fi or Bluetooth drops.
- Performance test (`--perf-test`) measuring both links.
- Windows installer with Start menu and desktop shortcuts.
