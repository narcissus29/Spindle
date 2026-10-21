"""Editor: Crop "Exact size" (W x H px) and "Limit file size" in the save
sheet (reusing handlers/target.py)."""

import pytest
from PyQt6.QtCore import QEventLoop, QPointF, Qt, QTimer
from PyQt6.QtTest import QTest

from app.config import Config
from app.editor import document, state as st
from app.editor.bridge import EditorBridge
from app.icons import icon_path
from tests.conftest import make_camera_photo, make_photo, make_photo_pdf
from tests.test_editor_bridge import wait_for


def bridge_for(path, tool="crop"):
    return EditorBridge(document.open_document(path), tool, Config(), software=False, icon_paths=icon_path)


def saved(b):
    got = []
    b.saved.connect(got.append)
    b.save()
    if not got:
        wait_for(b.saved)
    return b._doc.path.with_name(got[0])


def size_of(path):
    from PyQt6.QtGui import QImageReader

    r = QImageReader(str(path))
    r.setAutoTransform(True)
    s = r.size()
    return (s.height(), s.width()) if r.transformation().value & 4 else (s.width(), s.height())


# ------------------------------------------------------------- exact size ---

def test_fit_crop_keeps_the_shape_and_center():
    crop = st.fit_crop(None, 200 / 230, 320, 240)  # a portrait shape in a landscape picture
    x, y, w, h = crop
    assert h == pytest.approx(1) and w * 320 / (h * 240) == pytest.approx(200 / 230)
    assert x + w / 2 == pytest.approx(0.5)


def test_exact_size_saves_exactly_that_many_pixels(qapp, tmp_path):
    src = make_photo(tmp_path / "id.jpg", size=(1200, 900))
    b = bridge_for(src)
    b.setOutputSize(200, 230)
    assert (b.outputWidth, b.outputHeight) == (200, 230) and b.hasCrop
    assert b.outputName == "id (200x230).jpg"
    out = saved(b)
    assert out.name == "id (200x230).jpg" and size_of(out) == (200, 230)


def test_exact_size_turns_with_the_picture_and_undoes(qapp, tmp_path):
    b = bridge_for(make_photo(tmp_path / "p.jpg", size=(800, 600)))
    b.setOutputSize(140, 60)
    b.rotate(1)
    assert (b.outputWidth, b.outputHeight) == (60, 140)
    b.undo()
    b.undo()
    assert b.outputWidth == 0 and not b.hasCrop
    b.setOutputSize(8, 8)  # too small: refused
    assert b.outputWidth == 0


def test_exact_size_on_a_turned_phone_photo(qapp, tmp_path):
    src = make_camera_photo(tmp_path / "phone.jpg", size=(320, 240), orientation=6)  # shown 240 x 320
    b = bridge_for(src)
    b.setOutputSize(120, 160)
    out = saved(b)
    assert size_of(out) == (120, 160)


# ----------------------------------------------------------- size limit ---

def test_limit_file_size_on_an_edited_photo(qapp, tmp_path):
    src = make_camera_photo(tmp_path / "trip.jpg", size=(2400, 1800))
    b = bridge_for(src)
    b.setCrop(0.1, 0.1, 0.8, 0.8)
    assert b.setSaveLimit("lots") != "" and b.saveLimit == 0
    assert b.setSaveLimit("60 KB") == "" and b.saveLimit == 60_000
    assert b.outputName == "trip (cropped, 60 KB).jpg" and not b.locationChoice
    out = saved(b)
    data = out.read_bytes()
    assert out.name == "trip (cropped, 60 KB).jpg" and len(data) <= 60_000 and len(data) >= 0.85 * 60_000
    assert b"Exif" not in data and b"Google" not in data  # no metadata: it takes space
    assert b.lastSaveNote.startswith(f"{len(data) // 1000} KB") and not b.lastSaveNote.startswith("smallest")


def test_form_photo_exact_size_and_limit_together(qapp, tmp_path):
    src = make_photo(tmp_path / "me.png", size=(1600, 1200), fmt="PNG")
    b = bridge_for(src)
    b.setOutputSize(200, 230)
    b.setSaveLimit("20 KB")
    assert b.outputName == "me (200x230, 20 KB).jpg"
    out = saved(b)
    assert out.suffix == ".jpg" and out.stat().st_size <= 20_000 and size_of(out) == (200, 230)


def test_unreachable_limit_says_so(qapp, tmp_path):
    b = bridge_for(make_photo(tmp_path / "p.jpg", size=(400, 300)))
    b.setCrop(0, 0, 0.9, 0.9)
    b.setSaveLimit("1 KB")
    out = saved(b)
    if out.stat().st_size > 1000:
        assert b.lastSaveNote.startswith("smallest possible") and "over 1 KB" in b.lastSaveNote


def test_limit_file_size_on_a_pdf(qapp, tmp_path):
    src = make_photo_pdf(tmp_path / "report.pdf", make_photo(tmp_path / "ph.jpg", size=(3000, 2200)))
    b = bridge_for(src, tool="edit")
    b.rotate(1)
    b.setSaveLimit("150 KB")
    out = saved(b)
    assert out.name == "report (edited, 150 KB).pdf" and out.stat().st_size <= 150_000


def test_no_limit_after_clearing(qapp, tmp_path):
    b = bridge_for(make_photo(tmp_path / "p.jpg", size=(400, 300)))
    b.setSaveLimit("10 KB")
    b.setSaveLimit("")
    b.setCrop(0, 0, 0.5, 0.5)
    assert b.outputName == "p (cropped).jpg"


# ------------------------------------------------------- with real input ---

def wait(ms=300):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def test_exact_size_fields_and_limit_box_by_hand(qapp, tmp_path):
    """Click "Exact size", type 200 x 230, then tick "Limit file size",
    type 25 and save: a 200 x 230 JPEG under 25,000 bytes."""
    from PyQt6.QtCore import QEvent
    from PyQt6.QtGui import QGuiApplication, QKeyEvent

    from app.editor.app import build

    src = make_photo(tmp_path / "form.jpg", size=(1200, 900))
    engine, b, win = build(document.open_document(src), "crop", Config(), software=True)
    win.resize(1240, 820)
    wait(700)

    def items(root=None, acc=None):
        root = root or win.contentItem()
        acc = [] if acc is None else acc
        acc.append(root)
        for child in root.childItems():
            items(child, acc)
        return acc

    def shown(it):
        while it is not None:
            if not it.isVisible() or it.opacity() < 0.01:
                return False
            it = it.parentItem()
        return True

    def find(cls, text=None, name=None):
        for it in items():
            if it.metaObject().className().startswith(cls) and shown(it) \
                    and (text is None or it.property("text") == text) and (name is None or it.objectName() == name):
                return it
        raise AssertionError(f"no {cls} {text or name}")

    def click(it):
        p = it.mapToScene(QPointF(it.width() / 2, it.height() / 2)).toPoint()
        QTest.mouseClick(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p)
        wait(250)

    def type_text(text):
        for ch in text:
            for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
                QGuiApplication.sendEvent(win, QKeyEvent(kind, Qt.Key.Key_unknown, Qt.KeyboardModifier.NoModifier, ch))

    try:
        click(find("Chip", "Exact size"))
        assert b.outputWidth > 0  # starts from the crop as it is
        click(find("TextField", name="exactW"))
        QTest.keyClick(win, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        type_text("200")
        QTest.keyClick(win, Qt.Key.Key_Tab)
        click(find("TextField", name="exactH"))
        QTest.keyClick(win, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        type_text("230")
        QTest.keyClick(win, Qt.Key.Key_Return)
        wait(200)
        assert (b.outputWidth, b.outputHeight) == (200, 230)
        QTest.keyClick(win, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
        wait(400)
        click(find("CheckBox", "Limit file size"))
        click(find("TextField", name="limitField"))
        QTest.keyClick(win, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        type_text("25")
        wait(100)
        assert b.saveLimit == 25_000 and b.outputName == "form (200x230, 25 KB).jpg"
        got = []
        b.saved.connect(got.append)
        click(find("PillButton", "Save"))
        if not got:
            wait_for(b.saved)
        out = src.with_name(got[0])
        assert out.stat().st_size <= 25_000 and size_of(out) == (200, 230)
    finally:
        b._history.mark_saved()
        win.close()
        del engine
