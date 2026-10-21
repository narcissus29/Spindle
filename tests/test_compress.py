import pytest

from app.handlers import compress
from app.handlers.common import Context, Skip
from tests.conftest import add_exif_orientation, make_image, make_pdf, make_photo, make_photo_pdf


def run(src, preset="balanced"):
    ctx = Context(src, {"compress_preset": preset})
    try:
        compress.compress(src, "Compress", ctx)
    except BaseException:
        ctx.discard()  # what the runner does on Skip / errors
        raise
    return ctx.commit(), ctx.info


def test_pdf_with_big_photo_gets_much_smaller(qapp, tmp_path):
    src = make_photo_pdf(tmp_path / "report.pdf", make_photo(tmp_path / "p.jpg"))
    [out], info = run(src)
    assert out.name == "report (compressed).pdf"
    assert info["after"] < info["before"] * 0.5 and info["note"].startswith("−")
    import pymupdf
    with pymupdf.open(out) as doc:
        assert "Photo report" in doc[0].get_text()  # content intact


def test_light_preset_leaves_photos_alone(qapp, tmp_path):
    src = make_photo_pdf(tmp_path / "report.pdf", make_photo(tmp_path / "p.jpg"))
    with pytest.raises(Skip, match="Already compact"):
        run(src, "light")


def test_compressing_a_compressed_pdf_again_is_skipped(qapp, tmp_path):
    src = make_photo_pdf(tmp_path / "report.pdf", make_photo(tmp_path / "p.jpg"))
    [once], _ = run(src)
    with pytest.raises(Skip, match="Already compact"):
        run(once)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["p.jpg", "report (compressed).pdf", "report.pdf"]


def test_jpeg_reencoded_smaller_and_upright(qapp, tmp_path):
    from PyQt6.QtGui import QImageReader

    src = make_photo(tmp_path / "phone.jpg", size=(800, 400), quality=97)
    add_exif_orientation(src, 6)
    [out], info = run(src)
    assert out.name == "phone (compressed).jpg" and info["after"] < info["before"]
    size = QImageReader(str(out)).size()
    assert (size.width(), size.height()) == (400, 800)  # rotation baked in


def test_jpeg_with_light_preset_is_skipped(qapp, tmp_path):
    with pytest.raises(Skip, match="Already compact"):
        run(make_photo(tmp_path / "a.jpg", size=(300, 200)), "light")


def test_opaque_rgba_png_loses_its_alpha_channel_not_its_pixels(qapp, tmp_path):
    from PyQt6.QtGui import QImage

    src = tmp_path / "shot.png"
    img = QImage(400, 300, QImage.Format.Format_ARGB32)
    img.fill(0xFF3A7BD5)
    for x in range(0, 400, 7):
        img.setPixel(x, x % 300, 0xFFFFFFFF)
    img.save(str(src), b"PNG", 100)  # quality 100 = no zlib compression
    [out], info = run(src, "light")
    out_img = QImage(str(out))
    assert not out_img.hasAlphaChannel()
    assert out_img.convertToFormat(QImage.Format.Format_RGB32) == img.convertToFormat(QImage.Format.Format_RGB32)


def test_bmp_becomes_png(qapp, tmp_path):
    src = make_image(tmp_path / "old.bmp", "BMP", size=(300, 200))
    [out], _ = run(src)
    assert out.name == "old (compressed).png"


def test_strong_preset_caps_size(qapp, tmp_path):
    from PyQt6.QtGui import QImageReader

    src = make_photo(tmp_path / "huge.jpg", size=(4000, 1000))
    [out], _ = run(src, "strong")
    assert QImageReader(str(out)).size().width() == 2560
