# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Arsmillis (https://github.com/Arsmillis/multiput)
"""The two ways the PC reaches the Pico: UDP over Wi-Fi, or Bluetooth serial (COM port).

Both have the same small interface used by protocol.Session: send(bytes),
recv() -> bytes (never blocks), reconnect(). I/O errors are treated as lost
packets; the session notices the silence and calls reconnect().
"""

import socket
import sys
import time

import events

PORT = 41234
RETRY_S = 2.0  # how often to retry reaching the Pico at startup
# Receive buffer: larger than any UDP datagram. On Windows a datagram bigger than the buffer
# raises WSAEMSGSIZE and is lost (Linux would truncate it instead).
MAX_DATAGRAM = 65536

class Stopped(Exception):
    """Connecting was abandoned because `stop` was set (the tray app needs the link back)."""


def retry(connect, message, stop=None):
    """Call connect() until it succeeds, so multiput can be started before the Pico is up.
    stop: a threading.Event that abandons the attempt (raises Stopped)."""
    printed = False
    while True:
        if stop is not None and stop.is_set():
            raise Stopped()
        try:
            return connect()
        except OSError:
            if not printed:
                events.say(message + " (Ctrl+C to stop)", events.INFO)
                printed = True
            if stop is not None:
                stop.wait(RETRY_S)
            else:
                time.sleep(RETRY_S)

class UdpLink:
    def __init__(self, host, stop=None):
        self.host = host
        self.addr = (retry(lambda: socket.gethostbyname(host), f"Looking for the Pico at {host}...", stop), PORT)
        self.name = f"{host} ({self.addr[0]}:{PORT})"
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False)

    def reconnect(self):
        """Look the Pico up again: after a reboot it may have a new IP address."""
        try:
            ip = socket.gethostbyname(self.host)
        except OSError:
            return  # not back yet; the session tries again at its next timeout
        if ip != self.addr[0]:
            print(f"The Pico is now at {ip}.")
            self.addr = (ip, PORT)

    def send(self, data):
        try:
            self.sock.sendto(data, self.addr)
        except OSError:
            pass  # network briefly down: same as a lost packet; the Pico releases inputs

    def recv(self):
        out = b""
        while True:
            try:
                data, src = self.sock.recvfrom(MAX_DATAGRAM)
            except OSError:  # nothing waiting (or Windows reporting an earlier unreachable send)
                return out
            if src[0] == self.addr[0]:
                out += data

    def close(self):
        self.sock.close()

BT_NAME = "multiput"  # the name the Pico advertises (pico/multiput_pico/transport_bt.h)
PAIRED_DEVICES_KEY = r"SYSTEM\CurrentControlSet\Services\BTHPORT\Parameters\Devices"


def match_bt_port(paired, ports, name=BT_NAME):
    """The COM port for the paired device called `name`.
    paired: {bluetooth address: device name}; ports: [(device, hwid)]. Windows gives a
    paired serial device two ports; the outgoing one (the one to open) has the device's
    address in its hwid, while the incoming one has an all-zero address."""
    addresses = [addr.upper() for addr, n in paired.items() if n == name]
    for device, hwid in ports:
        if any(addr in hwid.upper() for addr in addresses):
            return device
    return None


def find_bt_port():
    """Auto-detect the Pico's COM port (Windows, pyserial). None if not found."""
    try:
        import winreg
        from serial.tools import list_ports
        paired = {}
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, PAIRED_DEVICES_KEY) as devices:
            for i in range(winreg.QueryInfoKey(devices)[0]):
                addr = winreg.EnumKey(devices, i)
                try:
                    with winreg.OpenKey(devices, addr) as d:
                        paired[addr] = bytes(winreg.QueryValueEx(d, "Name")[0]).rstrip(b"\0").decode(errors="replace")
                except OSError:
                    pass  # a device without a stored name
        return match_bt_port(paired, [(p.device, p.hwid or "") for p in list_ports.comports()])
    except (ImportError, OSError):
        return None


class SerialLink:
    def __init__(self, port, stop=None):
        try:
            import serial
        except ImportError:
            sys.exit("Bluetooth mode needs pyserial: pip install pyserial")
        self.name, self.serial = port, serial
        self.ser = retry(self._open, f"Connecting to the Pico over Bluetooth ({port})...", stop)

    def _open(self):
        return self.serial.Serial(self.name, timeout=0, write_timeout=1)

    # I/O errors (link dropped, port closed) count as lost packets; the session
    # notices the silence and calls reconnect().
    def send(self, data):
        try:
            self.ser.write(data)
        except OSError:
            pass

    def recv(self):
        try:
            return self.ser.read(256)
        except OSError:
            return b""

    def close(self):
        try:
            self.ser.close()
        except OSError:
            pass

    def reconnect(self):
        try:
            self.ser.close()
        except OSError:
            pass
        try:
            self.ser = self._open()
        except OSError:
            pass  # Pico not reachable yet; the session tries again at its next timeout
