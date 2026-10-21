"""The editor canvas with real mouse / key events: marks stay on the page,
and a highlighter stroke is one even tint on screen and in the saved file.

Runs offscreen on the software renderer by default. Run it on the GPU
renderer too, where a see-through stroke would darken its own overlaps
(the software renderer never shows that):

    QT_QPA_PLATFORM=wayland .venv/bin/python -m pytest tests/test_editor_canvas.py
"""

import math

import pytest
from PyQt6.QtCore import QEventLoop, QPointF, Qt, QTimer

from app.config import Config
from app.editor import document
from tests.conftest import make_image

W, H = 1200, 800


def wait(ms=300):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


@pytest.fixture
def canvas(qapp, tmp_path):
    """An editor on a plain white W x H image, Annotate tool."""
    from PyQt6.QtGui import QColor, QImage

    from app.editor.app import build

    img = QImage(W, H, QImage.Format.Format_RGB32)
    img.fill(QColor("white"))
    src = tmp_path / "white.png"
    img.save(str(src))
    doc = document.open_document(src)
    engine, bridge, win = build(doc, "annotate", Config(), software=True)
    win.resize(1240, 820)
    wait(600)

    def find(name, root=None):
        root = root or win.contentItem()
        if root.objectName() == name:
            return root
        for child in root.childItems():
            hit = find(name, child)
            if hit is not None:
                return hit
        return None

    view = find("view")
    layer = view.property("marksLayer")

    class C:
        pass

    c = C()
    c.win, c.bridge, c.layer, c.src, c.engine = win, bridge, layer, src, engine

    def at(x, y):  # content units -> window point
        p = layer.mapToItem(win.contentItem(), QPointF(x, y))
        from PyQt6.QtCore import QPoint

        return QPoint(round(p.x()), round(p.y()))

    def drag(points, steps=8):
        from PyQt6.QtTest import QTest

        QTest.mousePress(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at(*points[0]))
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            for i in range(1, steps + 1):
                t = i / steps
                QTest.mouseMove(win, at(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
        QTest.mouseRelease(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, at(*points[-1]))
        wait(100)

    c.at, c.drag = at, drag
    yield c
    win.close()
    del engine


# ------------------------------------------------------------ on the page ---

def test_a_stroke_cannot_start_off_the_page(canvas):
    canvas.bridge.setAnnotateTool("pen")
    canvas.drag([(-30, 400), (300, 400)])
    assert canvas.bridge.marks == []
    canvas.drag([(30, 400), (300, 400)])
    assert len(canvas.bridge.marks) == 1


@pytest.mark.parametrize("tool", ["rect", "arrow"])
def test_shapes_are_clamped_to_the_page(canvas, tool):
    canvas.bridge.setAnnotateTool(tool)
    canvas.drag([(1000, 600), (1500, 1100)])
    [m] = canvas.bridge.marks
    if tool == "rect":
        x, y, w, h = m["rect"]
        assert x + w <= W and y + h <= H and (x + w, y + h) == pytest.approx((W, H), abs=1)
    else:
        assert m["p2"] == pytest.approx([W, H], abs=1)


def test_redaction_boxes_are_clamped(canvas):
    canvas.bridge.setTool("redact")
    wait(100)
    canvas.drag([(1100, 50), (1400, -200)])
    [box] = canvas.bridge.redactions
    x, y, w, h = box["rect"]
    assert x + w <= W and y >= 0 and w > 90 and h > 40


def test_moving_a_mark_stops_at_the_edge(canvas):
    b = canvas.bridge
    mid = b.addMark({"type": "rect", "color": "#1e5bd8", "width": 4, "rect": [100, 100, 200, 100]})
    b.setAnnotateTool("select")
    canvas.drag([(200, 150), (4000, 150)], steps=4)
    [m] = b.marks
    assert m["id"] == mid and m["rect"][0] + m["rect"][2] <= W and m["rect"][0] > 800


def test_typed_text_wraps_and_stays_inside(canvas):
    from PyQt6.QtCore import QEvent
    from PyQt6.QtGui import QGuiApplication, QKeyEvent
    from PyQt6.QtTest import QTest

    b = canvas.bridge
    b.setAnnotateTool("text")
    b.setWidthIndex(3)
    QTest.mouseClick(canvas.win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, canvas.at(1150, 790))
    wait(100)
    for ch in "the quick brown fox jumps over the lazy dog " * 3:
        for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            QGuiApplication.sendEvent(canvas.win, QKeyEvent(kind, Qt.Key.Key_unknown, Qt.KeyboardModifier.NoModifier, ch))
    QTest.keyClick(canvas.win, Qt.Key.Key_Return)
    wait(100)
    [m] = b.marks
    x, y, w, h = m["rect"]
    assert x >= 0 and y >= 0 and x + w <= W + 0.5 and y + h <= H + 0.5
    assert h > m["size"] * 2  # wrapped onto several lines
    # the saved file draws it in the same box
    b.save()
    from tests.test_editor_bridge import wait_for

    name = wait_for(b.saved)[0]
    from PyQt6.QtGui import QImage

    saved = QImage(str(canvas.src.with_name(name)))
    dark = [(px, py) for px in range(0, W, 3) for py in range(0, H, 3) if saved.pixelColor(px, py).lightness() < 200]
    assert dark and min(p[0] for p in dark) >= x - 2 and max(p[1] for p in dark) <= y + h + 2


def test_python_side_clamps_too(canvas):
    b = canvas.bridge
    b.addMark({"type": "text", "color": "#000000", "size": 20, "text": "Edge", "rect": [1190, 790, 60, 24]})
    x, y, w, h = b.marks[0]["rect"]
    assert x + w <= W and y + h <= H
    b.addRedaction(-50, -50, 100, 100)
    assert b.redactions[0]["rect"] == [0, 0, 50, 50]


def test_marks_off_the_page_are_clipped_on_screen_and_in_the_file(canvas):
    """A freehand stroke may run off the page: both show only the part on it."""
    from PyQt6.QtGui import QImage

    from tests.test_editor_bridge import wait_for

    b = canvas.bridge
    b.addMark({"type": "pen", "color": "#ff0000", "width": 20, "points": [[-200, 400], [300, 400]]})
    wait(300)
    screen = canvas.win.grabWindow()
    on = screen.pixelColor(canvas.at(40, 400))
    off = screen.pixelColor(canvas.at(-40, 400))
    assert on.red() > 200 and on.green() < 60
    assert not (off.red() > 200 and off.green() < 60)  # canvas background, not red
    b.save()
    saved = QImage(str(canvas.src.with_name(wait_for(b.saved)[0])))
    c = saved.pixelColor(2, 400)
    assert c.red() > 200 and c.green() < 60 and saved.width() == W


# ------------------------------------------------------------ highlighter ---

def _zigzag(n=320):
    """A long stroke that crosses itself many times."""
    return [[150 + i * 2.6, 400 + 160 * math.sin(i / 7.0) * math.cos(i / 23.0)] for i in range(n)] \
        + [[150 + (320 - i) * 2.6, 400 + 120 * math.sin(i / 5.0)] for i in range(320)]


def _spread(colors):
    return max(max(ch) - min(ch) for ch in zip(*colors))


def test_highlighter_is_one_even_tint_on_screen_and_in_the_file(canvas):
    from PyQt6.QtGui import QImage

    from tests.test_editor_bridge import wait_for

    b = canvas.bridge
    pts = _zigzag()
    b.addMark({"type": "highlight", "color": "#ff0000", "width": 40, "points": pts})
    wait(400)
    screen = canvas.win.grabWindow()
    on_screen = [screen.pixelColor(canvas.at(*p)).getRgb()[:3] for p in pts[::4]]
    assert _spread(on_screen) <= 3, sorted(set(on_screen))[:6]
    r, g, bl = on_screen[0]
    assert r > 240 and 130 < g < 185 and 130 < bl < 185  # red at ~38% over white, not solid

    b.save()
    saved = QImage(str(canvas.src.with_name(wait_for(b.saved)[0])))
    in_file = [saved.pixelColor(round(x), round(y)).getRgb()[:3] for x, y in pts[::4]]
    assert _spread(in_file) <= 2, sorted(set(in_file))[:6]
    assert max(abs(a - c) for a, c in zip(in_file[0], on_screen[0])) <= 6  # same tint as the screen
