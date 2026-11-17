# Changelog

All notable changes are listed here. Versions follow [Semantic Versioning](https://semver.org/); see `docs/development.md` (Versioning and releases) for when each number goes up.

## [Unreleased]

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
