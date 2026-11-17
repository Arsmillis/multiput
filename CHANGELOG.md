# Changelog

All notable changes are listed here. Versions follow [Semantic Versioning](https://semver.org/); see `docs/development.md` (Versioning and releases) for when each number goes up.

## [Unreleased]

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
