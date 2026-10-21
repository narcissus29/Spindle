"""The Info panel with real mouse / key events: Remove all, Save clean
copy, editing a field by clicking it, Esc cancelling an edit."""

import pytest
from PyQt6.QtCore import QEvent, QEventLoop, QPointF, Qt, QTimer
from PyQt6.QtGui import QGuiApplication, QKeyEvent
from PyQt6.QtTest import QTest

from app.config import Config
from app.editor import document, state as st
from tests.conftest import make_camera_photo
from tests.test_editor_bridge import wait_for


def wait(ms=300):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


@pytest.fixture
def info(qapp, tmp_path):
    from app.editor.app import build

    src = make_camera_photo(tmp_path / "trip.jpg")
    engine, bridge, win = build(document.open_document(src), "metadata", Config(), software=True)
    win.resize(1240, 820)
    for _ in range(50):
        if bridge.metaStatus == "ready":
            break
        wait(100)
    wait(500)

    def all_items(root=None, acc=None):
        root = root or win.contentItem()
        acc = [] if acc is None else acc
        acc.append(root)
        for child in root.childItems():
            all_items(child, acc)
        return acc

    def shown(it):
        while it is not None:
            if not it.isVisible() or it.opacity() < 0.01:
                return False
            it = it.parentItem()
        return True

    def button(text):
        hits = [i for i in all_items() if i.metaObject().className().startswith("PillButton")
                and i.property("text") == text and shown(i)]
        assert hits, f"no visible button {text!r}"
        return hits[0]

    def row(key):
        for i in all_items():
            if i.metaObject().className().startswith("MetaRow") and shown(i):
                item = i.property("item")
                item = item.toVariant() if hasattr(item, "toVariant") else item
                if item and item.get("key") == key:
                    return i
        raise AssertionError(f"no row {key}")

    def click(it, x=None, y=None):
        p = it.mapToScene(QPointF(it.width() / 2 if x is None else x, it.height() / 2 if y is None else y))
        QTest.mouseClick(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p.toPoint())
        wait(250)

    def type_text(text):
        for ch in text:
            for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
                QGuiApplication.sendEvent(win, QKeyEvent(kind, Qt.Key.Key_unknown, Qt.KeyboardModifier.NoModifier, ch))

    class I:
        pass

    i = I()
    i.win, i.bridge, i.src = win, bridge, src
    i.button, i.row, i.click, i.type_text = button, row, click, type_text
    i.all_items, i.shown = all_items, shown
    yield i
    bridge._history.mark_saved()  # let the window close without asking
    win.close()
    del engine


def test_remove_all_then_save_clean_copy(info):
    info.click(info.button("Remove all"))
    assert info.bridge.metaClean
    saved = []
    info.bridge.saved.connect(saved.append)
    info.click(info.button("Save clean copy"))
    if not saved:
        wait_for(info.bridge.saved)
    name = saved[0]
    assert name == "trip (clean).jpg"
    data = info.src.with_name(name).read_bytes()
    assert b"Google" not in data and b"taken at home" not in data
    info.click(info.button("Undo"))
    assert not info.bridge.metaClean and st.meta(info.bridge._state) == st.NO_META


def test_click_a_field_type_and_press_enter(info):
    artist = info.row("field:artist")
    info.click(artist, 30, 30)  # on the value
    assert artist.property("editing")
    QTest.keyClick(info.win, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    info.type_text("Zoë Example")
    QTest.keyClick(info.win, Qt.Key.Key_Return)
    wait(200)
    assert st.meta(info.bridge._state)["set"] == {"field:artist": "Zoë Example"}
    assert info.row("field:artist").property("item")["state"] == "edited"


def test_esc_cancels_an_edit_and_keeps_the_window(info):
    date = info.row("field:datetaken")
    info.click(date, 30, 30)
    info.type_text("garbage")
    QTest.keyClick(info.win, Qt.Key.Key_Escape)
    wait(200)
    assert info.win.isVisible() and not date.property("editing")
    assert st.meta(info.bridge._state) == st.NO_META


def test_bad_date_shows_the_reason_and_stays_open(info):
    date = info.row("field:datetaken")
    info.click(date, 30, 30)
    QTest.keyClick(info.win, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    info.type_text("next tuesday")
    QTest.keyClick(info.win, Qt.Key.Key_Return)
    wait(200)
    assert date.property("editing") and "date" in date.property("error")
    assert st.meta(info.bridge._state) == st.NO_META


def test_remove_one_entry_with_its_button(info):
    gps = info.row("gps")
    trash = [c for c in gps.findChildren(type(gps)) if c.property("icon") == "trash" and c.isVisible()]
    assert trash
    info.click(trash[0])
    assert st.meta(info.bridge._state)["drop"] == ["gps"]
    assert info.row("gps").property("item")["state"] == "removed"


def test_keep_location_checkbox_in_the_save_sheet(info):
    from PIL import ExifTags, Image

    b = info.bridge
    b.setCrop(0, 0, 0.5, 0.5)
    QTest.keyClick(info.win, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    wait(400)
    boxes = [i for i in info.all_items() if i.metaObject().className().startswith("CheckBox")
             and i.property("text") == "Keep location" and info.shown(i)]
    assert boxes, "no Keep location box"
    info.click(boxes[0])
    saved = []
    b.saved.connect(saved.append)
    QTest.keyClick(info.win, Qt.Key.Key_Return)
    if not saved:
        wait_for(b.saved)
    with Image.open(info.src.with_name(saved[0])) as im:
        assert im.getexif().get_ifd(ExifTags.IFD.GPSInfo)  # ticked: kept
