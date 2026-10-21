"""The wheel's QML with real mouse events (offscreen, software renderer):
the parked stack's × button, the count badge, the progress ring."""

import pytest
from PyQt6.QtCore import QEventLoop, QPointF, Qt, QTimer, QUrl
from PyQt6.QtQuick import QQuickItem
from PyQt6.QtTest import QTest


def wait(ms=300):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def items(root):
    out = [root]
    for child in root.childItems():
        out += items(child)
    return out


def find(view, name):
    return next(i for i in items(view.rootObject()) if i.objectName() == name)


def shown(it):
    while it is not None:
        if not it.isVisible() or it.opacity() < 0.01:
            return False
        it = it.parentItem()
    return True


@pytest.fixture
def wheel(qapp):
    from app.bridge import Bridge
    from app.config import Config
    from app.window import WheelWindow

    cfg = Config()
    cfg.reduce_animations = True
    b = Bridge(cfg)
    w = WheelWindow(b, cfg, "software")
    w.show_wheel()
    wait(400)
    yield b, w
    b.dismiss()
    wait(300)
    w.shutdown()


def click(view, item):
    p = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p, 600)
    wait()


def test_x_on_the_stack_clears_it(wheel):
    b, w = wheel
    assert b.dragEnter([QUrl.fromLocalFile("/tmp/a.pdf"), QUrl.fromLocalFile("/tmp/b.pdf")]) and b.park()
    assert b.dragEnter([QUrl.fromLocalFile("/tmp/c.pdf")]) and b.park()
    wait()
    pill = find(w.view, "centerPill")
    assert pill.property("count") == 3 and pill.property("heldCount") == 3
    x = find(w.view, "clearStack")
    assert shown(x)
    click(w.view, x)
    assert not b.parked and b.fileCount == 0 and b.is_shown
    wait()
    assert not shown(x)


def test_progress_ring_spins_fills_and_goes(wheel):
    b, w = wheel
    jobs = []
    b.jobRequested.connect(jobs.append)
    assert b.dragEnter([QUrl.fromLocalFile(f"/tmp/{n}.pdf") for n in "abc"])
    assert b.drop([o["name"] for o in b.options].index("DOCX"))
    wait()
    ring, arc, spinner = (find(w.view, n) for n in ("progressRing", "progressArc", "progressSpinner"))
    assert shown(ring) and shown(spinner) and not shown(arc)  # loading: can't tell yet
    assert b.statusText == "File 1/3"
    job = jobs[0]
    b.file_progress(job, 0, 0.2, "Page 12/60")
    wait()
    assert shown(arc) and not shown(spinner) and b.statusText == "File 1/3 · 20%"
    assert abs(ring.property("shown") - 0.2) < 0.01
    b.file_done(job, 0, "", ["/tmp/a.docx"], {})
    wait()
    assert shown(spinner) and ring.property("shown") == 0  # the next file starts from empty
    for i in (1, 2):
        b.file_done(job, i, "", [f"/tmp/{i}.docx"], {})
    wait(600)
    assert not shown(ring)  # done: nothing left drawing


def test_one_file_shows_what_the_helper_says(qapp):
    from app.bridge import Bridge
    from app.config import Config

    b = Bridge(Config())
    jobs = []
    b.jobRequested.connect(jobs.append)
    b.open()
    assert b.dragEnter([QUrl.fromLocalFile("/tmp/book.pdf")])
    assert b.drop([o["name"] for o in b.options].index("DOCX"))
    assert b.statusText == "Working…" and b.progress == -1
    b.file_progress(jobs[0], 0, -1, "Analyzing…")
    assert b.statusText == "Analyzing…" and b.progress == -1
    b.file_progress(jobs[0], 0, 0.12, "Page 12/60")
    assert b.statusText == "Page 12/60" and b.progress == 0.12
    b.file_progress(jobs[0], 0, 0.5, "")
    assert b.statusText == "50%"
