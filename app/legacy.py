"""Moving over from Satsuma, this app's name up to 0.1.0-rc3.

On the first start as Spindle (the wheel process, before it reads its
config):

1. a Satsuma that is still running is asked to quit;
2. its settings (config.json: the shortcut, theme, ...) are copied to
   Spindle's folder, if Spindle has none yet;
3. once, with the config loaded: everything Satsuma set up is removed
   so nothing runs twice (start at login, GNOME shortcut, app-menu
   entry, D-Bus file, ~/Applications/Satsuma.AppImage), and Spindle takes
   over what was on (start at login, the GNOME shortcut). Satsuma's
   config, cache and log folders go too.

The Windows installer replaces a Satsuma install itself (same AppId).
Test instances map to test instances: "spindle-<x>" <-> "satsuma-<x>".
"""

from __future__ import annotations

import getpass
import hashlib
import os
import shutil
from pathlib import Path

from . import APP_ID, app_name, platform_utils as pu

OLD_ID = "satsuma"
OLD_NAME = "Satsuma"
OLD_DBUS_NAME = "io.github.narcissus29.Satsuma"


def old_app_name() -> str:
    return OLD_ID + app_name()[len(APP_ID):]


def old_folder(new_folder: Path) -> Path:
    """Satsuma's version of one of Spindle's folders (same parent)."""
    return new_folder.with_name(old_app_name())


def _old_socket_names() -> list[str]:
    try:
        user = getpass.getuser()
    except Exception:
        user = "user"
    base = f"{OLD_ID}-{hashlib.sha1(user.encode('utf-8')).hexdigest()[:12]}" + app_name()[len(APP_ID):]
    names = [base]  # Windows pipe, or Linux /tmp (rc1)
    runtime = pu.runtime_dir()
    if runtime is not None:
        names.insert(0, str(runtime / base))
    return names


def stop_old_instance() -> bool:
    """Ask a running Satsuma to quit. True if one was running."""
    from PyQt6.QtNetwork import QLocalSocket
    import time

    stopped = False
    for name in _old_socket_names():
        sock = QLocalSocket()
        sock.connectToServer(name)
        if sock.waitForConnected(200):
            sock.write(b"quit\n")
            sock.flush()
            sock.waitForBytesWritten(300)
            sock.disconnectFromServer()
            stopped = True
    if stopped:
        time.sleep(0.8)  # it unregisters its hotkey / D-Bus name on the way out
    return stopped


def copy_settings(config_dir: Path) -> bool:
    """Satsuma's config.json -> Spindle's, unless Spindle has one."""
    new, old = config_dir / "config.json", old_folder(config_dir) / "config.json"
    if new.exists() or not old.is_file():
        return False
    try:
        new.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(old, new)
        return True
    except OSError as exc:
        print(f"[migrate] can't copy {old}: {exc}")
        return False


def clean_up(config_dir: Path, cache_dir: Path, log_dir: Path) -> list[str]:
    """Remove Satsuma's leftovers; Spindle takes over what was on.
    Returns what was done (for the log)."""
    done: list[str] = []
    try:
        found = pu.remove_old_app(old_app_name(), OLD_NAME, OLD_DBUS_NAME)
    except Exception as exc:  # never stop Spindle from starting
        print(f"[migrate] {exc}")
        found = {"autostart": False, "shortcut": "", "removed": []}
    done += [f"removed {what}" for what in found["removed"]]
    if found["autostart"] and not pu.autostart_enabled():
        pu.set_autostart(True)
        done.append("start at login: now Spindle")
    if found["shortcut"] and pu.gnome_shortcuts_available() and not pu.gnome_shortcut():
        problem = pu.set_gnome_shortcut(found["shortcut"])
        done.append(f"GNOME shortcut {found['shortcut']}: " + (problem or "now Spindle"))
    for folder in {old_folder(config_dir), old_folder(cache_dir), old_folder(log_dir)}:
        if folder.is_dir() and folder.name == old_app_name():
            shutil.rmtree(folder, ignore_errors=True)
            done.append(f"removed {folder}")
    return done
