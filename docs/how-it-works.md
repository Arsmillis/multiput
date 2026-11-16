# How multiput works

## Why a Pico W fits this job

The device next to the Switch has three jobs, and the Pico W handles each of them in hardware:

| Job | What it needs | What the Pico W has |
|---|---|---|
| Appear to the Switch 2 as a controller | Built-in **USB device** support with your own descriptors, so you control the name, IDs and report format | The RP2040 chip has a built-in USB 1.1 port that can act as a device. TinyUSB lets it claim to be a "HORIPAD S", polled every 1 ms. |
| Receive inputs from the PC wirelessly | Some radio link | An Infineon CYW43439 chip with 2.4 GHz Wi‑Fi (802.11n) and Bluetooth 5.2 |
| Stay up while plugged in | Power from the USB port, nothing to manage | Draws roughly 50–100 mA with Wi‑Fi on, well within what a dock port supplies |

It also costs about $6, flashes from the Arduino IDE, and has a well-supported Arduino core.

The key requirement is the first one. Many cheap boards can't present themselves as a USB device:
- **Arduino Uno and classic ESP32:** no native USB, so they can't do it at all.
- **Arduino Pro Micro / Leonardo:** USB works, but there's no radio, so you'd need a wire to the PC.
- **ESP32‑S3:** native USB plus Wi‑Fi. It's an equally good choice; the Pico W just has the more common Arduino path for this.
- **Raspberry Pi Zero 2 W:** can do it, but it runs full Linux. It takes about 20 s to boot, needs an SD card, and is more likely to break.

## Hardware requirements

**Wi‑Fi: recommended.** It must be a 2.4 GHz network, because the CYW43439 has no 5 GHz support. The PC can be on 5 GHz or wired Ethernet as long as both are on the same local network. Throughput is trivial: a 34-byte signed packet each time something changes, plus one every 50 ms.

**Bluetooth: built in, used when you choose it.** The firmware listens on both Wi‑Fi and Bluetooth, and multiput picks one (see the README's Wi‑Fi or Bluetooth section). Your Xbox controller's own Bluetooth connection is to the PC, not to the Pico.

**Memory: not a concern.**
- **Storage:** the Pico W has 2 MB of flash. The firmware is about 535 KB (25%), and most of that is the radio chip's own firmware and the Wi‑Fi and Bluetooth stacks. Our code is a few KB.
- **RAM:** it has 264 KB. The firmware uses about 100 KB (38%), mostly network and Bluetooth buffers; the controller state is 8 bytes.

**CPU: not a concern.** It has two 133 MHz cores and uses only one, which spends nearly all its time idle.

**Physical:**
- The Pico W has a **micro‑USB** port. You need a micro‑USB to USB‑A data cable for the dock (some cheap cables only carry power, and those won't work).
- In handheld mode you'd plug into the Switch 2's USB‑C port with a USB‑C OTG adapter. This hasn't been verified.

**PC side:**
- A Windows PC. The installer includes everything; XInput is built into Windows.
- The Xbox controller connected by USB, the Xbox Wireless Adapter, or Bluetooth.

## End to end, from your seat

**One-time setup (about 5 minutes)**
1. Run the multiput installer. It adds a desktop shortcut and then starts setup.
2. Type your Wi‑Fi name and password. Hold BOOTSEL on the Pico and plug it into the PC. Setup writes your settings into the firmware and flashes it.

**Each session**
1. Plug the Pico into the dock and turn on the Switch.
   - The LED **blinks fast** for a few seconds while it joins Wi‑Fi.
   - It then **blinks slowly**: it's on Wi‑Fi and the Switch now sees a wired controller, but no input is arriving yet.
2. Turn on the Xbox controller. Windows and PC games pick it up as usual.
3. On the PC, double-click the **multiput** desktop shortcut. Its window shows:
   ```
   Sending controller 0 to multiput.local (192.168.1.50:41234). Ctrl+C or close this window to stop.
   Waiting for the Pico...
   Pico session started.
   Controller connected.
   ```
   The Pico's LED turns **solid**.
4. On the Switch, the new wired controller works like any wired pad. Press A in a menu and it registers.
5. Now every press goes to both devices. Pressing A in a PC game triggers A there, and the same press reaches the Switch a few milliseconds later. multiput can sit in the background, since XInput doesn't need focus.

**What happens to one press of A**
```
thumb → controller → PC          1–8 ms  (USB/Bluetooth; the PC game sees it here)
script polls XInput and signs    ≤1 ms
UDP over Wi-Fi → router → Pico   ~2–5 ms usually; occasional spikes on a busy network
Pico sends the next USB report   ≤1 ms
Switch game reads it next frame  0–16 ms (that part happens with any controller)
```

The Pico turns off Wi‑Fi power saving (`WiFi.noLowPowerMode()`), which would otherwise hold back incoming packets by tens of milliseconds.
