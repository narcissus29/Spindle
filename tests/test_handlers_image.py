from pathlib import Path

import pytest

from app.handlers import image
from app.handlers.common import Context, HandlerError
from tests.conftest import add_exif_orientation, make_image


def run(src: Path, option: str, **settings):
    ctx = Context(src, settings)
    image.convert(src, option, ctx)
    return ctx.commit()


@pytest.mark.parametrize("option,fmt,ext", [
    ("PNG", b"png", ".png"), ("JPG", b"jpeg", ".jpg"), ("WEBP", b"webp", ".webp"),
    ("BMP", b"bmp", ".bmp"), ("TIFF", b"tiff", ".tiff"),
])
def test_every_target_format(qapp, tmp_path, option, fmt, ext):
    from PyQt6.QtGui import QImageReader

    src = make_image(tmp_path / ("in.png" if option != "PNG" else "in.jpg"), "PNG" if option != "PNG" else "JPG")
    [out] = run(src, option)
    assert out.suffix == ext
    reader = QImageReader(str(out))
    assert bytes(reader.format()) == fmt
    assert (reader.size().width(), reader.size().height()) == (64, 48)


def test_transparency_becomes_white_in_jpg(qapp, tmp_path):
    from PyQt6.QtGui import QImage

    src = make_image(tmp_path / "logo.png", "PNG", alpha=True)
    [out] = run(src, "JPG")
    img = QImage(str(out))
    corner = img.pixelColor(1, 1)
    assert min(corner.red(), corner.green(), corner.blue()) > 240


def test_exif_orientation_is_applied(qapp, tmp_path):
    from PyQt6.QtGui import QImageReader

    src = make_image(tmp_path / "phone.jpg", "JPG", size=(80, 40))
    add_exif_orientation(src, 6)  # "rotate 90° clockwise to display"
    [out] = run(src, "PNG")
    size = QImageReader(str(out)).size()
    assert (size.width(), size.height()) == (40, 80)


@pytest.mark.parametrize("src_name,fmt", [("photo.jpg", "JPG"), ("pic.webp", "WEBP"), ("scan.tiff", "TIFF")])
def test_image_to_pdf(qapp, tmp_path, src_name, fmt):
    import pymupdf

    src = make_image(tmp_path / src_name, fmt, size=(96, 48))
    [out] = run(src, "PDF")
    with pymupdf.open(out) as doc:
        assert doc.page_count == 1
        rect = doc[0].rect
        assert abs(rect.width / rect.height - 2.0) < 0.01  # keeps the aspect ratio
        assert doc[0].get_images()  # the image is really embedded


def test_unreadable_image_fails_cleanly(qapp, tmp_path):
    src = tmp_path / "fake.png"
    src.write_bytes(b"\x89PNG\r\n\x1a\nbroken")
    with pytest.raises(HandlerError, match="Can't read image"):
        run(src, "JPG")
