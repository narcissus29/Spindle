import pytest

from app.handlers import background
from app.handlers.common import Context, Skip
from tests.conftest import make_image, make_photo


def run(src, color="#ff0000"):
    ctx = Context(src, {"background_color": color})
    background.add_bg(src, "Add BG", ctx)
    return ctx.commit()


def test_transparent_png_gets_the_color(qapp, tmp_path):
    from PyQt6.QtGui import QColor, QImage

    src = make_image(tmp_path / "logo.png", "PNG", alpha=True)
    [out] = run(src)
    assert out.name == "logo (bg).png"
    img = QImage(str(out))
    assert not img.hasAlphaChannel()
    assert img.pixelColor(1, 1) == QColor("#ff0000")            # was transparent
    assert img.pixelColor(32, 24) == QColor("#e94e1b")          # opaque part unchanged


def test_webp_stays_webp(qapp, tmp_path):
    src = make_image(tmp_path / "s.webp", "WEBP", alpha=True)
    [out] = run(src, "#ffffff")
    assert out.suffix == ".webp" and out.read_bytes()[8:12] == b"WEBP"


@pytest.mark.parametrize("name,fmt", [("photo.jpg", "JPG"), ("scan.bmp", "BMP")])
def test_formats_without_alpha_are_refused(qapp, tmp_path, name, fmt):
    src = make_image(tmp_path / name, fmt)
    with pytest.raises(Skip, match="No transparency"):
        run(src)
    assert sorted(p.name for p in tmp_path.iterdir()) == [name]


def test_alpha_channel_that_is_fully_opaque_is_refused(qapp, tmp_path):
    from PyQt6.QtGui import QImage

    img = QImage(50, 50, QImage.Format.Format_ARGB32)
    img.fill(0xFF00FF00)
    src = tmp_path / "opaque.png"
    img.save(str(src))
    with pytest.raises(Skip, match="No transparency"):
        run(src)
