"""Compress to a target size (handlers/target.py, compress.to_target)."""

import pytest

from app.handlers import compress, target as tg
from app.handlers.common import Context, HandlerError, Skip
from tests.conftest import make_image, make_pdf, make_photo, make_photo_pdf

TARGETS = ["20 KB", "50 KB", "100 KB", "200 KB", "500 KB", "1 MB"]


def run(src, option):
    ctx = Context(src, {})
    compress.to_target(src, option, ctx)
    [out] = ctx.commit()
    return out, ctx.info


def test_sizes_parse_and_print():
    assert tg.parse_target("50 KB") == 50_000 and tg.parse_target("75") == 75_000
    assert tg.parse_target("1 MB") == 1_000_000 and tg.parse_target("1,5mb") == 1_500_000
    assert tg.parse_target("0.5") is None and tg.parse_target("abc") is None and tg.parse_target("200 MB") is None
    assert tg.size_label(50_000) == "50 KB" and tg.size_label(1_000_000) == "1 MB" and tg.size_label(1_500_000) == "1.5 MB"
    assert tg.result_label(49_999) == "49 KB" and tg.result_label(340_001, up=True) == "341 KB"
    assert tg.result_label(2_600) == "2.6 KB"


@pytest.mark.parametrize("option", TARGETS)
def test_photo_lands_under_and_close_to_the_target(qapp, tmp_path, option):
    src = make_photo(tmp_path / "photo.jpg", size=(3000, 2250))
    size = tg.parse_target(option)
    if src.stat().st_size <= size:
        pytest.skip("photo already smaller")
    out, info = run(src, option)
    n = out.stat().st_size
    assert out.name == f"photo ({option}).jpg"
    assert n <= size and n >= 0.85 * size, (n, size)
    assert info["fits"] and info["note"] == f"{tg.result_label(n)} ✓"


def test_png_becomes_jpg_and_says_so(qapp, tmp_path):
    from PyQt6.QtGui import QImageReader

    src = make_photo(tmp_path / "scan.png", size=(1600, 1200), fmt="PNG")
    out, info = run(src, "100 KB")
    assert out.name == "scan (100 KB).jpg" and QImageReader(str(out)).format() == b"jpeg"
    assert "saved as JPG" in info["detail"] and out.stat().st_size <= 100_000


def test_transparent_png_gets_white_behind(qapp, tmp_path):
    from PyQt6.QtGui import QImage

    src = make_image(tmp_path / "logo.png", "PNG", size=(1600, 1200), alpha=True)
    src.write_bytes(src.read_bytes() + b"\0" * 0)
    # make it big enough to need work: noisy opaque middle
    img = QImage(str(src))
    from PyQt6.QtGui import QColor
    import random

    rnd = random.Random(1)
    for _ in range(20000):
        img.setPixelColor(rnd.randrange(400, 1200), rnd.randrange(300, 900), QColor(rnd.randrange(256), 0, 0))
    img.save(str(src))
    out, info = run(src, "20 KB")
    shown = QImage(str(out))
    assert "transparent areas made white" in info["detail"]
    corner = shown.pixelColor(2, 2)
    assert corner.red() > 240 and corner.green() > 240 and corner.blue() > 240


def test_webp_stays_webp(qapp, tmp_path):
    src = make_photo(tmp_path / "w.webp", size=(1600, 1200), fmt="WEBP")
    out, info = run(src, "50 KB")
    assert out.suffix == ".webp" and out.stat().st_size <= 50_000 and info["fits"]


def test_impossible_image_target_is_never_a_success(qapp, tmp_path):
    src = make_photo(tmp_path / "p.jpg", size=(800, 600))
    out, info = run(src, "1 KB")
    n = out.stat().st_size
    if info["fits"]:
        assert n <= 1000  # really fits (tiny picture)
    else:
        assert info["note"] == f"Smallest: {tg.result_label(n, up=True)}"


def test_already_under_the_target_writes_nothing(qapp, tmp_path):
    src = make_photo(tmp_path / "small.jpg", size=(64, 48))
    with pytest.raises(Skip) as skip:
        run(src, "50 KB")
    assert str(skip.value).startswith("Already") and skip.value.info["fits"]


def test_bad_option_fails_clearly(qapp, tmp_path):
    with pytest.raises(HandlerError):
        run(make_photo(tmp_path / "p.jpg", size=(64, 48)), "lots")


# ------------------------------------------------------------------- PDFs ---

def _scan_pdf(path, tmp_path, pages=2):
    """Pages that are only pictures: no text layer."""
    import pymupdf

    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_image(page.rect, filename=str(make_photo(tmp_path / f"s{i}.png", size=(1240, 1754), fmt="PNG")))
    doc.save(path)
    doc.close()
    return path


def test_text_layer_detection(qapp, tmp_path):
    import pymupdf

    with pymupdf.open(make_pdf(tmp_path / "t.pdf", pages=2)) as doc:
        assert tg.has_text_layer(doc)
    with pymupdf.open(_scan_pdf(tmp_path / "s.pdf", tmp_path)) as doc:
        assert not tg.has_text_layer(doc)
    # an OCR'd scan (invisible text over the picture) counts as text
    ocr = tmp_path / "ocr.pdf"
    with pymupdf.open(tmp_path / "s.pdf") as doc:
        doc[0].insert_text((72, 72), "Invoice 42", render_mode=3)
        doc.save(ocr)
    with pymupdf.open(ocr) as doc:
        assert tg.has_text_layer(doc)


def test_photo_pdf_reaches_the_target(qapp, tmp_path):
    src = make_photo_pdf(tmp_path / "report.pdf", make_photo(tmp_path / "ph.jpg", size=(3000, 2200)))
    out, info = run(src, "100 KB")
    assert info["fits"] and out.stat().st_size <= 100_000 and out.name == "report (100 KB).pdf"


def test_pdf_with_text_is_never_rasterized(qapp, tmp_path):
    import pymupdf

    src = make_pdf(tmp_path / "letter.pdf", pages=30)
    out, info = run(src, "2 KB")
    assert not info["fits"] and info["note"].startswith("Smallest:")
    with pymupdf.open(out) as doc:
        assert "Hello page 1" in doc[0].get_text() and not doc[0].get_images()


def test_scanned_pdf_can_be_rasterized_to_fit(qapp, tmp_path):
    import pymupdf

    src = _scan_pdf(tmp_path / "scan.pdf", tmp_path, pages=3)
    out, info = run(src, "40 KB")
    assert info["fits"] and out.stat().st_size <= 40_000
    with pymupdf.open(out) as doc, pymupdf.open(src) as orig:
        assert len(doc) == 3 and doc[0].rect == orig[0].rect  # same pages, same size
    assert "pages saved as pictures" in info["detail"]


def test_scan_rasterizing_is_only_a_last_resort(qapp, tmp_path):
    src = _scan_pdf(tmp_path / "scan.pdf", tmp_path, pages=1)
    result = tg.fit_pdf(src, 10_000_000)
    assert result["fits"] and not result["raster"] and result["step"] == 0  # lossless was enough


# ----------------------------------------------------------------- wheel ---

def test_wheel_sub_ring_and_results(qapp, tmp_path):
    from PyQt6.QtCore import QUrl

    from app import handlers
    from app.bridge import Bridge
    from app.config import Config

    b = Bridge(Config())
    jobs = []
    b.jobRequested.connect(jobs.append)
    photo = make_photo(tmp_path / "a.jpg", size=(64, 48))
    b.open()
    assert b.dragEnter([QUrl.fromLocalFile(str(photo))])
    assert b.park()
    names = [o["name"] for o in b.options]
    b.activate(names.index("Compress"))
    assert [o["name"] for o in b.options] == list(handlers.COMPRESS_TARGETS) and not jobs
    b.leaveSubRing()
    assert "Compress" in [o["name"] for o in b.options]
    b.activate(names.index("Compress"))
    b.activate(handlers.COMPRESS_TARGETS.index("Custom"))
    assert b.customEntry and not jobs
    assert b.runCustom("lots") != "" and b.customEntry
    assert b.runCustom("75") == ""
    [job] = jobs
    assert job.option == "75 KB" and job.items[0].spec == "app.handlers.compress:to_target"
    # results: a miss is shown as a warning, never a tick
    b.file_done(job, 0, "", [], {"note": "Smallest: 340 KB", "target": 75_000, "fits": False})
    assert b.statusText == "Smallest: 340 KB" and b.statusWarn
