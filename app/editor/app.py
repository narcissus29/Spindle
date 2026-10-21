"""Editor process entry point: `main.py --editor <tool> <file> [--software]`.

Opens the file first. If it can't be edited (password-protected PDF,
multi-page TIFF, ...), no window is shown: the reason goes to the wheel,
which shows it in its pill. Otherwise the window opens and the wheel is
told once the first frame is on screen.
"""

from __future__ import annotations

import argparse
import signal
import sys
import traceback
from pathlib import Path

from PyQt6.QtCore import QCoreApplication, QUrl
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlApplicationEngine
from PyQt6.QtQuick import QQuickWindow

from .. import APP_ID, APP_NAME, QML_DIR, app_name, config, platform_utils
from ..icons import icon_path
from ..single_instance import SingleInstance


def build(doc, tool: str, cfg, software: bool):
    """The editor window for an open document: (engine, bridge, window).
    Raises RuntimeError if the QML doesn't load."""
    from .bridge import EditorBridge
    from .provider import DocImageProvider

    engine = QQmlApplicationEngine()
    from .. import offline

    offline.protect(engine)
    # Owned by the engine, so it outlives the QML on teardown (no null `editor`).
    bridge = EditorBridge(doc, tool, cfg, software=software, icon_paths=icon_path, parent=engine)
    engine.addImageProvider("doc", DocImageProvider(doc))
    engine.rootContext().setContextProperty("editor", bridge)
    engine.load(QUrl.fromLocalFile(str(QML_DIR / "editor" / "Editor.qml")))
    if not engine.rootObjects():
        raise RuntimeError("failed to load qml/editor/Editor.qml")
    return engine, bridge, engine.rootObjects()[0]


def main(argv: list[str]) -> int:
    from .. import logs

    logs.setup("editor")
    p = argparse.ArgumentParser(prog="spindle --editor")
    p.add_argument("--editor", nargs=2, metavar=("TOOL", "FILE"), required=True)
    p.add_argument("--software", action="store_true")
    args, _rest = p.parse_known_args(argv)
    tool, file = args.editor

    sys.excepthook = lambda *exc: traceback.print_exception(*exc)
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    QCoreApplication.setApplicationName(app_name())
    QCoreApplication.setOrganizationName("")

    from ..window import _APIS, resolve_renderer

    cfg = config.load()
    renderer = resolve_renderer("software" if args.software else cfg.renderer)
    if renderer in _APIS:
        QQuickWindow.setGraphicsApi(_APIS[renderer])
    platform_utils.prepare_editor_environment()

    app = QGuiApplication(sys.argv)
    app.setApplicationDisplayName(APP_NAME)
    app.setDesktopFileName(APP_ID)
    from ..icons import app_icon

    app.setWindowIcon(app_icon())
    wheel = SingleInstance()

    from .document import OpenError, open_document

    path = Path(file).expanduser().resolve()
    try:
        doc = open_document(path)
    except OpenError as exc:
        print(f"[editor] {path.name}: {exc}", flush=True)
        wheel.send_to_running(f"editor-failed {exc}")
        return 1

    try:
        engine, bridge, window = build(doc, tool, cfg, software=(renderer == "software"))
    except RuntimeError:
        wheel.send_to_running("editor-failed The editor failed to start")
        return 1

    def first_frame() -> None:
        window.frameSwapped.disconnect(first_frame)
        wheel.send_to_running("editor-ready")

    window.frameSwapped.connect(first_frame)

    def first_activation() -> None:
        if window.isActive():
            window.activeChanged.disconnect(first_activation)
            print("[editor] window has focus", flush=True)

    window.activeChanged.connect(first_activation)
    print(f"[editor] {path.name} ({tool}, renderer {renderer}, platform {app.platformName()})", flush=True)
    code = app.exec()
    del engine  # destroy QML before the bridge and the document
    doc.close()
    return code
