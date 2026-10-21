"""Several files -> one PDF (images, PDFs, or a mix), and no metadata
leaking into a PDF made from photos."""

from pathlib import Path

import pytest

from app.handlers import combine
from app.handlers.common import Context, HandlerError
from tests.conftest import add_exif_gps, add_exif_orientation, make_image, make_pdf, make_photo

SECRET = b"GPS-SECRET-12.9716N-77.5946E"


def add_gps(jpeg):
    """A phone photo's worth of private data: EXIF with a GPS block, XMP,
    a comment, and a motion-photo video after the image, all carrying SECRET."""
    from tests.conftest import add_jpeg_segment, append_motion_video

    add_exif_gps(jpeg, SECRET.decode())
    add_jpeg_segment(jpeg, 0xE1, b"http://ns.adobe.com/xap/1.0/\x00<x:xmpmeta>" + SECRET + b"</x:xmpmeta>")
    add_jpeg_segment(jpeg, 0xFE, SECRET)
    append_motion_video(jpeg, SECRET)
    assert jpeg.read_bytes().count(SECRET) == 4


def leaks(pdf_path) -> list[str]:
    """Where SECRET still appears in a PDF: the raw file, or any object or
    stream after decoding."""
    import pymupdf

    found = []
    if SECRET in pdf_path.read_bytes():
        found.append("file")
    with pymupdf.open(pdf_path) as doc:
        for xref in range(1, doc.xref_length()):
            if SECRET.decode() in doc.xref_object(xref):
                found.append(f"object {xref}")
            if doc.xref_is_stream(xref):
                for data in (doc.xref_stream_raw(xref), doc.xref_stream(xref)):
                    if data and SECRET in data:
                        found.append(f"stream {xref}")
    return found


def run(handler, paths):
    ctx = Context(paths[0], {"jpeg_quality": 90})
    try:
        handler(paths, "PDF", ctx)
    except BaseException:
        ctx.discard()
        raise
    return ctx.commit(), ctx.info


def test_images_become_one_pdf_in_drop_order_each_page_its_own_size(qapp, tmp_path):
    import pymupdf

    wide = make_image(tmp_path / "b-wide.png", "PNG", size=(300, 100))
    tall = make_photo(tmp_path / "a-tall.jpg", size=(150, 400))
    square = make_image(tmp_path / "c.bmp", "BMP", size=(96, 96))
    [out], info = run(combine.to_one_pdf, [wide, tall, square])  # not alphabetical: drop order wins
    assert out.name == "b-wide (combined).pdf" and info["note"] == "Combined"
    with pymupdf.open(out) as doc:
        assert doc.page_count == 3
        sizes = [(p.rect.width, p.rect.height) for p in doc]
    want = [(225, 75), (112.5, 300), (72, 72)]  # 96 DPI images: px * 72 / 96
    assert [pytest.approx(s, abs=0.1) for s in want] == sizes  # Qt keeps DPI as dots per meter


def test_jpeg_pages_embed_the_original_image_data(qapp, tmp_path):
    """Lossless: the embedded JPEG is the original minus its metadata,
    with the compressed image data byte for byte the same."""
    import pymupdf

    from app.handlers.metadata import strip_jpeg
    from tests.conftest import jpeg_scan

    photo = make_photo(tmp_path / "p.jpg", size=(200, 120))
    add_gps(photo)
    other = make_photo(tmp_path / "q.jpg", size=(120, 200))
    [out], _ = run(combine.to_one_pdf, [photo, other])
    with pymupdf.open(out) as doc:
        xref = doc[0].get_images()[0][0]
        embedded = doc.extract_image(xref)["image"]
    assert embedded == strip_jpeg(photo.read_bytes())[0]
    assert jpeg_scan(embedded) == jpeg_scan(photo.read_bytes()).split(b"\xff\xd9")[0] + b"\xff\xd9"


def test_rotated_photo_page_is_upright(qapp, tmp_path):
    import pymupdf

    phone = make_photo(tmp_path / "phone.jpg", size=(400, 200))
    add_exif_orientation(phone, 6)
    [out], _ = run(combine.to_one_pdf, [phone, make_image(tmp_path / "x.png", "PNG")])
    with pymupdf.open(out) as doc:
        assert doc[0].rect.height > doc[0].rect.width


def test_one_bad_image_fails_the_whole_pdf_naming_it(qapp, tmp_path):
    from tests.conftest import make_animated_gif

    good = make_image(tmp_path / "a.png", "PNG")
    bad = make_animated_gif(tmp_path / "anim.gif")
    with pytest.raises(HandlerError, match="anim.gif: Animated GIF not supported"):
        run(combine.to_one_pdf, [good, bad])
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.png", "anim.gif"]  # nothing left behind


def test_merge_keeps_order_and_shifts_bookmarks(tmp_path):
    import pymupdf

    a = make_pdf(tmp_path / "zeta.pdf", pages=2)
    b = make_pdf(tmp_path / "alpha.pdf", pages=3)
    with pymupdf.open(b) as doc:
        doc.set_toc([[1, "Chapter B", 2]])
        doc.saveIncr()
    [out], info = run(combine.to_one_pdf, [a, b])
    assert out.name == "zeta (combined).pdf" and info["note"] == "Combined"
    with pymupdf.open(out) as doc:
        assert doc.page_count == 5
        assert "Hello page 1" in doc[0].get_text() and "Hello page 2" in doc[1].get_text()
        assert "Hello page 1" in doc[2].get_text()  # alpha.pdf starts after zeta.pdf's 2 pages
        assert doc.get_toc() == [[1, "Chapter B", 4]]


def test_merge_fails_on_a_locked_pdf_naming_it(tmp_path):
    a = make_pdf(tmp_path / "a.pdf", pages=1)
    locked = make_pdf(tmp_path / "secret.pdf", pages=1, password="pw")
    with pytest.raises(HandlerError, match="secret.pdf: Password-protected PDF"):
        run(combine.to_one_pdf, [a, locked])


def test_combined_request_through_the_helper(tmp_path):
    """One request with every path -> one done with one output."""
    from tests.test_runner import talk

    a, b = make_pdf(tmp_path / "a.pdf", pages=1), make_pdf(tmp_path / "b.pdf", pages=2)
    messages, _err, code = talk([{"type": "run", "id": 1, "spec": "app.handlers.combine:to_one_pdf",
                                  "paths": [str(a), str(b)], "kinds": ["pdf", "pdf"], "option": "Merge", "settings": {}}])
    assert code == 0 and messages[-1]["type"] == "done"
    assert messages[-1]["outputs"] == [str(tmp_path / "a (combined).pdf")]


def test_combined_request_checks_every_file(tmp_path):
    from tests.test_runner import talk

    a = make_pdf(tmp_path / "a.pdf", pages=1)
    fake = tmp_path / "b.pdf"
    fake.write_bytes(b"\x89PNG\r\n\x1a\n")
    messages, _err, _ = talk([{"type": "run", "id": 1, "spec": "app.handlers.combine:to_one_pdf",
                               "paths": [str(a), str(fake)], "kinds": ["pdf", "pdf"], "option": "Merge", "settings": {}}])
    assert messages[-1] == {"type": "error", "id": 1, "message": "b.pdf: Doesn't look like a PDF file"}


def test_worker_reports_a_combined_job_once(qapp, tmp_path):
    from app.jobs import Job, JobItem
    from app.jobs.process import ProcessWorker
    from tests.test_process_worker import Recorder, wait_until

    paths = [make_pdf(tmp_path / f"{n}.pdf", pages=1) for n in ("c", "a", "b")]
    worker = ProcessWorker(idle_ms=5000)
    rec = Recorder(worker)
    spec = "app.handlers.combine:to_one_pdf"
    worker.submit(Job("convert", "Merge", tuple(JobItem(p, "pdf", spec) for p in paths), combine=True))
    wait_until(qapp, lambda: rec.finished)
    worker.shutdown()
    assert rec.finished == [0] and len(rec.done) == 1
    index, error, outs = rec.done[0]
    assert index == 0 and error == "" and [Path(o).name for o in outs] == ["c (combined).pdf"]


# ---- no metadata into PDFs ----

def test_phone_photo_to_pdf_leaks_no_gps(qapp, tmp_path):
    from app.handlers import image

    photo = make_photo(tmp_path / "PXL_1.jpg", size=(320, 240))
    add_gps(photo)
    ctx = Context(photo, {})
    image.convert(photo, "PDF", ctx)
    [out] = ctx.commit()
    assert leaks(out) == []


def test_combined_pdf_of_phone_photos_has_no_gps(qapp, tmp_path):
    """The straight-through path (upright JPEG, embedded as is) and the
    re-encode path (rotated by EXIF) both come out clean."""
    upright = make_photo(tmp_path / "upright.jpg", size=(320, 240))
    add_gps(upright)
    turned = make_photo(tmp_path / "turned.jpg", size=(320, 240))
    add_exif_orientation(turned, 6)
    add_gps(turned)
    png = make_image(tmp_path / "shot.png", "PNG")
    from PyQt6.QtGui import QImage

    img = QImage(str(png))
    img.setText("Location", SECRET.decode())
    img.save(str(png))
    assert SECRET in png.read_bytes()
    [out], _ = run(combine.to_one_pdf, [upright, turned, png])
    assert leaks(out) == []


# ---- multi-page TIFFs and mixed drops ----

def test_combined_takes_every_tiff_page(qapp, tmp_path):
    import pymupdf

    from tests.conftest import make_multipage_tiff

    a = make_image(tmp_path / "a.png", "PNG")
    scan = make_multipage_tiff(tmp_path / "scan.tiff", pages=3)
    [out], _ = run(combine.to_one_pdf, [a, scan])
    with pymupdf.open(out) as doc:
        assert doc.page_count == 4


def test_mixed_images_and_pdfs_in_drop_order(qapp, tmp_path):
    import pymupdf

    photo = make_photo(tmp_path / "cover.jpg", size=(300, 200))
    add_gps(photo)
    report = make_pdf(tmp_path / "report.pdf", pages=2)
    with pymupdf.open(report) as doc:
        doc.set_toc([[1, "Second page", 2]])
        doc.saveIncr()
    back = make_image(tmp_path / "back.png", "PNG", size=(96, 96))
    [out], info = run(combine.to_one_pdf, [photo, report, back])
    assert out.name == "cover (combined).pdf" and info["note"] == "Combined"
    with pymupdf.open(out) as doc:
        assert doc.page_count == 4
        assert doc[0].get_images() and not doc[0].get_text().strip()      # the photo
        assert "Hello page 1" in doc[1].get_text()                          # report.pdf
        assert "Hello page 2" in doc[2].get_text()
        assert doc[3].rect.width == pytest.approx(72, abs=0.1)               # back.png
        assert doc.get_toc() == [[1, "Second page", 3]]                      # shifted by the photo page
    assert leaks(out) == []
