"""Welcome / settings window process.

The welcome runs once (first start): pick the shortcut, choose whether
Spindle starts at login, then a 3-step how-to. Settings has the same
choices plus the look, compress strength, the tray icon and, for the Linux
AppImage, "Remove Spindle".

Settings are written to the config file, then the running wheel is told to
reload it ("reload-config"). On Windows the wheel owns the hotkey, so the
window asks it to try a new one ("?hotkey ..."); on GNOME the window sets
the shortcut itself with gsettings.
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

from PyQt6.QtCore import QCoreApplication, QObject, QUrl, pyqtProperty, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlApplicationEngine

from .. import APP_ID, APP_NAME, QML_DIR, __version__, app_name, config, platform_utils as pu
from ..icons import icon_path
from ..single_instance import SingleInstance

THEMES = ("blue", "orange")
PRESETS = ("light", "balanced", "strong")


class SetupBridge(QObject):
    """Exposed to QML as `editor` too, because the shared components
    (qml/editor) read their theme and icons from that name."""

    changed = pyqtSignal()
    closeRequested = pyqtSignal()

    def __init__(self, mode: str, just_installed: bool, parent: QObject | None = None,
                 shortcut_mode: str | None = None) -> None:
        super().__init__(parent)
        self._mode = mode
        self._installed = just_installed
        self._cfg = config.load()
        self._wheel = SingleInstance()
        self._capturing = False
        self._paused_gnome = ""
        self._error = ""
        # "windows" / "gnome" / "manual"; tests can pick one.
        self._shortcut_mode = shortcut_mode or (
            "windows" if pu.IS_WINDOWS else "gnome" if pu.gnome_shortcuts_available() else "manual")
        self._problem = False
        if self._shortcut_mode == "windows":
            # The shortcut in the config may not work: another app had it
            # when the wheel started.
            state = self._wheel.ask("hotkey-state") or ""
            if state.startswith("off "):
                self._problem = True
                self._error = (f"{self.pretty(self._cfg.hotkey)} is used by another app, so it doesn't work. "
                               "Click here and press another one.")

    # ---- for the shared components (Style, Icon) ----

    @pyqtProperty(str, notify=changed)
    def themeName(self) -> str:
        return self._cfg.theme

    @pyqtProperty(bool, notify=changed)
    def reduceAnimations(self) -> bool:
        return self._cfg.reduce_animations

    @pyqtProperty(bool, constant=True)
    def software(self) -> bool:
        return self._cfg.renderer == "software"

    @pyqtSlot(str, result=str)
    def icon(self, name: str) -> str:
        return icon_path(name)

    # ---- facts ----

    @pyqtProperty(str, constant=True)
    def mode(self) -> str:
        return self._mode

    @pyqtProperty(str, constant=True)
    def version(self) -> str:
        return __version__

    @pyqtProperty(bool, constant=True)
    def isWindows(self) -> bool:
        return pu.IS_WINDOWS

    @pyqtProperty(bool, constant=True)
    def isAppImage(self) -> bool:
        return pu.running_as_appimage()

    @pyqtProperty(bool, constant=True)
    def justInstalled(self) -> bool:
        return self._installed

    @pyqtProperty(str, constant=True)
    def installedPath(self) -> str:
        path = str(pu.installed_appimage())
        home = str(Path.home())
        return "~" + path[len(home):] if path.startswith(home) else path

    @pyqtProperty(str, constant=True)
    def shortcutMode(self) -> str:
        """"windows" (Spindle registers it), "gnome" (Spindle sets it in
        GNOME) or "manual" (other desktops: the user binds the command)."""
        return self._shortcut_mode

    @pyqtProperty(str, constant=True)
    def manualCommand(self) -> str:
        return pu.shortcut_command()

    # ---- shortcut ----

    @pyqtProperty(str, notify=changed)
    def shortcut(self) -> str:
        if self.shortcutMode == "gnome":
            return pu.gnome_shortcut()
        return self._cfg.hotkey if self.shortcutMode == "windows" or self._cfg.setup_done else ""

    @pyqtProperty(str, notify=changed)
    def error(self) -> str:
        return self._error

    @pyqtProperty(bool, notify=changed)
    def shortcutProblem(self) -> bool:
        """The saved shortcut doesn't work (Windows: another app has it)."""
        return self._problem

    @pyqtProperty(str, constant=True)
    def defaultShortcut(self) -> str:
        return pu.default_hotkey()

    @pyqtProperty(str, notify=changed)
    def shortcutWarning(self) -> str:
        """Why the shortcut in use may misbehave (Windows: Alt + Shift is
        also the keyboard-language switch), or ""."""
        if self.shortcutMode != "windows":
            return ""
        return pu.hotkey_warning(self.shortcut)

    @pyqtSlot(str, result=str)
    def pretty(self, text: str) -> str:
        """"Meta" is the Windows key / Super key: say so, and first, the way
        Windows writes its shortcuts ("Win + Alt + S")."""
        parts = text.split("+")
        if "Meta" in parts[:-1]:
            parts = ["Meta"] + [p for p in parts if p != "Meta"]
        return " + ".join(parts).replace("Meta", "Win" if pu.IS_WINDOWS else "Super")

    @pyqtSlot()
    def startCapture(self) -> None:
        """Recording a new shortcut: the current one must not fire meanwhile."""
        if self._capturing:
            return
        self._capturing = True
        if self.shortcutMode == "windows":
            self._wheel.ask("hotkey-pause")
        elif self.shortcutMode == "gnome":
            self._paused_gnome = pu.gnome_shortcut()
            if self._paused_gnome:
                pu.remove_gnome_shortcut()

    @pyqtSlot()
    def endCapture(self) -> None:
        if not self._capturing:
            return
        self._capturing = False
        if self.shortcutMode == "windows":
            self._wheel.ask("hotkey-resume")
        elif self._paused_gnome and not pu.gnome_shortcut():
            pu.set_gnome_shortcut(self._paused_gnome)
        self._paused_gnome = ""

    @pyqtSlot(str, result=bool)
    def setShortcut(self, text: str) -> bool:
        """Use `text` ("Ctrl+Alt+Space"). False (and `error` says why) if
        it can't be used."""
        self._error = ""
        if pu.parse_hotkey(text) is None or pu.gnome_accel(text) is None:
            self._error = "Use Ctrl, Alt or the Super key together with a letter, number, F-key or Space."
        elif self.shortcutMode == "windows":
            # The wheel tries it (None: it isn't running and registers it
            # when it starts); this window is the one that saves it.
            answer = self._wheel.ask(f"hotkey {text}")
            if answer is None or answer == "ok":
                self._save(hotkey=text)
                self._problem = False
            else:
                self._error = f"{self.pretty(text)} is already used by another app. Try another one."
        elif self.shortcutMode == "gnome":
            used_by = pu.gnome_conflict(text)
            if used_by:
                self._error = f"{self.pretty(text)} is already used by GNOME ({used_by}). Try another one."
            else:
                problem = pu.set_gnome_shortcut(text)
                self._error = problem
                self._paused_gnome = ""
                if not problem:
                    self._save(hotkey=text)
        else:
            self._save(hotkey=text)
        self.changed.emit()
        return self._error == ""

    @pyqtSlot(str)
    def copyText(self, text: str) -> None:
        QGuiApplication.clipboard().setText(text)

    # ---- other settings ----

    @pyqtProperty(bool, notify=changed)
    def autostart(self) -> bool:
        return pu.autostart_enabled()

    @pyqtSlot(bool)
    def setAutostart(self, on: bool) -> None:
        try:
            pu.set_autostart(on)
        except OSError as exc:
            self._error = f"Couldn't change it ({exc})"
        self.changed.emit()

    @pyqtProperty(str, notify=changed)
    def theme(self) -> str:
        return self._cfg.theme

    @pyqtSlot(str)
    def setTheme(self, name: str) -> None:
        if name in THEMES:
            self._save(theme=name)

    @pyqtProperty(str, notify=changed)
    def compressPreset(self) -> str:
        return self._cfg.compress_preset

    @pyqtSlot(str)
    def setCompressPreset(self, name: str) -> None:
        if name in PRESETS:
            self._save(compress_preset=name)

    @pyqtProperty(bool, notify=changed)
    def trayIcon(self) -> bool:
        return self._cfg.tray_icon

    @pyqtSlot(bool)
    def setTrayIcon(self, on: bool) -> None:
        self._save(tray_icon=bool(on))

    @pyqtSlot(bool)
    def setReduceAnimations(self, on: bool) -> None:
        self._save(reduce_animations=bool(on))

    @pyqtProperty(bool, notify=changed)
    def softwareRendering(self) -> bool:
        return self._cfg.renderer == "software"

    @pyqtSlot(bool)
    def setSoftwareRendering(self, on: bool) -> None:
        """Takes effect when Spindle restarts: the wheel restarts itself."""
        self._save(renderer="software" if on else "auto", restart=True)

    @pyqtSlot()
    def finishWelcome(self) -> None:
        self._save(setup_done=True)
        self.closeRequested.emit()

    @pyqtSlot()
    def openLogFolder(self) -> None:
        from .. import logs

        logs.show()

    @pyqtProperty(str, constant=True)
    def logFolder(self) -> str:
        from .. import logs

        path = str(logs.log_dir())
        home = str(Path.home())
        return "~" + path[len(home):] if path.startswith(home) and not pu.IS_WINDOWS else path

    @pyqtSlot(bool)
    def removeSpindle(self, delete_settings: bool) -> None:
        """Linux AppImage: undo the install, stop Spindle, close."""
        self._wheel.send_to_running("quit")
        pu.remove_linux_install(delete_settings)
        self.closeRequested.emit()

    def _save(self, restart: bool = False, **values) -> None:
        cfg = config.load()  # the wheel may have changed other values meanwhile
        for key, value in values.items():
            setattr(cfg, key, value)
        config.save(cfg)
        self._cfg = cfg
        self._wheel.send_to_running("restart" if restart else "reload-config")
        self.changed.emit()


def main(argv: list[str]) -> int:
    mode = "welcome" if "--welcome" in argv else "settings"
    from .. import logs

    logs.setup(mode)
    sys.excepthook = lambda *exc: traceback.print_exception(*exc)
    QCoreApplication.setApplicationName(app_name())
    QCoreApplication.setOrganizationName("")
    from ..window import configure_graphics, resolve_renderer

    cfg = config.load()
    configure_graphics(resolve_renderer(cfg.renderer))
    pu.prepare_editor_environment()  # window decorations on Wayland
    app = QGuiApplication(sys.argv)
    app.setApplicationDisplayName(APP_NAME)
    app.setDesktopFileName(APP_ID)
    from ..icons import app_icon

    app.setWindowIcon(app_icon())
    engine = QQmlApplicationEngine()
    from .. import offline

    offline.protect(engine)
    # Owned by the engine: it outlives the QML on teardown.
    bridge = SetupBridge(mode, just_installed="--installed" in argv or bool(os.environ.get("SPINDLE_INSTALLED")),
                         parent=engine)
    engine.rootContext().setContextProperty("editor", bridge)
    engine.rootContext().setContextProperty("setup", bridge)
    engine.load(QUrl.fromLocalFile(str(QML_DIR / "setup" / ("Welcome.qml" if mode == "welcome" else "Settings.qml"))))
    if not engine.rootObjects():
        return 1
    window = engine.rootObjects()[0]
    bridge.closeRequested.connect(window.close)
    window.closing.connect(lambda _e: bridge.endCapture())
    code = app.exec()
    bridge.endCapture()
    del engine
    return code
