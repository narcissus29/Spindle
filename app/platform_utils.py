"""Every piece of OS-specific code lives here.

- Window strategy: where and how the wheel window is placed.
- Global cursor position (not available on Wayland).
- GPU presence check, so "auto" can pick the software renderer up front.
- Windows global hotkey via the Win32 RegisterHotKey API (ctypes).
- Windows foreground hand-off for `--show` from a second process, and
  bringing the wheel to the front when a file is parked.
- Process memory readers for the --stats logger, and heap trimming.
- Desktop notifications (Linux: freedesktop D-Bus; Windows: the tray).
- Desktop integration: how Spindle is started, autostart, the Linux
  AppImage installing itself, the GNOME shortcut and its D-Bus Toggle.
- Editor process: starting it with the right to take the foreground, its
  window decorations on Wayland, and "Show in folder".
- Whether a drag is under way when the shortcut is pressed, and making a
  changed input region take effect on GNOME (Wayland).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QAbstractNativeEventFilter, QPoint
from PyQt6.QtGui import QCursor, QGuiApplication, QWindow

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")
IS_MAC = sys.platform == "darwin"

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    _user32.RegisterHotKey.restype = wintypes.BOOL
    _user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.UnregisterHotKey.restype = wintypes.BOOL
    _user32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
    _user32.AllowSetForegroundWindow.restype = wintypes.BOOL
    _user32.GetForegroundWindow.argtypes = []
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    _user32.AttachThreadInput.restype = wintypes.BOOL
    _user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    _user32.SetForegroundWindow.restype = wintypes.BOOL
    _user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    _user32.GetAsyncKeyState.restype = ctypes.c_short
    _user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    _user32.GetSystemMetrics.restype = ctypes.c_int

    class _PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
            ("PrivateUsage", ctypes.c_size_t),
        ]

    _kernel32 = ctypes.WinDLL("kernel32")
    _kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    _psapi = ctypes.WinDLL("psapi")
    _psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(_PROCESS_MEMORY_COUNTERS_EX), wintypes.DWORD,
    ]
    _psapi.GetProcessMemoryInfo.restype = wintypes.BOOL


# ---------------------------------------------------------------- session ---

def is_wayland() -> bool:
    """True when Qt is running as a native Wayland client.

    Before the QGuiApplication exists this falls back to the environment."""
    if QGuiApplication.instance() is not None:
        return QGuiApplication.platformName().startswith("wayland")
    if not IS_LINUX:
        return False
    platform = os.environ.get("QT_QPA_PLATFORM", "")
    if platform:
        return platform.startswith("wayland")
    return bool(os.environ.get("WAYLAND_DISPLAY")) or os.environ.get("XDG_SESSION_TYPE") == "wayland"


def window_strategy() -> str:
    """'at_cursor': a wheel-sized window placed under the mouse (Windows, X11, macOS).
    'overlay':   a transparent maximized window with the wheel centered. It
                 takes all input while shown, so clicking outside the wheel
                 closes it. Used on Wayland, where clients cannot position
                 windows."""
    return "overlay" if is_wayland() else "at_cursor"


def cursor_position() -> QPoint | None:
    """Global cursor position, or None where the OS does not expose it."""
    if is_wayland():
        return None
    return QCursor.pos()


def allow_foreground_handoff() -> None:
    """Called by a short-lived `--show` process before it messages the
    resident instance. Windows only lets the process that has the user's
    input bring a window to the front; this passes that right along."""
    if IS_WINDOWS:
        ASFW_ANY = 0xFFFFFFFF  # (DWORD)-1
        _user32.AllowSetForegroundWindow(ASFW_ANY)


def bring_to_front(window: QWindow) -> None:
    """Give the wheel keyboard focus after a file is parked on it, so Esc /
    Tab work and clicking elsewhere counts as "click outside".

    A drop doesn't activate the target window: the file manager keeps focus.
    - Windows: SetForegroundWindow is refused for background apps, so attach
      to the foreground thread's input first (the workaround Qt itself uses
      for its AlwaysActivateWindow mode).
    - Wayland: not called. Activating needs an xdg-activation token tied to a
      recent input event; without one GNOME shows a "Spindle is ready"
      notification instead. The overlay window catches outside clicks
      itself (see window.py).
    - X11 / macOS: a normal activation request."""
    if is_wayland():
        return
    if not IS_WINDOWS:
        window.requestActivate()
        return
    hwnd = int(window.winId())
    foreground = _user32.GetForegroundWindow()
    if foreground == hwnd:
        return
    this_thread = _kernel32.GetCurrentThreadId()
    fg_thread = _user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
    attached = bool(fg_thread and fg_thread != this_thread
                    and _user32.AttachThreadInput(fg_thread, this_thread, True))
    try:
        _user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            _user32.AttachThreadInput(fg_thread, this_thread, False)


def allow_foreground_for(pid: int) -> None:
    """Windows: let a process we just started (the editor) bring its window
    to the front. We may hand on the right only while we have it, which we
    do right after the user dropped a file on the wheel."""
    if IS_WINDOWS and pid > 0:
        _user32.AllowSetForegroundWindow(pid)


# ------------------------------------------------- input region, dragging ---

def drag_in_progress() -> bool | None:
    """Is the primary mouse button held right now (a file being dragged)?
    None where the OS won't say: Wayland gives apps no global pointer state.

    - Windows: GetAsyncKeyState on the primary button (swapped buttons
      respected).
    - X11: XQueryPointer's button mask, through libX11."""
    if IS_WINDOWS:
        VK_LBUTTON, VK_RBUTTON, SM_SWAPBUTTON = 0x01, 0x02, 23
        key = VK_RBUTTON if _user32.GetSystemMetrics(SM_SWAPBUTTON) else VK_LBUTTON
        return bool(_user32.GetAsyncKeyState(key) & 0x8000)
    if IS_LINUX and QGuiApplication.platformName() == "xcb":
        return _x11_button1_down()
    return None


def _x11_button1_down() -> bool | None:
    try:
        import ctypes
        import ctypes.util

        x11 = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
        x11.XOpenDisplay.restype = ctypes.c_void_p
        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x11.XDefaultRootWindow.restype = ctypes.c_ulong
        x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        ulong, cint, cuint = ctypes.c_ulong, ctypes.c_int, ctypes.c_uint
        x11.XQueryPointer.argtypes = [ctypes.c_void_p, ulong, ctypes.POINTER(ulong), ctypes.POINTER(ulong),
                                      ctypes.POINTER(cint), ctypes.POINTER(cint), ctypes.POINTER(cint),
                                      ctypes.POINTER(cint), ctypes.POINTER(cuint)]
        display = x11.XOpenDisplay(None)
        if not display:
            return None
        try:
            root, child = ulong(), ulong()
            rx, ry, wx, wy, mask = cint(), cint(), cint(), cint(), cuint()
            x11.XQueryPointer(display, x11.XDefaultRootWindow(display), ctypes.byref(root), ctypes.byref(child),
                              ctypes.byref(rx), ctypes.byref(ry), ctypes.byref(wx), ctypes.byref(wy), ctypes.byref(mask))
            return bool(mask.value & 0x100)  # Button1Mask
        finally:
            x11.XCloseDisplay(display)
    except (OSError, AttributeError):
        return None


def input_region_needs_nudge() -> bool:
    """GNOME (Mutter, checked on 50.1) applies a new input region of a
    window that is already on screen only when the window's size changes;
    a plain commit with the new region is ignored, so clicks outside the
    wheel would still land on us. Other Wayland compositors don't need
    this, but a nudge is harmless there."""
    return is_wayland()


def nudge_window_size(window: QWindow, done: Callable[[], None]) -> None:
    """Shrink the window by one pixel and restore it a moment later, so the
    compositor re-reads the input region set just before. `done` runs once
    the size is back."""
    from PyQt6.QtCore import QTimer

    w, h = window.width(), window.height()
    window.resize(w, h - 1)

    def restore() -> None:
        window.resize(w, h)
        done()

    QTimer.singleShot(40, restore)


# ---------------------------------------------------------------- editor ---

def prepare_editor_environment() -> None:
    """Before the editor's QGuiApplication exists.

    Wayland on GNOME has no server-side window decorations, so Qt draws the
    title bar itself; its default ("bradient") looks dated. Qt ships an
    Adwaita-style one: use it unless the user picked something else. (KDE
    and most other compositors draw their own decorations and ignore this.)"""
    if IS_LINUX and is_wayland() and "QT_WAYLAND_DECORATION" not in os.environ:
        os.environ["QT_WAYLAND_DECORATION"] = "adwaita"


def reveal_in_file_manager(path: Path) -> None:
    """Open the file manager with `path` selected.

    - Linux: org.freedesktop.FileManager1.ShowItems over D-Bus (Files,
      Dolphin, Nemo, ...); if nobody answers, open the folder.
    - Windows: explorer /select,<path>."""
    from PyQt6.QtCore import QProcess, QUrl
    from PyQt6.QtGui import QDesktopServices

    if IS_WINDOWS:
        QProcess.startDetached("explorer", [f"/select,{path}"])
        return
    if IS_LINUX:
        try:
            from PyQt6.QtCore import QMetaType
            from PyQt6.QtDBus import QDBusArgument, QDBusConnection, QDBusInterface, QDBusMessage

            iface = QDBusInterface("org.freedesktop.FileManager1", "/org/freedesktop/FileManager1",
                                   "org.freedesktop.FileManager1", QDBusConnection.sessionBus())
            reply = iface.call("ShowItems",
                               QDBusArgument([QUrl.fromLocalFile(str(path)).toString()], QMetaType.Type.QStringList.value),
                               "")
            if reply.type() != QDBusMessage.MessageType.ErrorMessage:
                return
            print(f"[reveal] {reply.errorMessage()}")
        except Exception as exc:
            print(f"[reveal] {exc}")
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))


# ------------------------------------------------------------------- GPU ---

def has_gpu() -> bool:
    """Cheap check for hardware rendering, used when renderer = "auto".

    Linux: Mesa needs a DRM render node (/dev/dri/renderD*). Without one
    (VMs without 3D, some containers) OpenGL runs on llvmpipe, which costs
    ~75 MB more RAM than Qt Quick's own software renderer and is no faster
    for a scene this small.
    Windows / macOS: assume yes. If the GPU backend fails at runtime, the
    sceneGraphError fallback in main.py switches to software."""
    if IS_LINUX:
        if os.environ.get("LIBGL_ALWAYS_SOFTWARE", "") not in ("", "0"):
            return False
        return any(Path("/dev/dri").glob("renderD*"))
    return True


# ---------------------------------------------------------- global hotkey ---

_MODIFIERS = {"ctrl": 0x0002, "control": 0x0002, "alt": 0x0001, "shift": 0x0004, "win": 0x0008, "meta": 0x0008,
              "super": 0x0008}
_MOD_NOREPEAT = 0x4000
_NAMED_KEYS = {"space": 0x20, "tab": 0x09, "enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B}
_WM_HOTKEY = 0x0312


def default_hotkey() -> str:
    """Windows: Win+Alt+S ("Alt+Meta+S", in the order the recorder writes
    it). Tested with real keystrokes and two input languages:
    - Alt+Shift+Space flips the input language when Alt and Shift are let
      go before Space (Left Alt+Shift is Windows' language switch);
    - Ctrl+Shift can be the layout switch, Ctrl+Alt+Space is taken by
      other apps (the Claude desktop app), and Ctrl+Alt+<letter> is
      AltGr+<letter>, which types a character on many keyboards (₹ on
      English (India) is AltGr+4);
    - Win+Alt+S fired in every press / release order, never switched the
      language and never opened Start.
    Linux (GNOME): Ctrl+Alt+Space."""
    return "Alt+Meta+S" if IS_WINDOWS else "Ctrl+Alt+Space"


def hotkey_warning(text: str, windows: bool | None = None) -> str:
    """Windows: why a shortcut may misbehave, or "". Alt+Shift (and
    Ctrl+Shift, where set up) switch the keyboard language or layout."""
    if not (IS_WINDOWS if windows is None else windows):
        return ""
    mods = {p.strip().lower() for p in text.split("+")[:-1]}
    mods = {"ctrl" if m == "control" else "meta" if m in ("win", "super") else m for m in mods}
    if mods == {"alt", "shift"}:
        return ("Alt + Shift also switches the keyboard language in Windows: letting go of Alt and "
                "Shift first can flip it. A shortcut with Win or Ctrl + Alt is safer.")
    if mods == {"ctrl", "shift"}:
        return ("Ctrl + Shift can switch the keyboard layout in Windows (if it is set up that way). "
                "A shortcut with Win or Ctrl + Alt is safer.")
    return ""


def parse_hotkey(text: str) -> tuple[int, int] | None:
    """'Ctrl+Alt+Space' -> (modifier flags, virtual-key code)."""
    mods, vk = 0, None
    for part in (p.strip().lower() for p in text.split("+")):
        if part in _MODIFIERS:
            mods |= _MODIFIERS[part]
        elif part in _NAMED_KEYS:
            vk = _NAMED_KEYS[part]
        elif len(part) == 1 and part.isalnum():
            vk = ord(part.upper())
        elif part.startswith("f") and part[1:].isdigit() and 1 <= int(part[1:]) <= 24:
            vk = 0x70 + int(part[1:]) - 1
        else:
            return None
    if vk is None or mods == 0:
        return None
    return mods, vk


class GlobalHotkey(QAbstractNativeEventFilter):
    """System-wide hotkey. Windows only (RegisterHotKey + WM_HOTKEY).

    Linux has no portable global hotkey on Wayland; users bind a desktop
    shortcut to `main.py --toggle` instead (see README)."""

    _HOTKEY_ID = 0x5A75  # any value in 0x0000-0xBFFF

    def __init__(self, callback: Callable[[], None]) -> None:
        super().__init__()
        self._callback = callback
        self._registered = False
        self._last_msg: tuple[int, int] | None = None

    @staticmethod
    def supported() -> bool:
        return IS_WINDOWS

    @property
    def registered(self) -> bool:
        return self._registered

    def register(self, text: str) -> bool:
        if not IS_WINDOWS:
            return False
        parsed = parse_hotkey(text)
        if parsed is None:
            print(f"[hotkey] cannot parse {text!r}; expected e.g. 'Ctrl+Alt+Space'")
            return False
        mods, vk = parsed
        # hWnd=NULL: WM_HOTKEY is posted to this (the GUI) thread's queue,
        # independent of any window being created or destroyed.
        ok = bool(_user32.RegisterHotKey(None, self._HOTKEY_ID, mods | _MOD_NOREPEAT, vk))
        if not ok:
            print(f"[hotkey] {text} is already taken by another app (error {ctypes.get_last_error()})")
            return False
        QGuiApplication.instance().installNativeEventFilter(self)
        self._registered = True
        return True

    def unregister(self) -> None:
        if IS_WINDOWS and self._registered:
            _user32.UnregisterHotKey(None, self._HOTKEY_ID)
            QGuiApplication.instance().removeNativeEventFilter(self)
            self._registered = False

    def nativeEventFilter(self, eventType, message):
        if bytes(eventType) in (b"windows_dispatcher_MSG", b"windows_generic_MSG"):
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == _WM_HOTKEY and msg.wParam == self._HOTKEY_ID:
                # The same MSG can pass through both filter hooks; act once.
                key = (msg.time, msg.lParam)
                if key != self._last_msg:
                    self._last_msg = key
                    self._callback()
                return True, 0
        return False, 0


# ------------------------------------------------- office documents -> PDF ---
#
# Spindle bundles no office suite: it uses the one installed. Windows:
# Microsoft Word / Excel / PowerPoint through COM, else LibreOffice; Linux:
# LibreOffice (deb, Snap or Flatpak). Only the helper process calls these.

_OFFICE_EXE = {"Word.Application": "WINWORD.EXE", "Excel.Application": "EXCEL.EXE",
               "PowerPoint.Application": "POWERPNT.EXE"}


def office_app_installed(progid: str) -> bool:
    """Windows: is Word / Excel / PowerPoint ("Word.Application") there?"""
    if not IS_WINDOWS:
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, progid + "\\CLSID"):
            return True
    except OSError:
        return False


def process_ids(image_name: str) -> set[int]:
    """Windows: the processes running `image_name` ("WINWORD.EXE")."""
    if not IS_WINDOWS:
        return set()

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.Process32FirstW.argtypes = k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    found: set[int] = set()
    if not snap or snap == wintypes.HANDLE(-1).value:
        return found
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == image_name.lower():
                found.add(int(entry.th32ProcessID))
            ok = k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        _kernel32.CloseHandle(snap)
    return found


def com_application(progid: str):
    """Windows: start Word / Excel / PowerPoint for automation (late bound,
    nothing generated on disk). Returns (app, pid): pid is the process this
    started, or None if COM handed over one already running (PowerPoint
    runs once per user): that one is the user's, never quit or killed."""
    import comtypes.client

    exe = _OFFICE_EXE.get(progid, "")
    before = process_ids(exe)
    app = comtypes.client.CreateObject(progid, dynamic=True)
    new = process_ids(exe) - before
    return app, (next(iter(new)) if len(new) == 1 else None)


def libreoffice_command() -> list[str] | None:
    """How to run LibreOffice, or None if it isn't installed."""
    if IS_WINDOWS:
        roots = []
        import winreg

        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(hive, r"SOFTWARE\LibreOffice\UNO\InstallPath") as key:
                    roots.append(Path(winreg.QueryValueEx(key, "")[0]))
            except OSError:
                pass
        for env in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            if os.environ.get(env):
                roots.append(Path(os.environ[env]) / "LibreOffice" / "program")
        for root in roots:
            for name in ("soffice.com", "soffice.exe"):  # .com waits and reports like a console program
                if (root / name).is_file():
                    return [str(root / name)]
        return None
    if IS_MAC:
        app = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
        return [str(app)] if app.exists() else None
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return [found]
    if Path("/snap/bin/libreoffice").exists():
        return ["/snap/bin/libreoffice"]
    if shutil.which("flatpak"):
        try:
            if subprocess.run(["flatpak", "info", "org.libreoffice.LibreOffice"], capture_output=True,
                              timeout=10).returncode == 0:
                return ["flatpak", "run", "org.libreoffice.LibreOffice"]
        except (OSError, subprocess.SubprocessError):
            pass
    return None


def libreoffice_folders(command: list[str], source: Path) -> tuple[Path, Path]:
    """(its private profile, a new empty folder for its output). A Snap or
    Flatpak LibreOffice can't see hidden folders or /tmp, so for those both
    live where it can write: the profile in its own data folder, the
    output next to the source (removed right after)."""
    import tempfile

    from . import app_name

    exe = os.path.realpath(command[0]) if command[0] != "flatpak" else ""
    if command[0] == "flatpak":
        profile = _home() / ".var" / "app" / "org.libreoffice.LibreOffice" / f"{app_name()}-profile"
    elif exe.startswith("/snap/") or command[0].startswith("/snap/"):
        profile = _home() / "snap" / "libreoffice" / "common" / f"{app_name()}-profile"
    else:
        from . import config

        profile = config.cache_dir() / "libreoffice-profile"
        return profile, Path(tempfile.mkdtemp(prefix="spindle-lo-"))
    return profile, Path(tempfile.mkdtemp(prefix="Spindle converting ", dir=source.parent))


def start_hidden(command: list[str]) -> subprocess.Popen:
    """A child process with no console window (Windows) in its own process
    group (so it and whatever it starts can be stopped together)."""
    if IS_WINDOWS:
        flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        return subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, creationflags=flags)
    return subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, start_new_session=True)


def kill_process_tree(pid: int) -> None:
    """Stop a process and its children (a LibreOffice or Word that
    Spindle started; never anything else)."""
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True,
                       creationflags=subprocess.CREATE_NO_WINDOW, timeout=30)
        return
    import signal

    for kill in (lambda: os.killpg(pid, signal.SIGKILL), lambda: os.kill(pid, signal.SIGKILL)):
        try:
            kill()
        except OSError:
            pass


# ---------------------------------------------------------- startup timing ---

def startup_times() -> dict:
    """Seconds since this process was created ("process"), since the user
    signed in ("session", Windows only) and since the system booted
    ("boot"); None where unknown. Logged once the wheel is ready, so a
    slow start can be told apart: started late, or slow to start."""
    out = {"process": None, "session": None, "boot": None}
    try:
        if IS_LINUX:
            with open("/proc/uptime", encoding="ascii") as fh:
                uptime = float(fh.read().split()[0])
            with open("/proc/self/stat", encoding="ascii") as fh:
                started = int(fh.read().rsplit(")", 1)[1].split()[19]) / os.sysconf("SC_CLK_TCK")
            out["boot"], out["process"] = uptime, uptime - started
        elif IS_WINDOWS:
            k32 = ctypes.WinDLL("kernel32")
            k32.GetTickCount64.restype = ctypes.c_ulonglong
            u64p = ctypes.POINTER(ctypes.c_ulonglong)
            k32.GetSystemTimeAsFileTime.argtypes = [u64p]
            k32.GetProcessTimes.argtypes = [wintypes.HANDLE, u64p, u64p, u64p, u64p]
            k32.GetProcessTimes.restype = wintypes.BOOL
            out["boot"] = k32.GetTickCount64() / 1000
            now = ctypes.c_ulonglong()
            k32.GetSystemTimeAsFileTime(ctypes.byref(now))
            created, ex, kt, ut = (ctypes.c_ulonglong() for _ in range(4))
            if k32.GetProcessTimes(_kernel32.GetCurrentProcess(), ctypes.byref(created), ctypes.byref(ex),
                                   ctypes.byref(kt), ctypes.byref(ut)):
                out["process"] = (now.value - created.value) / 1e7
            logon = _windows_logon_filetime()
            if logon:
                out["session"] = (now.value - logon) / 1e7
    except Exception as exc:  # diagnostics only: never stop the app
        print(f"[startup] can't read the times: {exc}")
    return out


def _windows_logon_filetime() -> int | None:
    """When this Windows session's user signed in (FILETIME), via WTS."""

    class WTSINFOW(ctypes.Structure):
        _fields_ = [("State", ctypes.c_int), ("SessionId", wintypes.DWORD)]
        _fields_ += [(n, wintypes.DWORD) for n in ("IncomingBytes", "OutgoingBytes", "IncomingFrames",
                                                     "OutgoingFrames", "IncomingCompressedBytes",
                                                     "OutgoingCompressedBytes")]
        _fields_ += [("WinStationName", ctypes.c_wchar * 32), ("Domain", ctypes.c_wchar * 17),
                     ("UserName", ctypes.c_wchar * 21)]
        _fields_ += [(n, ctypes.c_longlong) for n in ("ConnectTime", "DisconnectTime", "LastInputTime",
                                                       "LogonTime", "CurrentTime")]

    wts = ctypes.WinDLL("wtsapi32")
    wts.WTSQuerySessionInformationW.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_int,
                                                ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD)]
    wts.WTSQuerySessionInformationW.restype = wintypes.BOOL
    wts.WTSFreeMemory.argtypes = [ctypes.c_void_p]
    buf, size = ctypes.c_void_p(), wintypes.DWORD()
    WTS_CURRENT_SESSION, WTSSessionInfo = 0xFFFFFFFF, 24
    if not wts.WTSQuerySessionInformationW(None, WTS_CURRENT_SESSION, WTSSessionInfo,
                                           ctypes.byref(buf), ctypes.byref(size)):
        return None
    try:
        if size.value < ctypes.sizeof(WTSINFOW):
            return None
        return WTSINFOW.from_address(buf.value).LogonTime or None
    finally:
        wts.WTSFreeMemory(buf)


# ---------------------------------------------------------------- memory ---

def memory_info() -> tuple[int | None, int | None]:
    """(rss, private) in bytes.

    rss:     resident set (Linux) / working set (Windows). Includes shared
             library pages, so it overstates what the app really costs.
    private: memory only this process uses. Linux: PSS from smaps_rollup
             (shared pages split between users). Windows: PrivateUsage
             (commit charge)."""
    try:
        if IS_LINUX:
            rss = pss = None
            with open("/proc/self/smaps_rollup", "r", encoding="ascii") as fh:
                for line in fh:
                    if line.startswith("Rss:"):
                        rss = int(line.split()[1]) * 1024
                    elif line.startswith("Pss:"):
                        pss = int(line.split()[1]) * 1024
            return rss, pss
        if IS_WINDOWS:
            counters = _PROCESS_MEMORY_COUNTERS_EX()
            counters.cb = ctypes.sizeof(counters)
            if _psapi.GetProcessMemoryInfo(_kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
                return counters.WorkingSetSize, counters.PrivateUsage
            return None, None
        import resource  # macOS: peak RSS only, in bytes

        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, None
    except Exception:
        return None, None


def process_memory(pid: int) -> dict:
    """Memory of another process (the helper, the editor), in bytes:
    {"rss", "peak", "private"}; missing values are None.
    Linux: VmRSS, VmHWM (peak), Pss. Windows: working set, its peak,
    PrivateUsage."""
    out = {"rss": None, "peak": None, "private": None}
    try:
        if IS_LINUX:
            with open(f"/proc/{pid}/status", encoding="ascii") as fh:
                for line in fh:
                    if line.startswith("VmRSS:"):
                        out["rss"] = int(line.split()[1]) * 1024
                    elif line.startswith("VmHWM:"):
                        out["peak"] = int(line.split()[1]) * 1024
            with open(f"/proc/{pid}/smaps_rollup", encoding="ascii") as fh:
                for line in fh:
                    if line.startswith("Pss:"):
                        out["private"] = int(line.split()[1]) * 1024
        elif IS_WINDOWS:
            handle = _kernel32.OpenProcess(0x1000 | 0x0010, False, pid)  # QUERY_LIMITED_INFORMATION | VM_READ
            if handle:
                try:
                    counters = _PROCESS_MEMORY_COUNTERS_EX()
                    counters.cb = ctypes.sizeof(counters)
                    if _psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                        out = {"rss": counters.WorkingSetSize, "peak": counters.PeakWorkingSetSize,
                               "private": counters.PrivateUsage}
                finally:
                    _kernel32.CloseHandle(handle)
    except (OSError, ValueError):
        pass
    return out


def kill_process(pid: int) -> None:
    """Stop another process of ours (SIGTERM; TerminateProcess on Windows)."""
    import signal

    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass


def release_memory() -> None:
    """Give freed heap pages back to the OS after the wheel hides.
    glibc keeps freed memory in its arenas otherwise. Takes ~1 ms."""
    if IS_LINUX:
        try:
            import ctypes

            ctypes.CDLL("libc.so.6").malloc_trim(0)
        except (OSError, AttributeError):
            pass


# ---------------------------------------------------------- notifications ---

_notifier: Callable[[str, str], None] | None = None


def set_notifier(fn: Callable[[str, str], None] | None) -> None:
    """Windows: the tray icon shows notifications (set by the app)."""
    global _notifier
    _notifier = fn


def notify(title: str, body: str) -> None:
    """Desktop notification, e.g. when a conversion finishes after the wheel
    was closed. Linux: org.freedesktop.Notifications over D-Bus (GNOME,
    KDE, ...). Windows: a toast from the tray icon."""
    if IS_WINDOWS and _notifier is not None:
        _notifier(title, body)
        return
    if IS_LINUX:
        try:
            from PyQt6.QtCore import QMetaType
            from PyQt6.QtDBus import QDBusArgument, QDBusConnection, QDBusInterface, QDBusMessage

            iface = QDBusInterface("org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                                   "org.freedesktop.Notifications", QDBusConnection.sessionBus())
            reply = iface.call(
                "Notify",
                "Spindle",                                             # app_name
                QDBusArgument(0, QMetaType.Type.UInt.value),           # replaces_id
                "document-save",                                       # app_icon (theme name)
                title, body,
                QDBusArgument([], QMetaType.Type.QStringList.value),   # actions
                {},                                                    # hints
                -1,                                                    # expire_timeout: server default
            )
            if reply.type() != QDBusMessage.MessageType.ErrorMessage:
                return
            print(f"[notify] {reply.errorMessage()}")
        except Exception as exc:  # no session bus etc.
            print(f"[notify] {exc}")
    print(f"[notify] {title}: {body}")


# ---------------------------------------------------- desktop integration ---
#
# How Spindle is started, started at login, found in the app menu, and
# toggled by a keyboard shortcut.
#
# Linux (AppImage): on first run the AppImage copies itself to
# ~/Applications/Spindle.AppImage and runs from there. Every start rewrites
# the app-menu entry, icon and D-Bus service file for that path, so moving
# or updating the AppImage never leaves a broken entry behind. The shortcut
# runs `gdbus call ... Toggle` (about 10 ms; D-Bus starts Spindle first if
# it isn't running), set up automatically on GNOME with gsettings.
# Windows: the installer adds the Start Menu entry and uninstaller; the app
# only handles "start with Windows" and its RegisterHotKey.
#
# Start at login runs `Spindle --background`: it never shows the wheel, and
# if Spindle is already running it just exits. On Windows it is a Task
# Scheduler task with a logon trigger: Windows starts programs from the
# Run key late after sign-in (often a minute or more, after the desktop
# settles), a logon task right away. If the task can't be made (a policy
# forbids it), the Run key is used instead.

import shutil
import subprocess

_GNOME_MEDIA_KEYS = "org.gnome.settings-daemon.plugins.media-keys"
_GNOME_BINDING_PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/spindle/"
_GNOME_SCHEMAS = ("org.gnome.desktop.wm.keybindings", "org.gnome.shell.keybindings",
                  "org.gnome.mutter.keybindings", "org.gnome.mutter.wayland.keybindings", _GNOME_MEDIA_KEYS)
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _home() -> Path:
    return Path.home()


def _data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or _home() / ".local" / "share")


def _config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or _home() / ".config")


def runtime_dir() -> Path | None:
    """Linux: the user's private runtime folder ($XDG_RUNTIME_DIR, normally
    /run/user/<uid>, mode 0700), for the single-instance socket and lock:
    in the shared /tmp, another user could take their (predictable) names
    first and stop Spindle from starting. None elsewhere (Windows: named
    pipes, the lock in the per-user %TEMP%)."""
    if not IS_LINUX:
        return None
    for candidate in (os.environ.get("XDG_RUNTIME_DIR"), f"/run/user/{os.getuid()}"):
        if not candidate:
            continue
        path = Path(candidate)
        try:
            st = path.stat()
        except OSError:
            continue
        if path.is_dir() and st.st_uid == os.getuid() and not st.st_mode & 0o077:
            return path
    return None


def log_dir(name: str) -> Path:
    """Where the log file goes. Windows: %LOCALAPPDATA%\\<name> (next to
    the config); Linux: $XDG_STATE_HOME/<name> (~/.local/state/<name>)."""
    if IS_WINDOWS:
        return Path(os.environ.get("LOCALAPPDATA") or _home() / "AppData" / "Local") / name
    if IS_MAC:
        return _home() / "Library" / "Logs" / name
    return Path(os.environ.get("XDG_STATE_HOME") or _home() / ".local" / "state") / name


def open_folder(path: Path) -> None:
    """Show a folder in the file manager (Explorer, Files, ...)."""
    from PyQt6.QtCore import QUrl
    from PyQt6.QtGui import QDesktopServices

    path.mkdir(parents=True, exist_ok=True)
    if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
        print(f"[logs] can't open {path}")


def running_as_appimage() -> bool:
    return IS_LINUX and bool(os.environ.get("APPIMAGE"))


def installed_appimage() -> Path:
    return _home() / "Applications" / "Spindle.AppImage"


def app_command(*args: str) -> list[str]:
    """The command line that starts Spindle: the installed AppImage, the
    .exe, or `python main.py` from a source checkout."""
    if running_as_appimage():
        target = installed_appimage()
        return [str(target if target.exists() else Path(os.environ["APPIMAGE"])), *args]
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    from . import PROJECT_DIR

    return [sys.executable, str(PROJECT_DIR / "main.py"), *args]


def _exec_line(argv: list[str], desktop: bool = True) -> str:
    """argv as a .desktop (or D-Bus service) Exec value, each part quoted.
    In a .desktop file "%" is doubled, or it would be read as a field code
    like %f."""
    def quote(a: str) -> str:
        for ch in ('\\', '"', '`', '$'):
            a = a.replace(ch, '\\' + ch)
        return f'"{a}"'.replace("%", "%%") if desktop else f'"{a}"'
    return " ".join(quote(a) for a in argv)


def _write_if_changed(path: Path, text: str, mode: int | None = None) -> None:
    if path.exists() and path.read_text(encoding="utf-8", errors="replace") == text:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    if mode is not None:
        tmp.chmod(mode)
    os.replace(tmp, path)


# ---- Linux: the AppImage installs itself ----

def self_install_appimage() -> Path | None:
    """Running a downloaded AppImage: copy it to ~/Applications (unless it
    is that copy already, or an identical one is there). Returns the
    installed path when the caller should switch to it, else None."""
    if not running_as_appimage():
        return None
    src = Path(os.environ["APPIMAGE"])
    dst = installed_appimage()
    try:
        if dst.exists() and src.resolve() == dst.resolve():
            return None
        if not (dst.exists() and _same_file(src, dst)):
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_name(".Spindle.AppImage.part")
            shutil.copyfile(src, tmp)
            tmp.chmod(0o755)
            os.replace(tmp, dst)  # a running copy keeps its old file open
        return dst
    except OSError as exc:
        print(f"[install] can't copy to {dst}: {exc}")
        return None


def _same_file(a: Path, b: Path) -> bool:
    import hashlib

    if a.stat().st_size != b.stat().st_size:
        return False
    def digest(p: Path) -> bytes:
        h = hashlib.sha256()
        with p.open("rb") as f:
            while chunk := f.read(1 << 20):
                h.update(chunk)
        return h.digest()
    return digest(a) == digest(b)


def _icon_files(app_id: str) -> list[Path]:
    """Where the app-menu icon goes: one PNG per size (pixel art), plus the
    scalable SVG earlier versions put there."""
    from . import ICON_SIZES

    theme = _data_home() / "icons" / "hicolor"
    return [theme / f"{s}x{s}" / "apps" / f"{app_id}.png" for s in ICON_SIZES] + \
        [theme / "scalable" / "apps" / f"{app_id}.svg"]


def write_linux_entries(icons: dict[int, Path]) -> None:
    """App-menu entry, icons and D-Bus activation file for the installed
    AppImage (rewritten on every start, so they follow it). `icons`: size
    -> PNG."""
    if not running_as_appimage():
        return
    from . import APP_ID, APP_NAME, DBUS_NAME

    run = app_command()
    try:
        _write_if_changed(_data_home() / "applications" / f"{APP_ID}.desktop", "\n".join([
            "[Desktop Entry]", "Type=Application", f"Name={APP_NAME}",
            "Comment=Convert, compress and edit files from a radial wheel",
            f"Exec={_exec_line(run)}", f"Icon={APP_ID}", "Terminal=false",
            "Categories=Utility;Graphics;Office;", f"StartupWMClass={APP_ID}", "Actions=Settings;", "",
            "[Desktop Action Settings]", "Name=Settings", f"Exec={_exec_line(app_command('--settings'))}", ""]))
        theme = _data_home() / "icons" / "hicolor"
        for size, png in icons.items():
            dst = theme / f"{size}x{size}" / "apps" / f"{APP_ID}.png"
            data = png.read_bytes()
            if not dst.exists() or dst.read_bytes() != data:
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(data)
        (theme / "scalable" / "apps" / f"{APP_ID}.svg").unlink(missing_ok=True)  # rc4's smooth icon
        _write_if_changed(_data_home() / "dbus-1" / "services" / f"{DBUS_NAME}.service",
                          f"[D-BUS Service]\nName={DBUS_NAME}\nExec={_exec_line(run, desktop=False)}\n")
        if autostart_enabled():
            set_autostart(True)       # follow a moved / updated AppImage
        if gnome_shortcut():
            set_gnome_shortcut(gnome_shortcut())
    except OSError as exc:
        print(f"[install] can't write the app entry: {exc}")


def remove_linux_install(delete_settings: bool) -> None:
    """Undo everything the AppImage set up: the copy in ~/Applications,
    app-menu entry, icon, D-Bus file, autostart, GNOME shortcut."""
    from . import APP_ID, DBUS_NAME

    set_autostart(False)
    remove_gnome_shortcut()
    for path in (installed_appimage(),
                 _data_home() / "applications" / f"{APP_ID}.desktop",
                 *_icon_files(APP_ID),
                 _data_home() / "dbus-1" / "services" / f"{DBUS_NAME}.service"):
        path.unlink(missing_ok=True)
    if delete_settings:
        from . import config

        shutil.rmtree(config.config_dir(), ignore_errors=True)
        shutil.rmtree(config.cache_dir(), ignore_errors=True)


# ---- start at login ----

def _autostart_file() -> Path:
    from . import APP_ID

    return _config_home() / "autostart" / f"{APP_ID}.desktop"


AUTOSTART_ARGS = ("--background",)


def _run_value_name(app: str | None = None, display: str = "Spindle") -> str:
    """The Run value: "Spindle" (a test instance: its app name). `app` /
    `display` name another app (the old Satsuma, to remove it)."""
    from . import APP_ID, app_name

    app = app or app_name()
    base = display.lower() if display != "Spindle" else APP_ID
    return display if app == base else app


def _task_name(app: str | None = None, display: str = "Spindle") -> str:
    """Per user: task names are shared by everyone on the PC."""
    return f"{_run_value_name(app, display)} ({os.environ.get('USERNAME', 'user')})"


def _schtasks(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["schtasks", *args], capture_output=True, text=True, errors="replace",
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=30)


def _task_xml(argv: list[str]) -> str:
    """A logon task for this user only, run unelevated, with none of the
    defaults that would stop it: on battery, after 3 days, at low priority."""
    from xml.sax.saxutils import escape

    user = f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}".lstrip("\\")
    command, args = argv[0], subprocess.list2cmdline(argv[1:])
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Author>Spindle</Author>
    <Description>Starts Spindle in the background when you sign in, so its shortcut works right away.</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger><Enabled>true</Enabled><UserId>{escape(user)}</UserId></LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{escape(user)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>false</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>5</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(command)}</Command>
      <Arguments>{escape(args)}</Arguments>
      <WorkingDirectory>{escape(str(Path(command).parent))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def _windows_task_exists() -> bool:
    try:
        return _schtasks("/Query", "/TN", _task_name()).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _windows_run_value() -> str | None:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            return str(winreg.QueryValueEx(key, _run_value_name())[0])
    except OSError:
        return None


def _set_windows_run_value(command: str | None) -> None:
    import winreg

    # CreateKeyEx: a fresh account may not have the Run key yet.
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if command is not None:
            winreg.SetValueEx(key, _run_value_name(), 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, _run_value_name())
            except OSError:
                pass


def autostart_method() -> str:
    """How Spindle starts at login: "task" / "run-key" (Windows),
    "desktop-file" (Linux), or "" (it doesn't)."""
    if IS_WINDOWS:
        if _windows_task_exists():
            return "task"
        return "run-key" if _windows_run_value() is not None else ""
    return "desktop-file" if _autostart_file().exists() else ""


def autostart_enabled() -> bool:
    return autostart_method() != ""


def set_autostart(on: bool) -> None:
    """Start Spindle (hidden, ready for the shortcut) when the user logs in."""
    from . import APP_NAME

    argv = app_command(*AUTOSTART_ARGS)
    if IS_WINDOWS:
        import tempfile

        if not on:
            if _windows_task_exists():
                _schtasks("/Delete", "/TN", _task_name(), "/F")
            _set_windows_run_value(None)
            return
        fd, name = tempfile.mkstemp(prefix="spindle-task-", suffix=".xml")
        os.close(fd)
        xml = Path(name)
        try:
            xml.write_text(_task_xml(argv), encoding="utf-16")
            made = _schtasks("/Create", "/TN", _task_name(), "/XML", str(xml), "/F")
        except (OSError, subprocess.SubprocessError) as exc:
            made = None
            print(f"[autostart] can't make the logon task: {exc}")
        finally:
            xml.unlink(missing_ok=True)
        if made is not None and made.returncode == 0:
            _set_windows_run_value(None)  # one way only (and no rc1 leftover)
            print(f"[autostart] logon task {_task_name()!r} set")
        else:
            if made is not None:
                print(f"[autostart] logon task refused ({(made.stderr or made.stdout).strip()}); using the Run key")
            _set_windows_run_value(subprocess.list2cmdline(argv))
        return
    path = _autostart_file()
    if not on:
        path.unlink(missing_ok=True)
        return
    _write_if_changed(path, "\n".join([
        "[Desktop Entry]", "Type=Application", f"Name={APP_NAME}", f"Exec={_exec_line(argv)}",
        "Terminal=false", "NoDisplay=true", "X-GNOME-Autostart-enabled=true", ""]))


# ---- the keyboard shortcut (Linux) ----

def shortcut_command() -> str:
    """What the desktop shortcut runs. With the D-Bus file installed (the
    AppImage) a gdbus call: ~10 ms, and it starts Spindle if needed."""
    from . import DBUS_INTERFACE, DBUS_NAME, DBUS_PATH

    if running_as_appimage() and shutil.which("gdbus"):
        return (f"gdbus call --session --dest {DBUS_NAME} --object-path {DBUS_PATH} "
                f"--method {DBUS_INTERFACE}.Toggle")
    return subprocess.list2cmdline(app_command("--toggle")) if IS_WINDOWS else " ".join(
        f"'{a}'" if " " in a else a for a in app_command("--toggle"))


def gnome_shortcuts_available() -> bool:
    if not IS_LINUX or not shutil.which("gsettings"):
        return False
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    if not any(d in desktop for d in ("gnome", "unity", "ubuntu", "pantheon", "budgie")):
        return False
    return _gsettings("get", _GNOME_MEDIA_KEYS, "custom-keybindings") is not None


def _gsettings(*args: str) -> str | None:
    try:
        out = subprocess.run(["gsettings", *args], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def _gvariant_list(text: str | None) -> list[str]:
    import re

    if not text or text.startswith("@as"):
        return []
    return re.findall(r"'((?:[^'\\]|\\.)*)'", text)


def _gquote(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


# Qt key names (as in "Ctrl+Alt+Space") <-> GTK key names
_GTK_KEYS = {"space": "space", "tab": "Tab", "return": "Return", "enter": "Return", "esc": "Escape",
             "escape": "Escape", "backspace": "BackSpace", "del": "Delete", "delete": "Delete",
             "ins": "Insert", "insert": "Insert", "home": "Home", "end": "End", "pgup": "Page_Up",
             "pgdown": "Page_Down", "left": "Left", "right": "Right", "up": "Up", "down": "Down",
             ",": "comma", ".": "period", "/": "slash", ";": "semicolon", "'": "apostrophe",
             "[": "bracketleft", "]": "bracketright", "\\": "backslash", "-": "minus", "=": "equal",
             "`": "grave"}
_GTK_MODS = {"ctrl": "<Control>", "alt": "<Alt>", "shift": "<Shift>", "meta": "<Super>", "super": "<Super>"}


def gnome_accel(text: str) -> str | None:
    """'Ctrl+Alt+Space' -> '<Control><Alt>space'."""
    parts = [p.strip() for p in text.split("+") if p.strip()] if text.strip() != "+" else []
    if len(parts) < 2:
        return None
    mods, key = parts[:-1], parts[-1]
    out = ""
    for m in mods:
        if m.lower() not in _GTK_MODS:
            return None
        out += _GTK_MODS[m.lower()]
    k = key.lower()
    if k in _GTK_KEYS:
        out += _GTK_KEYS[k]
    elif len(key) == 1 and key.isalnum():
        out += key.lower()
    elif k.startswith("f") and k[1:].isdigit():
        out += key.upper()
    else:
        return None
    return out


def _accel_key(accel: str) -> tuple[frozenset, str] | None:
    """A GTK accelerator as (modifiers, key) for comparing."""
    import re

    mods = set()
    for m in re.findall(r"<(\w+)>", accel):
        m = m.lower()
        mods.add({"primary": "control", "ctrl": "control", "control": "control", "mod1": "alt",
                  "meta": "super", "mod4": "super", "super": "super", "alt": "alt", "shift": "shift"}.get(m, m))
    key = re.sub(r"<\w+>", "", accel).strip()
    return (frozenset(mods), key.lower()) if key else None


def gnome_shortcut(path: str = _GNOME_BINDING_PATH) -> str:
    """The shortcut Spindle set in GNOME, as Qt text ("Ctrl+Alt+Space"), or "".
    (`path`: another app's binding, the old Satsuma's.)"""
    if not IS_LINUX or not shutil.which("gsettings"):
        return ""
    if path not in _gvariant_list(_gsettings("get", _GNOME_MEDIA_KEYS, "custom-keybindings")):
        return ""
    accel = (_gvariant_list(_gsettings("get", f"{_GNOME_MEDIA_KEYS}.custom-keybinding:{path}",
                                       "binding")) or [""])[0]
    parsed = _accel_key(accel)
    if not parsed:
        return ""
    names = {"control": "Ctrl", "alt": "Alt", "shift": "Shift", "super": "Meta"}
    key = parsed[1]
    pretty = {v.lower(): k for k, v in _GTK_KEYS.items() if len(k) > 1}.get(key, key)
    pretty = pretty.capitalize() if len(pretty) > 1 else pretty.upper()
    return "+".join([names[m] for m in ("control", "alt", "shift", "super") if m in parsed[0]] + [pretty])


def gnome_conflict(text: str) -> str:
    """What already uses this shortcut in GNOME ("Switch to workspace 1"),
    or "" if nothing does."""
    accel = gnome_accel(text)
    wanted = _accel_key(accel) if accel else None
    if not wanted:
        return ""
    for schema in _GNOME_SCHEMAS:
        listing = _gsettings("list-recursively", schema) or ""
        for line in listing.splitlines():
            parts = line.split(" ", 2)
            if len(parts) < 3:
                continue
            for value in _gvariant_list(parts[2]) or ([parts[2].strip("'")] if parts[2].startswith("'") else []):
                if _accel_key(value) == wanted:
                    return parts[1].replace("-", " ").capitalize()
    for path in _gvariant_list(_gsettings("get", _GNOME_MEDIA_KEYS, "custom-keybindings")):
        if path == _GNOME_BINDING_PATH:
            continue
        schema = f"{_GNOME_MEDIA_KEYS}.custom-keybinding:{path}"
        value = (_gvariant_list(_gsettings("get", schema, "binding")) or [""])[0]
        if _accel_key(value) == wanted:
            return (_gvariant_list(_gsettings("get", schema, "name")) or ["a custom shortcut"])[0]
    return ""


def set_gnome_shortcut(text: str) -> str:
    """Bind `text` ("Ctrl+Alt+Space") to Spindle in GNOME. Returns an error
    message, or "" when done."""
    from . import APP_NAME

    accel = gnome_accel(text)
    if not accel:
        return "Use Ctrl, Alt or Super with a letter, number, F-key or Space"
    paths = _gvariant_list(_gsettings("get", _GNOME_MEDIA_KEYS, "custom-keybindings"))
    if _GNOME_BINDING_PATH not in paths:
        paths.append(_GNOME_BINDING_PATH)
        if _gsettings("set", _GNOME_MEDIA_KEYS, "custom-keybindings",
                      "[" + ", ".join(_gquote(p) for p in paths) + "]") is None:
            return "GNOME didn't accept the shortcut"
    schema = f"{_GNOME_MEDIA_KEYS}.custom-keybinding:{_GNOME_BINDING_PATH}"
    for key, value in (("name", APP_NAME), ("command", shortcut_command()), ("binding", accel)):
        if _gsettings("set", schema, key, _gquote(value)) is None:
            return "GNOME didn't accept the shortcut"
    return ""


def remove_gnome_shortcut(path: str = _GNOME_BINDING_PATH) -> None:
    if not IS_LINUX or not shutil.which("gsettings"):
        return
    paths = _gvariant_list(_gsettings("get", _GNOME_MEDIA_KEYS, "custom-keybindings"))
    if path in paths:
        paths.remove(path)
        _gsettings("set", _GNOME_MEDIA_KEYS, "custom-keybindings",
                   "[" + ", ".join(_gquote(p) for p in paths) + "]" if paths else "@as []")
    schema = f"{_GNOME_MEDIA_KEYS}.custom-keybinding:{path}"
    for key in ("name", "command", "binding"):
        _gsettings("reset", schema, key)


# ---- what an older version under another name left behind ----

def remove_old_app(old_app: str, old_display: str, old_dbus_name: str) -> dict:
    """Remove everything an earlier name of this app set up, so nothing
    runs twice: its start at login (logon task, Run value, autostart file),
    GNOME shortcut, app-menu entry, icon, D-Bus file and installed
    AppImage. `old_app` is its app name ("satsuma", or "satsuma-<test>").
    Returns what it had: {"autostart": bool, "shortcut": "Ctrl+Alt+Space"
    or "", "removed": [what went]} so the new name can take them over."""
    found = {"autostart": False, "shortcut": "", "removed": []}
    if IS_WINDOWS:
        task = _task_name(old_app, old_display)
        try:
            if _schtasks("/Query", "/TN", task).returncode == 0:
                _schtasks("/Delete", "/TN", task, "/F")
                found["autostart"] = True
                found["removed"].append(f"logon task {task!r}")
        except (OSError, subprocess.SubprocessError):
            pass
        import winreg

        value = _run_value_name(old_app, old_display)
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0,
                                winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE) as key:
                winreg.QueryValueEx(key, value)
                winreg.DeleteValue(key, value)
                found["autostart"] = True
                found["removed"].append(f"Run value {value!r}")
        except OSError:
            pass
        return found
    old_id = old_display.lower()
    autostart = _config_home() / "autostart" / f"{old_id}.desktop"
    if autostart.exists():
        autostart.unlink(missing_ok=True)
        found["autostart"] = True
        found["removed"].append(str(autostart))
    old_path = _GNOME_BINDING_PATH.replace("/spindle/", f"/{old_id}/")
    found["shortcut"] = gnome_shortcut(old_path)
    listed = gnome_shortcuts_available() and old_path in _gvariant_list(
        _gsettings("get", _GNOME_MEDIA_KEYS, "custom-keybindings"))
    if found["shortcut"] or listed:
        remove_gnome_shortcut(old_path)
        found["removed"].append(f"GNOME shortcut {found['shortcut'] or '(empty)'}")
    for path in (_data_home() / "applications" / f"{old_id}.desktop",
                 _data_home() / "icons" / "hicolor" / "scalable" / "apps" / f"{old_id}.svg",
                 _data_home() / "dbus-1" / "services" / f"{old_dbus_name}.service",
                 _home() / "Applications" / f"{old_display}.AppImage"):
        if path.exists() and str(path) != os.environ.get("APPIMAGE"):
            path.unlink(missing_ok=True)
            found["removed"].append(str(path))
    return found


# ---- the D-Bus Toggle the shortcut calls (Linux) ----

def register_dbus_toggle(on_toggle: Callable[[], None], on_settings: Callable[[], None]):
    """Own DBUS_NAME on the session bus with Toggle / Settings methods.
    Returns the object (keep it alive), or None if D-Bus isn't there."""
    if not IS_LINUX:
        return None
    try:
        from PyQt6.QtCore import QObject, pyqtClassInfo, pyqtSlot
        from PyQt6.QtDBus import QDBusConnection

        from . import DBUS_INTERFACE, DBUS_NAME, DBUS_PATH

        @pyqtClassInfo("D-Bus Interface", DBUS_INTERFACE)
        class _Service(QObject):
            @pyqtSlot()
            def Toggle(self) -> None:  # noqa: N802 (D-Bus method name)
                on_toggle()

            @pyqtSlot()
            def Settings(self) -> None:  # noqa: N802
                on_settings()

        bus = QDBusConnection.sessionBus()
        service = _Service()
        if not bus.registerObject(DBUS_PATH, service, QDBusConnection.RegisterOption.ExportAllSlots):
            return None
        if not bus.registerService(DBUS_NAME):
            print(f"[dbus] can't own {DBUS_NAME}: {bus.lastError().message()}")
            return None
        return service
    except Exception as exc:  # no session bus
        print(f"[dbus] {exc}")
        return None
