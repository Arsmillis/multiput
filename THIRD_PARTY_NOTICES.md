# Third-party notices

multiput's own code is under the Apache License 2.0 (see `LICENSE` and `NOTICE`). The built files also contain other people's code under their own licenses.

## Pico firmware (`multiput.uf2`)
Built with the [arduino-pico](https://github.com/earlephilhower/arduino-pico) core, which links these into the firmware:

| Component | License |
|---|---|
| arduino-pico core (Earle F. Philhower, III) | LGPL 2.1. multiput's full source and build scripts are public, so you can rebuild the firmware with a modified core. |
| Raspberry Pi Pico SDK (Raspberry Pi Ltd) | BSD 3-Clause |
| Adafruit TinyUSB (Ha Thach for Adafruit Industries) | MIT |
| BearSSL (Thomas Pornin) | MIT |
| lwIP (Swedish Institute of Computer Science) | BSD 3-Clause |
| BTstack (BlueKitchen GmbH) | BTstack license, used under Raspberry Pi's licence grant for Pico W / Pico 2 W hardware (`pico-sdk/src/rp2_common/pico_btstack/LICENSE.RP`) |
| CYW43 Wi‑Fi/Bluetooth driver (George Robotics Pty Ltd) | Raspberry Pi licence (`pico-sdk/lib/cyw43-driver/LICENSE.RP`) |

**Hardware restriction:** under the BTstack and CYW43 grants, the firmware may only be used with Raspberry Pi hardware (the Pico W, as multiput intends). Each component's full license text ships with the arduino-pico core and the Pico SDK.

## Windows program (`multiput.exe` and the installer)
| Component | License |
|---|---|
| Python runtime (Python Software Foundation) | PSF License 2.0 |
| pySerial (Chris Liechti) | BSD 3-Clause |
| SDL 2 (Sam Lantinga and contributors), from pysdl2-dll | zlib |
| PySDL2 (Marcus von Appen and contributors) | Public domain (CC0), or zlib where that isn't recognised |
| PyInstaller bootloader | GPL 2.0 with the bootloader exception, which allows distributing bundled programs under their own license |
