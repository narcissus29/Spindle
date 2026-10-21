"""The editor's QObject (what QML calls) and its QML, loaded offscreen."""

import pytest
from PyQt6.QtCore import QEventLoop, QTimer

from app.config import Config
from app.editor import document
from app.editor.bridge import EditorBridge
from app.icons import icon_path
from tests.conftest import make_image, make_pdf, make_photo


def bridge_for(path, tool="crop"):
    return EditorBridge(document.open_document(path), tool, Config(), software=False, icon_paths=icon_path)


def wait_for(signal, ms=10000):
    got = []
    loop = QEventLoop()
    signal.connect(lambda *a: (got.append(a), loop.quit()))
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
    return got[0] if got else None


def test_turn_is_announced_before_the_new_state(qapp, tmp_path):
    """QML starts the turn animation on `turned`, before geometry changes."""
    b = bridge_for(make_photo(tmp_path / "a.jpg", size=(200, 100)))
    order = []
    b.turned.connect(lambda op: order.append(("turned", op, b.rot)))
    b.changed.connect(lambda: order.append(("changed", b.rot)))
    b.rotate(1)
    assert order[0][:2] == ("turned", "cw") and order[1] == ("changed", 90)
    order.clear()
    b.undo()
    assert order[0][:2] == ("turned", "ccw") and b.rot == 0
    order.clear()
    b.flip("v")
    assert order[0][:2] == ("turned", "v")
    b.undo()
    b.redo()
    assert b.mirror and b.rot == 180


def test_crop_undo_labels_and_modified(qapp, tmp_path):
    b = bridge_for(make_photo(tmp_path / "a.jpg", size=(200, 100)))
    assert not b.modified and not b.canUndo and b.outputName == "a (cropped).jpg"
    b.setCrop(0.1, 0.1, 0.5, 0.5)
    assert b.hasCrop and b.modified and b.undoText == "Crop"
    b.setCrop(0.1, 0.1, 0.5, 0.5)  # same again: no new step
    b.undo()
    assert not b.hasCrop and not b.modified and b.redoText == "Crop"
    b.setAdjust("contrast", 0.3)
    assert b.outputName == "a (edited).jpg" and b.contrast == pytest.approx(0.3)
    b.resetAdjust()
    assert b.contrast == 0 and b.undoText == "Reset colors"


def test_save_runs_off_the_ui_thread_and_clears_modified(qapp, tmp_path):
    src = make_photo(tmp_path / "trip.jpg", size=(400, 300))
    b = bridge_for(src)
    b.rotate(-1)
    b.save()
    assert b.saving
    name = wait_for(b.saved)
    assert name == ("trip (edited).jpg",) and not b.saving and not b.modified
    assert (tmp_path / "trip (edited).jpg").exists()
    assert b.outputName == "trip (edited) (1).jpg"  # the next save never overwrites


def test_last_page_cannot_be_deleted(qapp, tmp_path):
    b = bridge_for(make_pdf(tmp_path / "one.pdf", pages=1))
    b.setRotateAllPages(True)
    b.deletePage()  # refused: the last page stays
    assert not b.pageDeleted and not b.canUndo


def test_pdf_pages_crop_all_and_rotate_one(qapp, tmp_path):
    b = bridge_for(make_pdf(tmp_path / "doc.pdf", pages=3), tool="edit")
    b.goToPage(1)
    b.rotate(1)
    assert [p["rot"] for p in b.pages] == [0, 90, 0]
    b.setRotateAllPages(True)
    b.rotate(-1)
    assert [p["rot"] for p in b.pages] == [270, 0, 270]
    b.deletePage()
    assert b.pageDeleted and b.keptPages == 2
    b.setCrop(0, 0, 0.5, 0.5)  # crop all (the default) includes the deleted page
    assert all(p["cropped"] for p in b.pages)
    b.setCropAllPages(False)
    b.goToPage(0)
    b.clearCrop()
    assert [p["cropped"] for p in b.pages] == [False, True, True]
    b.goToPage(1)
    b.restorePage()
    assert b.keptPages == 3


@pytest.mark.parametrize("kind", ["image", "pdf"])
def test_qml_loads_cleanly(qapp, tmp_path, kind):
    """The whole editor window loads offscreen without a single QML warning."""
    from PyQt6.QtCore import qInstallMessageHandler

    from app.editor.app import build

    src = make_photo(tmp_path / "p.jpg", size=(300, 200)) if kind == "image" else make_pdf(tmp_path / "d.pdf", pages=3)
    warnings = []
    previous = qInstallMessageHandler(lambda mode, ctx, msg: warnings.append(msg) if "qml" in msg.lower() or "file:" in msg else None)
    try:
        doc = document.open_document(src)
        engine, bridge, window = build(doc, "crop", Config(), software=True)
        loop = QEventLoop()
        QTimer.singleShot(600, loop.quit)
        loop.exec()
        for tool in ("edit", "annotate", "redact", "metadata", "crop"):
            bridge.setTool(tool)
        bridge.rotate(1)
        loop = QEventLoop()
        QTimer.singleShot(600, loop.quit)
        loop.exec()
        window.close()
        del engine
    finally:
        qInstallMessageHandler(previous)
    assert warnings == []


def test_transparent_png_reports_alpha(qapp, tmp_path):
    b = bridge_for(make_image(tmp_path / "logo.png", "PNG", alpha=True))
    assert b.hasAlpha and not b.isPdf and b.formatLabel == "PNG"


# ---- Annotate / Redact ----

def test_marks_add_undo_select_move_edit_delete(qapp, tmp_path):
    b = bridge_for(make_photo(tmp_path / "a.jpg", size=(400, 300)), tool="annotate")
    assert b.addMark({"type": "nonsense"}) == -1 and not b.canUndo
    assert b.addMark({"type": "pen", "color": "#e5322d", "width": 3, "points": []}) == -1
    pen = b.addMark({"type": "pen", "color": "#e5322d", "width": 3.0, "points": [[10, 10], [50, 20]]})
    text = b.addMark({"type": "text", "color": "#111111", "size": 18.4, "text": "Hi", "rect": [100, 100, 30, 20]})
    assert [m["type"] for m in b.marks] == ["pen", "text"] and b.undoText == "Text"
    assert b.marks[1]["size"] == 18 and b.outputName == "a (annotated).jpg"
    assert b.markAt(30, 15, 2) == pen and b.markAt(110, 110, 0) == text and b.markAt(300, 250, 2) == -1
    b.selectMark(text)
    b.setMarkColor("#2fa84f")  # recolors the selected mark too
    assert b.marks[1]["color"] == "#2fa84f" and b.undoText == "Change color"
    b.moveMark(text, 5, -5)
    assert b.marks[1]["rect"][:2] == [105, 95] and b.undoText == "Move"
    b.updateMark(text, {"text": "Hello", "rect": [105, 95, 50, 20]})
    assert b.marks[1]["text"] == "Hello"
    b.updateMark(text, {"text": "   "})  # emptied: the mark goes
    assert [m["type"] for m in b.marks] == ["pen"]
    b.undo()
    assert b.marks[1]["text"] == "Hello"
    b.deleteMark(pen)
    assert [m["type"] for m in b.marks] == ["text"] and b.selectedMark == -1
    for _ in range(6):
        b.undo()
    assert b.marks == [] and not b.modified


def test_marks_follow_the_page_on_screen(qapp, tmp_path):
    b = bridge_for(make_pdf(tmp_path / "d.pdf", pages=2), tool="annotate")
    b.addMark({"type": "rect", "color": "#1e5bd8", "width": 2, "rect": [10, 10, 50, 50]})
    b.goToPage(1)
    assert b.marks == []
    b.goToPage(0)
    assert len(b.marks) == 1 and b.hasMarks


def test_redaction_boxes_and_search(qapp, tmp_path):
    import pymupdf

    src = tmp_path / "s.pdf"
    d = pymupdf.open()
    for i in range(3):
        d.new_page().insert_text((72, 100), f"Page {i}: call Jane Doe or jane doe", fontsize=12)
    d.save(src)
    d.close()
    b = bridge_for(src, tool="redact")
    b.addRedaction(10, 10, 0, 50)  # empty: ignored
    assert not b.canUndo
    b.addRedaction(10, 10, 40, 20)
    box = b.redactions[0]["id"]
    assert b.redactionAt(20, 20) == box and b.redactionAt(100, 100) == -1
    b.search("Jane Doe", True, False)
    assert b.searching
    wait_for(b.searchChanged)
    assert not b.searching and len(b.searchResults) == 3 and b.checkedCount == 3  # match case: one per page
    b.setResultChecked(1, False)
    b.redactChecked()
    assert b.undoText == "Redact 2 matches" and b.redactionCount == 3
    assert [r["page"] for r in b.searchResults] == [1]  # the unticked one stays listed
    out = None
    b.save()
    out = wait_for(b.saved)[0]
    assert out == "s (redacted).pdf"
    text = "".join(p.get_text() for p in pymupdf.open(tmp_path / out))
    assert text.count("Jane Doe") == 1 and text.count("jane doe") == 3
    b.clearRedactions()
    assert b.redactionCount == 0


def test_save_passes_flatten(qapp, tmp_path):
    import pymupdf

    b = bridge_for(make_pdf(tmp_path / "f.pdf", pages=1), tool="annotate")
    b.addMark({"type": "rect", "color": "#1e5bd8", "width": 2, "rect": [10, 10, 50, 50]})
    b.save(True)
    name = wait_for(b.saved)[0]
    with pymupdf.open(tmp_path / name) as doc:
        assert list(doc[0].annots()) == [] and doc[0].get_drawings()
