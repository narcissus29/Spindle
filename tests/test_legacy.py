"""Coming from Satsuma (this app's old name): the first start as Spindle
moves the settings, stops a running Satsuma and removes everything it set
up, taking over start at login and the GNOME shortcut. Against the real
wheel process, in a throwaway home."""

import json
import os
import subprocess
import sys
import time

import pytest

from app import config, legacy, logs, platform_utils as pu
from tests import wheel_process
from tests.test_shortcut_recorder import isolated  # noqa: F401 (fixture)

FAKE_OLD = r"""
import sys
from PyQt6.QtCore import QCoreApplication
from PyQt6.QtNetwork import QLocalServer
app = QCoreApplication([])
server = QLocalServer()
server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
QLocalServer.removeServer(sys.argv[1])
assert server.listen(sys.argv[1]), server.errorString()
def take():
    sock = server.nextPendingConnection()
    def read():
        if b"quit" in bytes(sock.readAll()):
            app.quit()
    sock.readyRead.connect(read)
server.newConnection.connect(take)
print("listening", flush=True)
app.exec()
"""


def test_first_start_moves_satsuma_over(qapp, isolated):  # noqa: F811
    home = os.environ.get("HOME", "")
    old_cfg = legacy.old_folder(config.config_dir())
    old_cfg.mkdir(parents=True)
    (old_cfg / "config.json").write_text(json.dumps({"hotkey": "Ctrl+Alt+K", "theme": "orange", "setup_done": True}))
    (config.config_dir() / "config.json").unlink()  # a fresh Spindle: nothing of its own yet
    old_logs = legacy.old_folder(logs.log_dir())
    old_logs.mkdir(parents=True, exist_ok=True)
    (old_logs / "satsuma.log").write_text("old log\n")
    old_cache = legacy.old_folder(config.cache_dir())
    old_cache.mkdir(parents=True, exist_ok=True)

    old_task = None
    if pu.IS_WINDOWS:  # Satsuma's start at login: a logon task and a Run value
        old_task = pu._task_name(legacy.old_app_name(), "Satsuma")
        import tempfile

        fd, xml = tempfile.mkstemp(suffix=".xml")
        os.close(fd)
        with open(xml, "w", encoding="utf-16") as fh:
            fh.write(pu._task_xml([sys.executable, "-c", "pass"]))
        assert pu._schtasks("/Create", "/TN", old_task, "/XML", xml, "/F").returncode == 0
        os.unlink(xml)
        import winreg

        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, pu._RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, pu._run_value_name(legacy.old_app_name(), "Satsuma"), 0, winreg.REG_SZ, "x")
    else:
        from pathlib import Path

        h = Path(home)
        for f in (h / ".config" / "autostart" / "satsuma.desktop",
                  h / ".local" / "share" / "applications" / "satsuma.desktop",
                  h / ".local" / "share" / "dbus-1" / "services" / f"{legacy.OLD_DBUS_NAME}.service",
                  h / "Applications" / "Satsuma.AppImage"):
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("old")
    gnome = pu.gnome_shortcuts_available()
    print("GNOME part:", gnome)
    old_path = pu._GNOME_BINDING_PATH.replace("/spindle/", "/satsuma/")
    if gnome:
        pu._gsettings("set", pu._GNOME_MEDIA_KEYS, "custom-keybindings", "['" + old_path + "']")
        pu._gsettings("set", f"{pu._GNOME_MEDIA_KEYS}.custom-keybinding:{old_path}", "binding", "'<Control><Alt>k'")
        assert pu.gnome_shortcut(old_path) == "Ctrl+Alt+K"

    # a Satsuma that is still running
    old = subprocess.Popen([sys.executable, "-c", FAKE_OLD, legacy._old_socket_names()[0]],
                           stdout=subprocess.PIPE, text=True, env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
    assert old.stdout.readline().strip() == "listening"

    wheel = wheel_process.start("--background")
    try:
        wheel_process.wait_until_up(wheel)
        assert old.wait(15) is not None  # it was asked to quit
        assert wheel_process.ask("hotkey-state").endswith("Ctrl+Alt+K") or not pu.IS_WINDOWS
        cfg = json.loads((config.config_dir() / "config.json").read_text())
        assert cfg["hotkey"] == "Ctrl+Alt+K" and cfg["theme"] == "orange" and cfg["setup_done"]
        assert cfg["satsuma_cleaned"]
        assert not old_cfg.exists() and not old_logs.exists() and not old_cache.exists()
        assert pu.autostart_enabled()  # Satsuma started at login: now Spindle does
        if pu.IS_WINDOWS:
            assert pu._schtasks("/Query", "/TN", old_task).returncode != 0
            assert pu.autostart_method() == "task"
        else:
            from pathlib import Path

            h = Path(home)
            assert not (h / ".config" / "autostart" / "satsuma.desktop").exists()
            assert not (h / ".local" / "share" / "applications" / "satsuma.desktop").exists()
            assert not (h / "Applications" / "Satsuma.AppImage").exists()
            assert "--background" in (h / ".config" / "autostart" / "spindle.desktop").read_text()
        if gnome:
            assert pu.gnome_shortcut(old_path) == "" and pu.gnome_shortcut() == "Ctrl+Alt+K"
        log = logs.log_path().read_text(encoding="utf-8")
        assert "[migrate] settings copied" in log and "[migrate] removed" in log
    finally:
        print(wheel_process.stop(wheel))
        if old.poll() is None:
            old.kill()
        pu.set_autostart(False)
        if old_task:
            pu._schtasks("/Delete", "/TN", old_task, "/F")


def test_a_second_start_changes_nothing(qapp, isolated):  # noqa: F811
    wheel = wheel_process.start("--background")
    try:
        wheel_process.wait_until_up(wheel)
    finally:
        wheel_process.stop(wheel)
    first = json.loads((config.config_dir() / "config.json").read_text())
    assert first["satsuma_cleaned"]
    assert not legacy.copy_settings(config.config_dir())  # Spindle has its own now
