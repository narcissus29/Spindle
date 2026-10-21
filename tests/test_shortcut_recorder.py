"""The shortcut recorder in the welcome and settings windows, against the
real wheel process (on Windows it registers the keys for real with
RegisterHotKey; elsewhere it accepts any shortcut). Every confirmed
shortcut must be shown, saved to the config and used by the wheel, the
last one winning, also after the wheel restarts."""

import os
import shutil
import sys

import pytest
from PyQt6.QtCore import QCoreApplication, QEvent, QEventLoop, QPointF, Qt, QTimer, QUrl
from PyQt6.QtGui import QGuiApplication, QKeyEvent
from PyQt6.QtQml import QQmlApplicationEngine
from PyQt6.QtQuick import QQuickItem
from PyQt6.QtTest import QTest

from app import QML_DIR, app_name, config
from app import platform_utils as pu
from tests import wheel_process


def wait(ms=200):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


@pytest.fixture
def isolated(qapp, tmp_path, monkeypatch):
    """Own instance name (socket, config folder), own home on Linux."""
    monkeypatch.setenv("SPINDLE_INSTANCE", f"pytest{os.getpid()}")
    if not pu.IS_WINDOWS:
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
        monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
        monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local" / "state"))
        monkeypatch.setenv("XDG_CACHE_HOME", str(home / ".cache"))
        monkeypatch.setenv("GSETTINGS_BACKEND", "keyfile")
    old_name = QCoreApplication.applicationName()
    QCoreApplication.setApplicationName(app_name())
    cfg = config.Config()
    cfg.setup_done = True  # no welcome window from the wheel
    cfg.tray_icon = False
    config.save(cfg)
    yield config.config_dir()
    folder = config.config_dir()
    QCoreApplication.setApplicationName(old_name)
    if pu.IS_WINDOWS:
        shutil.rmtree(folder, ignore_errors=True)


@pytest.fixture
def wheel(isolated):
    proc = wheel_process.start()
    try:
        wheel_process.wait_until_up(proc)
        yield proc
    finally:
        print(wheel_process.stop(proc))


def press(win, field, key, mods):
    p = field.mapToScene(QPointF(field.width() / 2, field.height() / 2)).toPoint()
    QTest.mouseClick(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p, 600)
    wait()
    assert field.property("recording")
    QGuiApplication.sendEvent(win, QKeyEvent(QEvent.Type.KeyPress, key, mods))
    wait()


def shown_keys(field) -> str:
    caps = next(c for c in field.childItems() if c.objectName() == "shortcutKeys")
    return caps.property("keys") if caps.isVisible() else ""


@pytest.mark.parametrize("page", ["Welcome.qml", "Settings.qml"])
def test_last_confirmed_shortcut_is_shown_saved_and_used(qapp, wheel, page):
    from app.setup.app import SetupBridge

    engine = QQmlApplicationEngine()
    bridge = SetupBridge("welcome" if page == "Welcome.qml" else "settings", just_installed=False,
                         parent=engine, shortcut_mode="windows")
    engine.rootContext().setContextProperty("editor", bridge)
    engine.rootContext().setContextProperty("setup", bridge)
    engine.load(QUrl.fromLocalFile(str(QML_DIR / "setup" / page)))
    win = engine.rootObjects()[0]
    wait(400)
    field = next(i for i in win.findChildren(QQuickItem) if i.metaObject().className().startswith("ShortcutField"))
    assert shown_keys(field) == pu.default_hotkey()

    ctrl, alt, shift = (Qt.KeyboardModifier.ControlModifier, Qt.KeyboardModifier.AltModifier,
                        Qt.KeyboardModifier.ShiftModifier)
    for key, mods, text in ((Qt.Key.Key_X, ctrl | shift, "Ctrl+Shift+X"), (Qt.Key.Key_C, ctrl | alt, "Ctrl+Alt+C")):
        press(win, field, key, mods)
        assert field.property("status") == "ok", bridge.error
        assert shown_keys(field) == text
        assert bridge.shortcut == text
        assert config.load().hotkey == text
        assert wheel_process.ask("hotkey-state") == f"ok {text}"

    # Esc while recording keeps the last one (and the wheel still has it).
    p = field.mapToScene(QPointF(field.width() / 2, field.height() / 2)).toPoint()
    QTest.mouseClick(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p, 600)
    wait()
    QGuiApplication.sendEvent(win, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    wait()
    assert not field.property("recording") and shown_keys(field) == "Ctrl+Alt+C"
    assert wheel_process.ask("hotkey-state") == "ok Ctrl+Alt+C"
    win.close()
    del engine

    # A fresh wheel uses it: it was saved.
    print(wheel_process.stop(wheel))
    again = wheel_process.start()
    try:
        wheel_process.wait_until_up(again)
        assert wheel_process.ask("hotkey-state") == "ok Ctrl+Alt+C"
    finally:
        print(wheel_process.stop(again))


def test_taken_shortcut_is_refused_and_the_old_one_kept(qapp, isolated):
    """A fake wheel that refuses one shortcut (another app has it)."""
    from app.setup.app import SetupBridge
    from app.single_instance import SingleInstance

    import threading

    server = SingleInstance()
    assert server.listen()
    server.responder = lambda q: ("off Alt+Shift+Space" if q == "hotkey-state"
                                  else "taken" if q == "hotkey Ctrl+Alt+T" else "ok")
    got = {}

    def run():  # questions are answered by this thread's event loop: ask from another one
        b = SetupBridge("settings", just_installed=False, shortcut_mode="windows")
        got["problem"], got["error0"] = b.shortcutProblem, b.error
        got["taken"] = b.setShortcut("Ctrl+Alt+T")
        got["error"], got["after_taken"] = b.error, config.load().hotkey
        got["ok"] = b.setShortcut("Ctrl+Alt+K")
        got["problem_after"], got["saved"] = b.shortcutProblem, config.load().hotkey

    t = threading.Thread(target=run)
    t.start()
    for _ in range(100):
        wait(50)
        if not t.is_alive():
            break
    t.join(1)
    server.close()
    assert got["problem"] and "used by another app" in got["error0"]
    assert got["taken"] is False and "already used" in got["error"] and got["after_taken"] == pu.default_hotkey()
    assert got["ok"] is True and not got["problem_after"] and got["saved"] == "Ctrl+Alt+K"


def test_default_shortcut_per_platform():
    assert pu.default_hotkey() == ("Alt+Meta+S" if sys.platform == "win32" else "Ctrl+Alt+Space")
    assert pu.parse_hotkey(pu.default_hotkey()) is not None
    assert pu.hotkey_warning(pu.default_hotkey()) == ""


def test_language_switch_combinations_get_a_warning():
    assert "keyboard language" in pu.hotkey_warning("Alt+Shift+Space", windows=True)
    assert "keyboard layout" in pu.hotkey_warning("Ctrl+Shift+X", windows=True)
    for fine in ("Alt+Meta+S", "Ctrl+Alt+Space", "Ctrl+Alt+Shift+K", "Shift+Meta+F5"):
        assert pu.hotkey_warning(fine, windows=True) == "", fine
    assert pu.hotkey_warning("Alt+Shift+Space", windows=False) == ""


@pytest.mark.parametrize("page", ["Welcome.qml", "Settings.qml"])
def test_windows_shows_the_warning_and_the_safer_default(qapp, isolated, monkeypatch, page):
    from app.setup.app import SetupBridge

    real = pu.hotkey_warning  # the warning is about Windows' language switch
    monkeypatch.setattr(pu, "hotkey_warning", lambda text: real(text, windows=True))
    monkeypatch.setattr(pu, "default_hotkey", lambda: "Alt+Meta+S")
    cfg = config.load()
    cfg.hotkey = "Ctrl+Shift+X"  # what rc1 saved on the Windows test PC
    config.save(cfg)
    engine = QQmlApplicationEngine()
    bridge = SetupBridge("welcome", just_installed=False, parent=engine, shortcut_mode="windows")
    engine.rootContext().setContextProperty("editor", bridge)
    engine.rootContext().setContextProperty("setup", bridge)
    engine.load(QUrl.fromLocalFile(str(QML_DIR / "setup" / page)))
    win = engine.rootObjects()[0]
    wait(400)
    note = next(i for i in win.findChildren(QQuickItem) if i.objectName() == "shortcutWarning")
    assert note.isVisible() and "keyboard layout" in note.property("text")
    assert bridge.defaultShortcut == "Alt+Meta+S"
    assert bridge.pretty(bridge.defaultShortcut) == ("Win + Alt + S" if pu.IS_WINDOWS else "Super + Alt + S")
    assert bridge.setShortcut(bridge.defaultShortcut)  # no wheel running: saved for its next start
    wait()
    assert config.load().hotkey == "Alt+Meta+S" and not note.isVisible()
    win.close()
    del engine


def test_config_write_is_atomic_and_a_bad_read_keeps_the_file(qapp, isolated, capsys):
    path = config.config_path()
    cfg = config.load()
    cfg.hotkey = "Ctrl+Alt+K"
    config.save(cfg)
    assert config.load().hotkey == "Ctrl+Alt+K"
    assert not list(path.parent.glob("*.tmp"))
    path.write_text('{"hotkey": "Ctrl+Al', encoding="utf-8")  # half a file
    assert config.load().hotkey == pu.default_hotkey()
    assert path.read_text(encoding="utf-8") == '{"hotkey": "Ctrl+Al'  # not overwritten with defaults
