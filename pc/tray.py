# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Arsmillis (https://github.com/Arsmillis/multiput)
"""multiput in the system tray (multiputw.exe, or `multiput --tray`).

The mirroring loop (multiput.run_loop) runs on a worker thread; this module shows its
status as the tray icon's colour and tooltip, raises notifications for what matters, and
offers a menu. Tasks that need the Pico to themselves (update, performance test, status)
run the console multiput in its own window: the tray releases the link first and takes
it back when that window closes.

Three layers: TrayState (pure: events -> icon, tooltip, notifications; tested on Linux),
TrayIcon (the Win32 tray icon and menu, through ctypes; no extra dependencies), TrayApp
(ties them to the worker thread and the menu actions).
"""

import ctypes
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

import events
import links

GREEN, AMBER, GREY, RED = (0x2E, 0xB8, 0x4F), (0xF0, 0x8C, 0x00), (0x80, 0x80, 0x80), (0xD9, 0x30, 0x25)


class TrayState:
    """What the icon should show, from the events the loop emits."""

    def __init__(self, link_name="the Pico"):
        self.link_name = link_name
        self.pico, self.controller, self.paused, self.error = None, None, False, None  # controller: its name
        self.busy = False  # a console task (update, performance test, status) has the Pico

    def on_event(self, text, kind, subject=None):
        """Update from an event; returns (title, message, warning) to notify, or None."""
        if kind == events.PICO_UP:
            was_lost = self.pico == "lost"
            self.pico, self.error = "up", None
            if was_lost:
                return "Reconnected", "multiput is reaching the Pico again.", False
        elif kind == events.PICO_LOST:
            self.pico = "lost"
            return "Lost contact with the Pico", "Reconnecting... Inputs on the console are released meanwhile.", True
        elif kind == events.CONTROLLER_UP:
            self.controller = subject or "a controller"
        elif kind == events.CONTROLLER_LOST:
            notify = self.controller
            self.controller = None
            if notify:
                return "Controller disconnected", "multiput will use the next controller that connects.", True
        elif kind == events.PAUSED:
            self.paused = True
            return "Paused", text, False
        elif kind == events.RESUMED:
            self.paused = False
            return "Resumed", "Sending to the console again.", False
        elif kind == events.FIRMWARE_UPDATE:
            return "Pico firmware", text, False
        elif kind == events.WARNING:
            return "multiput", text, True
        return None

    def fail(self, text):
        self.error, self.pico = text, None

    def badge(self):
        """(letter, colour) for the icon: C connected, W waiting, P paused, F failed."""
        if self.error:
            return "F", RED
        if self.busy:
            return "W", AMBER
        if self.paused:
            return "P", GREY
        if self.pico == "up" and self.controller:
            return "C", GREEN
        return "W", AMBER

    def status_lines(self):
        """The status, and the controller in use (when there is one)."""
        if self.error:
            status = f"Stopped: {self.error}"
        elif self.busy:
            status = "Busy in another window"
        elif self.paused:
            status = "Paused: the console gets no input"
        elif self.pico == "lost":
            status = "Reconnecting to the Pico..."
        elif self.pico != "up":
            status = f"Looking for the Pico over {self.link_name}..."
        elif not self.controller:
            status = "Waiting for a controller"
        else:
            status = f"Sending to the console over {self.link_name}"
        lines = [status]
        if self.controller and not (self.error or self.busy):
            lines.append(self.controller)
        return lines

    def tooltip(self):
        """Hovering the icon: multiput, then the status lines."""
        return "\n".join(["multiput", *self.status_lines()])[:127]  # the tray's limit


def console_command(*args):
    """How to start the console multiput (for the editor, updates and so on)."""
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).with_name("multiput.exe")), *args]
    python = Path(sys.executable)
    if python.name.lower() == "pythonw.exe":
        python = python.with_name("python.exe")
    return [str(python), str(Path(__file__).with_name("multiput.py")), *args]


def rounded_square(x, y, size):
    """How much of pixel (x, y) the icon's rounded square covers (0..1, smoothed edges)."""
    radius, half = size * 0.22, size / 2
    dx = max(abs(x + 0.5 - half) - (half - radius), 0)
    dy = max(abs(y + 0.5 - half) - (half - radius), 0)
    return max(0.0, min(1.0, radius + 0.5 - (dx * dx + dy * dy) ** 0.5))


# ---- Win32 ------------------------------------------------------------------------------

WM_DESTROY, WM_COMMAND, WM_CLOSE, WM_USER = 0x0002, 0x0111, 0x0010, 0x0400
WM_LBUTTONUP, WM_RBUTTONUP, WM_CONTEXTMENU = 0x0202, 0x0205, 0x007B
WM_TRAY, WM_REFRESH = WM_USER + 1, WM_USER + 2
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x1, 0x2, 0x4, 0x10
NIIF_INFO, NIIF_WARNING = 0x1, 0x2
MF_STRING, MF_GRAYED, MF_CHECKED, MF_SEPARATOR, MF_POPUP = 0x0, 0x1, 0x8, 0x800, 0x10
TPM_RETURNCMD, TPM_RIGHTBUTTON = 0x100, 0x2


class TrayIcon:
    """A tray icon with a menu, on the calling thread's message loop. menu() returns
    [(id, label, flags) | None for a separator | (label, [submenu...])]; on_command(id)
    runs on this thread. Other threads call refresh() to update the icon and notify()."""

    def __init__(self, menu, on_command):
        from ctypes import wintypes as w
        self.w, self.menu, self.on_command = w, menu, on_command
        self.user32, self.shell32 = ctypes.WinDLL("user32", use_last_error=True), ctypes.WinDLL("shell32")
        self.gdi32, kernel32 = ctypes.WinDLL("gdi32"), ctypes.WinDLL("kernel32")
        lresult = ctypes.c_ssize_t
        self.WNDPROC = ctypes.WINFUNCTYPE(lresult, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
        self.user32.DefWindowProcW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
        self.user32.DefWindowProcW.restype = lresult
        self.user32.CreateWindowExW.restype = w.HWND
        self.user32.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, ctypes.c_int, ctypes.c_int,
                                                ctypes.c_int, ctypes.c_int, w.HWND, w.HMENU, w.HINSTANCE, w.LPVOID]
        self.user32.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
        self.user32.CreatePopupMenu.restype = w.HMENU
        self.user32.AppendMenuW.argtypes = [w.HMENU, w.UINT, ctypes.c_size_t, w.LPCWSTR]
        self.user32.TrackPopupMenu.argtypes = [w.HMENU, w.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.HWND,
                                               w.LPVOID]
        self.user32.DestroyMenu.argtypes = [w.HMENU]
        self.user32.DestroyWindow.argtypes = [w.HWND]
        self.user32.SetForegroundWindow.argtypes = [w.HWND]
        self.gdi32.CreateDIBSection.restype = w.HBITMAP
        self.gdi32.CreateBitmap.restype = w.HBITMAP
        self.gdi32.CreateCompatibleDC.restype = w.HDC
        self.gdi32.CreateFontW.restype = w.HFONT
        self.gdi32.SelectObject.restype = w.HGDIOBJ
        self.gdi32.SelectObject.argtypes = [w.HDC, w.HGDIOBJ]
        self.gdi32.SetBkMode.argtypes = [w.HDC, ctypes.c_int]
        self.gdi32.SetTextColor.argtypes = [w.HDC, w.COLORREF]
        self.gdi32.DeleteObject.argtypes = [w.HGDIOBJ]
        self.gdi32.DeleteDC.argtypes = [w.HDC]
        self.user32.DrawTextW.argtypes = [w.HDC, w.LPCWSTR, ctypes.c_int, ctypes.POINTER(w.RECT), w.UINT]
        self.user32.CreateIconIndirect.restype = w.HICON

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [("style", w.UINT), ("lpfnWndProc", self.WNDPROC), ("cbClsExtra", ctypes.c_int),
                        ("cbWndExtra", ctypes.c_int), ("hInstance", w.HINSTANCE), ("hIcon", w.HICON),
                        ("hCursor", w.HANDLE), ("hbrBackground", w.HBRUSH), ("lpszMenuName", w.LPCWSTR),
                        ("lpszClassName", w.LPCWSTR)]

        class NOTIFYICONDATAW(ctypes.Structure):
            _fields_ = [("cbSize", w.DWORD), ("hWnd", w.HWND), ("uID", w.UINT), ("uFlags", w.UINT),
                        ("uCallbackMessage", w.UINT), ("hIcon", w.HICON), ("szTip", w.WCHAR * 128),
                        ("dwState", w.DWORD), ("dwStateMask", w.DWORD), ("szInfo", w.WCHAR * 256),
                        ("uVersion", w.UINT), ("szInfoTitle", w.WCHAR * 64), ("dwInfoFlags", w.DWORD),
                        ("guidItem", ctypes.c_byte * 16), ("hBalloonIcon", w.HICON)]

        self.NOTIFYICONDATAW = NOTIFYICONDATAW
        self._proc = self.WNDPROC(self._wndproc)  # keep a reference: Windows calls it
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSW(lpfnWndProc=self._proc, hInstance=hinst, lpszClassName="multiputTray")
        self.user32.RegisterClassW(ctypes.byref(wc))
        self.taskbar_created = self.user32.RegisterWindowMessageW("TaskbarCreated")
        self.hwnd = self.user32.CreateWindowExW(0, "multiputTray", "multiput", 0, 0, 0, 0, 0, None, None, hinst, None)
        self.icons = {}
        self.badge, self.tip, self.pending = ("W", AMBER), "multiput", []
        self._add()

    def _icon(self, badge):
        """A rounded square in the badge's colour with its letter in white, drawn into a
        32-bit icon (no image files needed)."""
        if badge in self.icons:
            return self.icons[badge]
        letter, (r, g, b) = badge
        size = self.user32.GetSystemMetrics(49) or 16  # SM_CXSMICON: follows the display scaling

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [(n, t) for n, t in [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                                           ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                                           ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                                           ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                                           ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                                           ("biClrImportant", ctypes.c_uint32)]]

        class ICONINFO(ctypes.Structure):
            _fields_ = [("fIcon", self.w.BOOL), ("xHotspot", self.w.DWORD), ("yHotspot", self.w.DWORD),
                        ("hbmMask", self.w.HBITMAP), ("hbmColor", self.w.HBITMAP)]

        header = BITMAPINFOHEADER(biSize=40, biWidth=size, biHeight=-size, biPlanes=1, biBitCount=32)
        bits = ctypes.c_void_p()
        colour_bmp = self.gdi32.CreateDIBSection(None, ctypes.byref(header), 0, ctypes.byref(bits), None, 0)
        pixels = (ctypes.c_uint32 * (size * size)).from_address(bits.value)
        coverage = [rounded_square(x, y, size) for y in range(size) for x in range(size)]
        for i, a in enumerate(coverage):
            pixels[i] = (r << 16) | (g << 8) | b
        # The letter, through GDI: bold, white, centred, smoothed against the background colour.
        dc = self.gdi32.CreateCompatibleDC(None)
        old_bmp = self.gdi32.SelectObject(dc, colour_bmp)
        font = self.gdi32.CreateFontW(-int(size * 0.78), 0, 0, 0, 700, 0, 0, 0, 1, 0, 0, 4, 0, "Segoe UI")
        old_font = self.gdi32.SelectObject(dc, font)
        self.gdi32.SetBkMode(dc, 1)                # transparent
        self.gdi32.SetTextColor(dc, 0x00FFFFFF)    # white
        rect = self.w.RECT(0, 0, size, size)
        self.user32.DrawTextW(dc, letter, -1, ctypes.byref(rect), 0x1 | 0x4 | 0x20)  # centre, vcentre, one line
        self.gdi32.GdiFlush()
        self.gdi32.SelectObject(dc, old_font)
        self.gdi32.SelectObject(dc, old_bmp)
        self.gdi32.DeleteObject(font)
        self.gdi32.DeleteDC(dc)
        # GDI clears the alpha of the pixels it drew: set every pixel's alpha from the shape.
        for i, a in enumerate(coverage):
            pixels[i] = (int(a * 255) << 24) | (pixels[i] & 0x00FFFFFF)
        mask = (ctypes.c_ubyte * (((size + 15) // 16) * 2 * size))()  # all zero: the alpha channel decides
        mask_bmp = self.gdi32.CreateBitmap(size, size, 1, 1, mask)
        info = ICONINFO(fIcon=True, hbmMask=mask_bmp, hbmColor=colour_bmp)
        self.icons[badge] = self.user32.CreateIconIndirect(ctypes.byref(info))
        return self.icons[badge]

    def _data(self, flags):
        nid = self.NOTIFYICONDATAW(cbSize=ctypes.sizeof(self.NOTIFYICONDATAW), hWnd=self.hwnd, uID=1, uFlags=flags,
                                   uCallbackMessage=WM_TRAY, hIcon=self._icon(self.badge))
        nid.szTip = self.tip
        return nid

    def _add(self):
        self.shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self._data(NIF_MESSAGE | NIF_ICON | NIF_TIP)))

    def refresh(self, badge, tip, notification=None):
        """Thread-safe: update the icon (badge: (letter, colour)) and tooltip, optionally with a notification."""
        self.badge, self.tip = badge, tip
        if notification:
            self.pending.append(notification)
        self.user32.PostMessageW(self.hwnd, WM_REFRESH, 0, 0)

    def _apply(self):
        self.shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self._data(NIF_ICON | NIF_TIP)))
        while self.pending:
            title, message, warning = self.pending.pop(0)
            nid = self._data(NIF_INFO)
            nid.szInfoTitle, nid.szInfo = title[:63], message[:255]
            nid.dwInfoFlags = NIIF_WARNING if warning else NIIF_INFO
            self.shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def _build(self, items):
        hmenu = self.user32.CreatePopupMenu()
        for item in items:
            if item is None:
                self.user32.AppendMenuW(hmenu, MF_SEPARATOR, 0, None)
            elif isinstance(item[1], list):
                self.user32.AppendMenuW(hmenu, MF_POPUP, self._build(item[1]), item[0])
            else:
                command, label, flags = item
                self.user32.AppendMenuW(hmenu, MF_STRING | flags, command, label)
        return hmenu

    def _show_menu(self):
        hmenu = self._build(self.menu())
        pt = self.w.POINT()
        self.user32.GetCursorPos(ctypes.byref(pt))
        self.user32.SetForegroundWindow(self.hwnd)  # so the menu closes when you click elsewhere
        command = self.user32.TrackPopupMenu(hmenu, TPM_RETURNCMD | TPM_RIGHTBUTTON, pt.x, pt.y, 0, self.hwnd, None)
        self.user32.DestroyMenu(hmenu)
        if command:
            self.on_command(command)

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAY and lparam in (WM_LBUTTONUP, WM_RBUTTONUP, WM_CONTEXTMENU):
            self._show_menu()
            return 0
        if msg == WM_REFRESH:
            self._apply()
            return 0
        if msg == self.taskbar_created:  # Explorer restarted: the icon must be added again
            self._add()
            return 0
        if msg == WM_CLOSE:  # Quit, or close() from another thread: tidy up on the owning thread
            self.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._data(0)))
            self.user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            self.user32.PostQuitMessage(0)
            return 0
        return self.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def run(self):
        msg = self.w.MSG()
        while self.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            self.user32.TranslateMessage(ctypes.byref(msg))
            self.user32.DispatchMessageW(ctypes.byref(msg))

    def close(self):
        """Thread-safe: remove the icon and end run()."""
        self.user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)


# ---- the app ----------------------------------------------------------------------------

PAUSE, LINK_WIFI, LINK_BT, MAPPING, UPDATE, PERF, STATUS, LOG, QUIT = range(1, 10)


class TrayApp:
    def __init__(self, args, cfg, store, mp, log_path):
        """mp: the multiput module (run_loop, claim/release of the single-instance lock)."""
        self.args, self.cfg, self.store, self.mp, self.log_path = args, cfg, store, mp, log_path
        self.saved = store.load_settings(cfg) or {}
        self.state = TrayState()
        self.worker, self.stop, self.commands = None, None, queue.Queue()
        self.busy = None  # the console task running, if any
        self.icon = TrayIcon(self.menu, self.command)
        events.set_handler(self.on_event)

    def on_event(self, text, kind, subject=None):
        print(text, flush=True)  # into the log file
        notification = self.state.on_event(text, kind, subject)  # first: the icon must show the state after the event
        self.icon.refresh(self.state.badge(), self.state.tooltip(), notification)

    def start_worker(self):
        self.mp.claim_single_instance()
        self.stop = threading.Event()
        self.saved = self.store.load_settings(self.cfg) or {}
        self.state.link_name = "Bluetooth" if self.saved.get("link") == "bt" else "Wi-Fi"
        key = self.store.load_key(self.cfg)

        def work(stop=self.stop):
            try:
                self.mp.run_loop(self.args, self.cfg, self.saved, key, stop=stop, commands=self.commands)
            except links.Stopped:
                pass
            except (SystemExit, OSError, ValueError) as e:  # e.g. no Bluetooth port, link error
                text = str(e.code if isinstance(e, SystemExit) else e)
                print(f"Error: {text}", flush=True)
                self.state.fail(text)
                self.icon.refresh(self.state.badge(), self.state.tooltip(), ("multiput stopped", text, True))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def stop_worker(self):
        if self.worker:
            self.stop.set()
            self.worker.join(5)
            self.worker = None
        self.mp.release_single_instance()

    def run_console(self, args):
        """Run a console multiput task (mapping editor, update, ...) in its own window. The
        loop stops meanwhile: the task may need the Pico, and the Switch shouldn't get the
        buttons pressed in the mapping editor. It restarts afterwards with the saved settings."""
        if self.busy:
            return
        self.busy = args[0]
        was_paused = self.state.paused
        self.stop_worker()
        self.state = TrayState(self.state.link_name)
        self.state.busy = True
        self.icon.refresh(self.state.badge(), self.state.tooltip())

        def wait():
            try:
                subprocess.run(console_command(*args), creationflags=subprocess.CREATE_NEW_CONSOLE)
            finally:
                self.busy = None
                self.state = TrayState(self.state.link_name)  # not busy: shown until the loop reports in
                self.icon.refresh(self.state.badge(), self.state.tooltip())
                self.start_worker()
                if was_paused:  # stay paused across the restart
                    self.commands.put("pause")

        threading.Thread(target=wait, daemon=True).start()

    def switch_link(self, link):
        self.saved = self.store.load_settings(self.cfg) or {}
        if self.saved.get("link") == link:
            return
        self.saved["link"] = link
        self.store.save_settings(self.cfg, self.saved)
        self.stop_worker()
        self.state = TrayState()
        self.start_worker()

    def menu(self):
        link = (self.store.load_settings(self.cfg) or {}).get("link", "wifi")
        busy = MF_GRAYED if self.busy else 0
        return [
            *[(0, line, MF_GRAYED) for line in self.state.status_lines()],  # a menu item can't break lines
            None,
            (PAUSE, "Resume" if self.state.paused else "Pause", busy),
            ("Link", [(LINK_WIFI, "Wi-Fi", busy | (MF_CHECKED if link == "wifi" else 0)),
                      (LINK_BT, "Bluetooth", busy | (MF_CHECKED if link == "bt" else 0))]),
            (MAPPING, "Button mapping", busy),
            None,
            (UPDATE, "Update the Pico", busy),
            (PERF, "Performance test", busy),
            (STATUS, "Pico status", busy),
            (LOG, "Open log", 0),
            None,
            (QUIT, "Quit", 0),
        ]

    def command(self, command):
        if command == PAUSE:
            self.commands.put("pause")
        elif command in (LINK_WIFI, LINK_BT):
            self.switch_link("wifi" if command == LINK_WIFI else "bt")
        elif command == MAPPING:
            self.run_console(["--remap"])
        elif command == UPDATE:
            self.run_console(["--update"])
        elif command == PERF:
            self.run_console(["--perf-test"])
        elif command == STATUS:
            self.run_console(["--pico-status"])
        elif command == LOG:
            os.startfile(self.log_path)
        elif command == QUIT:
            self.stop_worker()
            self.icon.close()

    def run(self):
        self.start_worker()
        self.icon.run()
        events.set_handler(None)


def main(args, cfg, store, mp):
    """Entry point for tray mode. Output goes to %APPDATA%\\multiput\\multiput.log."""
    cfg.mkdir(parents=True, exist_ok=True)
    log_path = cfg / "multiput.log"
    log = open(log_path, "w", buffering=1, encoding="utf-8")
    sys.stdout = sys.stderr = log
    saved = store.load_settings(cfg)
    if not (saved and "link" in saved):  # first run: setup needs a console
        subprocess.run(console_command("--setup", "--no-start"), creationflags=subprocess.CREATE_NEW_CONSOLE)
        saved = store.load_settings(cfg)
        if not (saved and "link" in saved):
            return
    try:
        mp.claim_single_instance()  # before the icon exists, so a second copy leaves no stray icon
    except SystemExit as e:
        ctypes.WinDLL("user32").MessageBoxW(None, str(e.code), "multiput", 0x30)
        return
    TrayApp(args, cfg, store, mp, log_path).run()
