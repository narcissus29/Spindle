"""Drive the real editor window with a script and grab screenshots.

    .venv/bin/python tests/ui/editor_shots.py <file> <out-prefix> <script.py> [tool] [software]

The script is executed with these names available:
    win, bridge (the `editor` object), app, QTest, Qt, QPoint, QPointF
    step(ms)   decorator: run the function `ms` after the previous step
    shot(name) save the window to <out-prefix>-<name>.png
    item(name) find a QML item by objectName
    type_text(s) type a string into whatever has keyboard focus
Steps run in order; the editor exits after the last one.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
sys.excepthook = lambda *e: __import__("traceback").print_exception(*e)

from pathlib import Path

from PyQt6.QtCore import QPoint, QPointF, Qt, QTimer
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQuick import QQuickWindow
from PyQt6.QtTest import QTest

from app import config, platform_utils
from app.window import _APIS

file, out, script = sys.argv[1], sys.argv[2], sys.argv[3]
tool = sys.argv[4] if len(sys.argv) > 4 else "crop"
software = len(sys.argv) > 5 and sys.argv[5] == "software"
if software:
    QQuickWindow.setGraphicsApi(_APIS["software"])
platform_utils.prepare_editor_environment()
app = QGuiApplication(sys.argv)

from app.editor.app import build
from app.editor.document import open_document

doc = open_document(Path(file))
engine, bridge, win = build(doc, tool, config.Config(), software)
steps = []


def step(ms):
    def deco(fn):
        steps.append((ms, fn))
        return fn
    return deco


def shot(name):
    img = win.grabWindow()
    img.save(f"{out}-{name}.png")
    print("shot", name, flush=True)


def item(name, root=None):
    root = root or win.contentItem()
    if root.objectName() == name:
        return root
    for child in root.childItems():
        found = item(name, child)
        if found is not None:
            return found
    return None


def type_text(text):
    from PyQt6.QtCore import QEvent
    from PyQt6.QtGui import QKeyEvent

    for ch in text:
        for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            QGuiApplication.sendEvent(win, QKeyEvent(kind, Qt.Key.Key_unknown, Qt.KeyboardModifier.NoModifier, ch))


def run(i=0):
    if i >= len(steps):
        app.exit(0)  # not quit(): the window refuses to close with unsaved edits
        return
    ms, fn = steps[i]

    def go():
        try:
            fn()
        except Exception:  # report it, keep going: later shots still help
            import traceback

            traceback.print_exc()
        run(i + 1)

    QTimer.singleShot(ms, go)


exec(open(script).read())
win.show()
run()
app.exec()
sys.stdout.flush()
os._exit(0)
