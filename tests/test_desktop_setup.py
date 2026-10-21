"""Desktop integration and the welcome / settings window: the GNOME
shortcut (gsettings, isolated in a throwaway keyfile backend), autostart,
the AppImage installing itself, and the socket questions to the wheel."""

import os
import sys

import pytest
from PyQt6.QtCore import QEvent, QEventLoop, Qt, QTimer

from app import platform_utils as pu

linux_only = pytest.mark.skipif(not pu.IS_LINUX, reason="Linux desktop integration")


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A throwaway home: config, data, autostart and GNOME settings."""
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(h / ".config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(h / ".local" / "share"))
    monkeypatch.setenv("GSETTINGS_BACKEND", "keyfile")  # never the real GNOME settings
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "ubuntu:GNOME")
    monkeypatch.setenv("SPINDLE_INSTANCE", "pytest")
    monkeypatch.delenv("APPIMAGE", raising=False)
    return h


def wait(ms=200):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def test_gnome_accelerators():
    assert pu.gnome_accel("Ctrl+Alt+Space") == "<Control><Alt>space"
    assert pu.gnome_accel("Meta+Shift+F5") == "<Super><Shift>F5"
    assert pu.gnome_accel("Ctrl+Alt+K") == "<Control><Alt>k"
    assert pu.gnome_accel("Space") is None and pu.gnome_accel("Ctrl+Hyper+X") is None
    assert pu._accel_key("<Primary><Alt>space") == pu._accel_key("<Control><Alt>Space")
    assert pu.parse_hotkey("Meta+E") is not None  # the Windows key


@linux_only
@pytest.mark.skipif(not pu.shutil.which("gsettings"), reason="needs gsettings")
def test_gnome_shortcut_set_read_conflict_remove(home):
    if not pu.gnome_shortcuts_available():
        pytest.skip("GNOME's keybinding schemas aren't installed")
    assert pu.gnome_conflict("Meta+Space")       # GNOME's input-source switch
    assert pu.gnome_conflict("Ctrl+Alt+K") == ""
    assert pu.set_gnome_shortcut("Ctrl+Alt+K") == ""
    assert pu.gnome_shortcut() == "Ctrl+Alt+K"
    keyfile = (home / ".config" / "glib-2.0" / "settings" / "keyfile").read_text()
    assert "binding='<Control><Alt>k'" in keyfile and "name='Spindle'" in keyfile
    assert pu.set_gnome_shortcut("Ctrl+Alt+J") == "" and pu.gnome_shortcut() == "Ctrl+Alt+J"
    pu.remove_gnome_shortcut()
    assert pu.gnome_shortcut() == ""


@linux_only
def test_autostart_entry(home):
    assert not pu.autostart_enabled()
    pu.set_autostart(True)
    entry = (home / ".config" / "autostart" / "spindle.desktop").read_text()
    assert "Exec=" in entry and "main.py" in entry and '"--background"' in entry and "NoDisplay=true" in entry
    assert pu.autostart_enabled()
    pu.set_autostart(False)
    assert not pu.autostart_enabled()


@linux_only
def test_appimage_installs_itself_and_can_be_removed(home, tmp_path, monkeypatch):

    download = tmp_path / "Downloads" / "Spindle-x86_64.AppImage"
    download.parent.mkdir()
    download.write_bytes(b"\x7fELF fake appimage " * 1000)
    monkeypatch.setenv("APPIMAGE", str(download))
    installed = pu.self_install_appimage()
    assert installed == home / "Applications" / "Spindle.AppImage"
    assert installed.read_bytes() == download.read_bytes() and os.access(installed, os.X_OK)
    monkeypatch.setenv("APPIMAGE", str(installed))  # what the copy sees when it runs
    assert pu.self_install_appimage() is None        # running the installed copy: nothing to do
    pu.set_autostart(True)
    from app import BRAND_DIR, ICON_SIZES

    old_svg = home / ".local" / "share" / "icons" / "hicolor" / "scalable" / "apps" / "spindle.svg"
    old_svg.parent.mkdir(parents=True)
    old_svg.write_text("<svg/>")  # rc4's smooth icon
    pu.write_linux_entries({s: BRAND_DIR / f"icon-{s}.png" for s in ICON_SIZES})
    data = home / ".local" / "share"
    desktop = (data / "applications" / "spindle.desktop").read_text()
    assert f'Exec="{installed}"' in desktop and "Icon=spindle" in desktop and "--settings" in desktop
    for s in ICON_SIZES:  # pixel art: one exact PNG per size
        assert (data / "icons" / "hicolor" / f"{s}x{s}" / "apps" / "spindle.png").read_bytes() == \
            (BRAND_DIR / f"icon-{s}.png").read_bytes()
    assert not old_svg.exists()
    service = next((data / "dbus-1" / "services").glob("*.service")).read_text()
    assert f'Exec="{installed}"' in service
    assert str(installed) in (home / ".config" / "autostart" / "spindle.desktop").read_text()
    assert pu.shortcut_command().startswith("gdbus call --session")
    pu.remove_linux_install(delete_settings=True)
    assert not installed.exists() and not (data / "applications" / "spindle.desktop").exists()
    assert not list((data / "icons").rglob("spindle.png"))  # the icons go too
    assert not pu.autostart_enabled()


def test_socket_questions_get_answers(qapp, home):
    from app.single_instance import SingleInstance

    server = SingleInstance()
    assert server.listen()
    server.responder = lambda q: "ok" if q == "hotkey Ctrl+Alt+K" else "taken"
    got = {}

    def ask():
        got["a"] = SingleInstance().ask("hotkey Ctrl+Alt+K")
        got["b"] = SingleInstance().ask("hotkey F1")

    # The answers come from this process's own event loop, so ask from a thread.
    import threading

    t = threading.Thread(target=ask)
    t.start()
    for _ in range(50):
        wait(50)
        if not t.is_alive():
            break
    t.join(1)
    server.close()
    assert got == {"a": "ok", "b": "taken"}


@linux_only
@pytest.mark.skipif(not pu.shutil.which("gsettings"), reason="needs gsettings")
def test_welcome_records_a_shortcut_by_keyboard(qapp, home):
    from PyQt6.QtCore import QUrl
    from PyQt6.QtGui import QGuiApplication, QKeyEvent
    from PyQt6.QtQml import QQmlApplicationEngine
    from PyQt6.QtTest import QTest

    from app import QML_DIR
    from app.setup.app import SetupBridge

    if not pu.gnome_shortcuts_available():
        pytest.skip("GNOME's keybinding schemas aren't installed")
    engine = QQmlApplicationEngine()
    bridge = SetupBridge("welcome", just_installed=False, parent=engine)
    assert bridge.shortcutMode == "gnome" and bridge.shortcut == ""
    engine.rootContext().setContextProperty("editor", bridge)
    engine.rootContext().setContextProperty("setup", bridge)
    engine.load(QUrl.fromLocalFile(str(QML_DIR / "setup" / "Welcome.qml")))
    win = engine.rootObjects()[0]
    wait(400)

    from PyQt6.QtQuick import QQuickItem

    field = win.findChild(QQuickItem, "shortcutField")
    from PyQt6.QtCore import QPointF

    p = field.mapToScene(QPointF(field.width() / 2, field.height() / 2)).toPoint()
    QTest.mouseClick(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p)
    wait()
    assert field.property("recording")
    mods = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
    # a shortcut GNOME already uses is refused with the reason
    QGuiApplication.sendEvent(win, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_T, mods))
    wait()
    assert field.property("status") == "error" and "Terminal" in bridge.error
    QTest.mouseClick(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p)
    wait()
    QGuiApplication.sendEvent(win, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_K, mods))
    wait()
    assert field.property("status") == "ok" and pu.gnome_shortcut() == "Ctrl+Alt+K"
    # finishing: start at login on, welcome done
    win.next()
    win.next()
    assert pu.autostart_enabled()
    win.next()
    from app import config

    assert config.load().setup_done
    win.close()
    del engine
