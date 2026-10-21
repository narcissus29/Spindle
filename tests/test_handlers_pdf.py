import zipfile
from pathlib import Path

import pytest

from app.handlers import pdf
from app.handlers.common import Context, HandlerError
from tests.conftest import make_pdf


TEXTS: list[str] = []  # the progress texts of the last run


def run(handler, src: Path, option: str, **settings):
    progress = []
    TEXTS.clear()

    def report(fraction, text=""):
        progress.append(fraction)
        TEXTS.append(text)

    ctx = Context(src, settings, on_progress=report)
    handler(src, option, ctx)
    return ctx.commit(), progress


def test_txt_has_every_page_in_order(tmp_path):
    src = make_pdf(tmp_path / "report.pdf", pages=3)
    [out], progress = run(pdf.to_txt, src, "TXT")
    assert out == tmp_path / "report.txt"
    text = out.read_text(encoding="utf-8")
    assert text.index("Hello page 1") < text.index("Hello page 2") < text.index("Hello page 3")
    assert progress[-1] == 1.0


def test_single_page_png_next_to_source(tmp_path):
    from PyQt6.QtGui import QImageReader

    src = make_pdf(tmp_path / "one.pdf", pages=1)
    [out], _ = run(pdf.to_images, src, "PNG", pdf_image_dpi=72)
    assert out == tmp_path / "one.png"
    reader = QImageReader(str(out))
    assert bytes(reader.format()) == b"png"
    assert (reader.size().width(), reader.size().height()) == (595, 842)  # A4 at 72 DPI


def test_multi_page_jpg_goes_in_a_folder(tmp_path):
    src = make_pdf(tmp_path / "report.pdf", pages=3)
    [folder], progress = run(pdf.to_images, src, "JPG", pdf_image_dpi=50, jpeg_quality=80)
    assert folder == tmp_path / "report (JPG)" and folder.is_dir()
    assert sorted(p.name for p in folder.iterdir()) == ["page-001.jpg", "page-002.jpg", "page-003.jpg"]
    assert (folder / "page-001.jpg").read_bytes()[:3] == b"\xff\xd8\xff"
    assert len(progress) >= 1 and progress[-1] == 1.0


def test_existing_output_gets_a_new_name(tmp_path):
    src = make_pdf(tmp_path / "one.pdf", pages=1)
    run(pdf.to_images, src, "PNG", pdf_image_dpi=36)
    [second], _ = run(pdf.to_images, src, "PNG", pdf_image_dpi=36)
    assert second.name == "one (1).png"


def test_docx(tmp_path):
    src = make_pdf(tmp_path / "report.pdf", pages=2)
    [out], progress = run(pdf.to_docx, src, "DOCX")
    assert out == tmp_path / "report.docx"
    with zipfile.ZipFile(out) as z:
        xml = z.read("word/document.xml").decode()
    assert "Hello page 1" in xml and "Hello page 2" in xml
    assert progress[-1] == 1.0 and progress[0] is None  # "Analyzing…" before pages can be counted
    assert TEXTS[0] == "Analyzing…" and any(t.startswith("Page ") for t in TEXTS)


def test_password_protected_pdf_fails_cleanly(tmp_path):
    src = make_pdf(tmp_path / "secret.pdf", pages=1, password="pw")
    with pytest.raises(HandlerError, match="Password-protected PDF"):
        run(pdf.to_txt, src, "TXT")


def test_damaged_pdf_fails_cleanly(tmp_path):
    src = tmp_path / "broken.pdf"
    src.write_bytes(b"%PDF-1.7\nthis is not really a pdf")
    with pytest.raises(HandlerError, match="Can't open PDF|has no pages"):
        run(pdf.to_txt, src, "TXT")


def test_thumbnail_is_small_and_cached(tmp_path):
    from PyQt6.QtGui import QImageReader

    src = make_pdf(tmp_path / "report.pdf", pages=2)
    cache = tmp_path / "thumbs"
    thumb = pdf.render_thumbnail(src, 128, cache)
    size = QImageReader(str(thumb)).size()
    assert max(size.width(), size.height()) == 128
    mtime = thumb.stat().st_mtime_ns
    assert pdf.render_thumbnail(src, 128, cache) == thumb and thumb.stat().st_mtime_ns == mtime
