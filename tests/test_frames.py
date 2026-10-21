"""Pages and frames are never dropped silently: multi-page TIFFs and
animated images are refused (no output) by every handler that would only
keep the first frame."""

import pytest

from app.handlers import background, compress, image, metadata
from app.handlers.common import Context, Skip
from tests.conftest import make_animated_gif, make_animated_webp, make_apng, make_image, make_multipage_tiff

HANDLERS = {
    "Metadata": metadata.strip,
    "Compress": compress.compress,
    "Add BG": background.add_bg,
    "PNG": image.convert,
    "PDF": image.convert,
}

FILES = {
    "scan.tiff": (make_multipage_tiff, "Multi-page TIFF not supported"),
    "anim.gif": (make_animated_gif, "Animated GIF not supported"),
    "anim.webp": (make_animated_webp, "Animated WEBP not supported"),
    "anim.png": (make_apng, "Animated PNG not supported"),
}


def run(handler_name, src):
    ctx = Context(src, {"compress_preset": "strong"})
    try:
        HANDLERS[handler_name](src, handler_name, ctx)
    except BaseException:
        ctx.discard()
        raise
    return ctx.commit()


def test_fixtures_really_have_several_frames(qapp, tmp_path):
    from PyQt6.QtGui import QImageReader

    for name, (make, _msg) in FILES.items():
        src = make(tmp_path / name)
        if name != "anim.png":  # Qt doesn't know APNG; detected by its acTL chunk
            assert QImageReader(str(src)).imageCount() == 2, name


# Metadata on GIF / WEBP / PNG works on the bytes and keeps every frame;
# a PNG has no "PNG" convert wedge; a multi-page TIFF -> PDF keeps every
# page (test_tiff_pages_all_go_into_the_pdf) and -> PNG says to use PDF.
NOT_DECODED = {("Metadata", "anim.gif"), ("Metadata", "anim.webp"), ("Metadata", "anim.png"), ("PNG", "anim.png"),
               ("PDF", "scan.tiff"), ("PNG", "scan.tiff")}
CASES = [(h, n) for h in HANDLERS for n in FILES if (h, n) not in NOT_DECODED]


@pytest.mark.parametrize("handler,name", CASES)
def test_multi_frame_images_are_refused(qapp, tmp_path, handler, name):
    make, message = FILES[name]
    src = make(tmp_path / name)
    with pytest.raises(Skip, match=message):
        run(handler, src)
    assert sorted(p.name for p in tmp_path.iterdir()) == [name]  # no output, no temp left


def test_metadata_keeps_every_webp_frame(qapp, tmp_path):
    """Byte-level stripping never decodes, so animations survive it intact."""
    import struct

    from PyQt6.QtGui import QImageReader

    src = make_animated_webp(tmp_path / "anim.webp")
    data = src.read_bytes()
    exif = b"EXIF" + struct.pack("<I", 10) + b"GPS-secret"
    body = data[12:] + exif
    src.write_bytes(b"RIFF" + struct.pack("<I", len(body) + 4) + b"WEBP" + body)
    [out] = run("Metadata", src)
    assert b"GPS-secret" not in out.read_bytes()
    assert QImageReader(str(out)).imageCount() == 2


def test_single_page_tiff_still_works(qapp, tmp_path):
    src = make_multipage_tiff(tmp_path / "one.tiff", pages=1)
    [out] = run("PNG", src)
    assert out.name == "one.png"


def test_static_png_is_not_mistaken_for_apng(qapp, tmp_path):
    src = make_image(tmp_path / "logo.png", "PNG", alpha=True)
    [out] = run("Add BG", src)
    assert out.name == "logo (bg).png"


def test_tiff_to_another_image_format_points_to_pdf(qapp, tmp_path):
    src = make_multipage_tiff(tmp_path / "scan.tiff")
    with pytest.raises(Skip, match="Multi-page TIFF: convert to PDF to keep every page"):
        run("PNG", src)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["scan.tiff"]


def test_tiff_pages_all_go_into_the_pdf(qapp, tmp_path):
    import pymupdf

    src = make_multipage_tiff(tmp_path / "scan.tiff", pages=3, size=(40, 30))
    [out] = run("PDF", src)
    assert out.name == "scan.pdf"
    with pymupdf.open(out) as doc:
        assert doc.page_count == 3
        # each page shows its own TIFF page (gray levels 40, 100, 160)
        levels = [doc[i].get_pixmap().pixel(5, 5)[0] for i in range(3)]
    assert levels == sorted(levels) and len(set(levels)) == 3
