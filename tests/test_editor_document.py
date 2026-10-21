import itertools

import numpy as np
import pytest

from app.editor import document, state as st
from tests.conftest import add_exif_orientation, make_image, make_multipage_tiff, make_pdf, make_photo


def _array(img):
    from PyQt6.QtGui import QImage

    img = img.convertToFormat(QImage.Format.Format_RGB888)
    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes())
    rows = np.frombuffer(ptr, np.uint8).reshape(img.height(), img.bytesPerLine())
    return rows[:, :img.width() * 3].reshape(img.height(), img.width(), 3).astype(np.int16)


# ------------------------------------------------------------------ images ---

def test_exif_rotated_photo_opens_upright(qapp, tmp_path):
    src = make_photo(tmp_path / "phone.jpg", size=(400, 200))
    add_exif_orientation(src, 6)  # shown rotated a quarter turn
    doc = document.open_document(src)
    assert doc.page_size(0) == (200.0, 400.0)
    assert (doc.preview.width(), doc.preview.height()) == (200, 400)


def test_big_image_gets_a_smaller_preview(qapp, tmp_path):
    src = make_photo(tmp_path / "big.jpg", size=(5000, 2500), quality=80)
    doc = document.open_document(src)
    assert doc.page_size(0) == (5000.0, 2500.0)
    assert max(doc.preview.width(), doc.preview.height()) <= document.PREVIEW_MAX


def test_multi_page_tiff_is_refused(qapp, tmp_path):
    with pytest.raises(document.OpenError, match="Multi-page TIFF"):
        document.open_document(make_multipage_tiff(tmp_path / "scan.tiff"))


def test_unknown_file_is_refused(tmp_path):
    (tmp_path / "x.pdf").write_bytes(b"hello")
    with pytest.raises(document.OpenError):
        document.open_document(tmp_path / "x.pdf")


def test_image_crop_rotate_saved_full_size(qapp, tmp_path):
    from PyQt6.QtGui import QImage

    src = make_photo(tmp_path / "trip.jpg", size=(1000, 600))
    doc = document.open_document(src)
    s = {**st.turn_image(doc.initial_state(), "cw"), "crop": [0.1, 0.2, 0.5, 0.5]}
    out = doc.save(s)
    assert out.name == "trip (edited).jpg"
    saved = QImage(str(out))
    # rotated: 600 x 1000, cropped to half of each side
    assert (saved.width(), saved.height()) == (300, 500)
    assert src.read_bytes() == make_photo(tmp_path / "again.jpg", size=(1000, 600)).read_bytes()  # untouched


def test_saved_image_matches_the_preview(qapp, tmp_path):
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QImage

    src = make_photo(tmp_path / "p.png", size=(640, 400), fmt="PNG")
    doc = document.open_document(src)
    s = st.turn_image(st.turn_image(doc.initial_state(), "ccw"), "h")
    s = {**s, "crop": [0.2, 0.1, 0.6, 0.7],
         "adjust": {"brightness": 0.1, "contrast": 0.3, "saturation": -0.4}}
    out = doc.save(s)
    assert out.name == "p (edited).png"
    from app.editor import imaging

    preview = imaging.render_image(doc.preview, s)
    saved = QImage(str(out)).scaled(preview.size(), Qt.AspectRatioMode.IgnoreAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation)
    assert np.abs(_array(saved) - _array(preview)).mean() < 2


def test_transparency_kept_and_format_kept(qapp, tmp_path):
    from PyQt6.QtGui import QImage

    src = make_image(tmp_path / "logo.png", "PNG", size=(64, 48), alpha=True)
    doc = document.open_document(src)
    out = doc.save({**doc.initial_state(), "crop": [0, 0, 0.5, 0.5]})
    assert out.name == "logo (cropped).png"
    img = QImage(str(out))
    assert img.hasAlphaChannel() and img.pixelColor(0, 0).alpha() == 0
    assert (img.width(), img.height()) == (32, 24)


def test_saving_twice_never_overwrites(qapp, tmp_path):
    src = make_image(tmp_path / "a.png", "PNG")
    doc = document.open_document(src)
    s = {**doc.initial_state(), "crop": [0, 0, 0.5, 0.5]}
    first, second = doc.save(s), doc.save(s)
    assert first.name == "a (cropped).png" and second.name == "a (cropped) (1).png"


def test_static_gif_is_saved_as_png(qapp, tmp_path):
    from tests.conftest import make_animated_gif

    src = make_animated_gif(tmp_path / "dot.gif", frames=1)
    doc = document.open_document(src)
    out = doc.save(st.turn_image(doc.initial_state(), "cw"))
    assert out.name == "dot (edited).png"


# -------------------------------------------------------------------- PDFs ---

def _grid_pdf(path, rotate=0, mediabox=None, cropbox=None):
    """A page full of differently colored cells (any misplaced crop shows)."""
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=400, height=600)
    for i, j in itertools.product(range(10), range(10)):
        page.draw_rect(pymupdf.Rect(i * 40, j * 60, i * 40 + 40, j * 60 + 60), color=None,
                       fill=(i / 10, j / 10, ((i * 3 + j * 7) % 10) / 10))
    if mediabox:
        doc.xref_set_key(page.xref, "MediaBox", "[%g %g %g %g]" % mediabox)
    if cropbox:
        page.set_cropbox(pymupdf.Rect(cropbox))
    page.set_rotation(rotate)
    doc.new_page()  # a second page
    doc.save(path)
    doc.close()
    return path


def _render(path, index=0, width=300):
    doc = document.PdfDocument(path)
    try:
        return doc.render_page(index, width)
    finally:
        doc.close()


def _canvas_view(doc, index, change, width=600):
    """What the editor shows: the page, turned by the user's rotation, then
    the crop."""
    from PyQt6.QtGui import QTransform

    img = doc.render_page(index, width)
    if change["rot"]:
        img = img.transformed(QTransform().rotate(change["rot"]))
    if change["crop"]:
        from app.editor import imaging

        img = img.copy(imaging.crop_pixels(img.width(), img.height(), change["crop"]))
    return img


CASES = list(itertools.product((0, 90, 180, 270), (0, 90, 270),
                               (None, (50, 80, 450, 680)), (None, (60, 90, 380, 560))))


@pytest.mark.parametrize("own_rot,user_rot,mediabox,cropbox", CASES)
def test_pdf_crop_and_rotate_look_like_the_canvas(qapp, tmp_path, own_rot, user_rot, mediabox, cropbox):
    from PyQt6.QtCore import Qt

    if mediabox and cropbox:
        cropbox = (cropbox[0] + 50, cropbox[1], cropbox[2] + 50, cropbox[3])  # inside the moved media box
    src = _grid_pdf(tmp_path / "grid.pdf", own_rot, mediabox, cropbox)
    doc = document.PdfDocument(src)
    s = doc.initial_state()
    for _ in range(user_rot // 90):
        s = st.turn_page(s, 0, "cw")
    s = st.set_page(s, 0, crop=[0.313, 0.171, 0.437, 0.613])
    expected = _canvas_view(doc, 0, s["pages"][0])
    out = doc.save(s)
    doc.close()
    got = _render(out, 0, expected.width())
    assert abs(got.width() / got.height() - expected.width() / expected.height()) < 0.02
    got = got.scaled(expected.size(), Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    assert np.abs(_array(got) - _array(expected)).mean() < 6


def test_pdf_delete_and_rotate_pages(qapp, tmp_path):
    import pymupdf

    src = make_pdf(tmp_path / "doc.pdf", pages=3)
    doc = document.PdfDocument(src)
    s = st.set_page(doc.initial_state(), 1, deleted=True)
    s = st.turn_page(s, 2, "ccw")
    out = doc.save(s)
    doc.close()
    assert out.name == "doc (edited).pdf"
    with pymupdf.open(out) as saved:
        assert saved.page_count == 2
        assert "Hello page 1" in saved[0].get_text() and "Hello page 3" in saved[1].get_text()
        assert saved[1].rotation == 270
    with pymupdf.open(src) as original:
        assert original.page_count == 3  # untouched


def test_pdf_cannot_delete_every_page(qapp, tmp_path):
    src = make_pdf(tmp_path / "one.pdf", pages=1)
    doc = document.PdfDocument(src)
    with pytest.raises(document.OpenError, match="every page"):
        doc.save(st.set_page(doc.initial_state(), 0, deleted=True))
    doc.close()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["one.pdf"]


def test_password_pdf_is_refused(tmp_path):
    src = make_pdf(tmp_path / "secret.pdf", pages=1, password="pw")
    with pytest.raises(document.OpenError, match="Password"):
        document.open_document(src)


def test_pdf_page_sizes_include_own_rotation(qapp, tmp_path):
    src = _grid_pdf(tmp_path / "r.pdf", rotate=90)
    doc = document.PdfDocument(src)
    assert doc.page_size(0) == (600.0, 400.0)
    thumb = doc.thumbnail(0)
    assert thumb.height() == document.THUMB_HEIGHT and thumb.width() > thumb.height()
    doc.close()
