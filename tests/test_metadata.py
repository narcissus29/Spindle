import struct

import pytest

from app.handlers import metadata
from app.handlers.common import Context, Skip
from tests.conftest import (add_exif_orientation, add_jpeg_segment, jpeg_scan, jpeg_segments,
                            make_image, make_pdf, make_photo)


def run(src):
    ctx = Context(src, {})
    metadata.strip(src, "Metadata", ctx)
    return ctx.commit(), ctx.info


def test_jpeg_exif_xmp_comment_removed_pixels_untouched(qapp, tmp_path):
    from PyQt6.QtGui import QImageReader

    src = make_photo(tmp_path / "trip.jpg", size=(320, 160))
    add_jpeg_segment(src, 0xFE, b"shot by Ravi at home")
    add_jpeg_segment(src, 0xE1, b"http://ns.adobe.com/xap/1.0/\x00<x:xmpmeta>GPS 12.97N</x:xmpmeta>")
    add_exif_orientation(src, 6)  # EXIF block, with orientation
    [out], info = run(src)
    assert out.name == "trip (clean).jpg" and info["note"] == "Cleaned"
    data = out.read_bytes()
    assert b"Ravi" not in data and b"xmpmeta" not in data
    assert jpeg_scan(data) == jpeg_scan(src.read_bytes())  # image data byte-identical
    exif = [p for m, p in jpeg_segments(data) if m == 0xE1]
    assert len(exif) == 1 and len(exif[0]) < 40  # only the orientation was put back
    reader = QImageReader(str(out))
    reader.setAutoTransform(True)
    shown = reader.read()
    assert (shown.width(), shown.height()) == (160, 320)  # still displays upright


def test_icc_profile_is_kept(qapp, tmp_path):
    src = make_photo(tmp_path / "a.jpg", size=(64, 64))
    add_jpeg_segment(src, 0xE2, b"ICC_PROFILE\x00\x01\x01fake-profile")
    add_jpeg_segment(src, 0xFE, b"comment")
    [out], _ = run(src)
    assert any(m == 0xE2 and p.startswith(b"ICC_PROFILE") for m, p in jpeg_segments(out.read_bytes()))


def test_clean_jpeg_is_skipped(qapp, tmp_path):
    with pytest.raises(Skip, match="No metadata"):
        run(make_photo(tmp_path / "clean.jpg", size=(64, 64)))


def test_png_text_chunks_removed(qapp, tmp_path):
    from PyQt6.QtGui import QImage

    src = make_image(tmp_path / "logo.png", "PNG", alpha=True)
    img = QImage(str(src))
    img.setText("Author", "Ravi")
    img.setText("Location", "Home")
    img.save(str(src))
    assert b"tEXt" in src.read_bytes()
    [out], _ = run(src)
    data = out.read_bytes()
    assert b"tEXt" not in data and b"Ravi" not in data
    assert QImage(str(out)) == QImage(str(src))  # same pixels (incl. transparency)


def _webp_with_exif(plain: bytes) -> bytes:
    width, height = 64, 48
    vp8x = b"VP8X" + struct.pack("<I", 10) + bytes([0x08, 0, 0, 0]) + (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little")
    exif_payload = b"II*\x00\x08\x00\x00\x00\x00\x00\x00\x00\x00\x00GPS-secret"
    exif = b"EXIF" + struct.pack("<I", len(exif_payload)) + exif_payload + (b"\x00" if len(exif_payload) & 1 else b"")
    body = vp8x + plain[12:] + exif
    return b"RIFF" + struct.pack("<I", len(body) + 4) + b"WEBP" + body


def test_webp_exif_removed(qapp, tmp_path):
    from PyQt6.QtGui import QImageReader

    plain = make_image(tmp_path / "p.webp", "WEBP").read_bytes()
    src = tmp_path / "pic.webp"
    src.write_bytes(_webp_with_exif(plain))
    [out], _ = run(src)
    data = out.read_bytes()
    assert b"GPS-secret" not in data and b"EXIF" not in data
    assert data[20] & 0x08 == 0  # EXIF flag cleared in VP8X
    assert QImageReader(str(out)).size().width() == 64


def test_pdf_info_removed_content_kept(tmp_path):
    import pymupdf

    src = make_pdf(tmp_path / "cv.pdf", pages=1)
    with pymupdf.open(src) as doc:
        doc.set_metadata({"author": "Ravi", "title": "CV", "creator": "Word"})
        doc.saveIncr()
    [out], info = run(src)
    assert out.name == "cv (clean).pdf" and "document info" in info["detail"]
    with pymupdf.open(out) as doc:
        assert not doc.metadata["author"] and not doc.metadata["title"] and not doc.metadata["creator"]
        assert "Hello page 1" in doc[0].get_text()


def test_pdf_without_metadata_is_skipped(tmp_path):
    import pymupdf

    src = make_pdf(tmp_path / "bare.pdf", pages=1)
    with pymupdf.open(src) as doc:
        doc.set_metadata({})
        doc.save(tmp_path / "bare2.pdf")
    with pytest.raises(Skip, match="No metadata"):
        run(tmp_path / "bare2.pdf")


def test_bmp_has_nothing_to_remove(qapp, tmp_path):
    with pytest.raises(Skip, match="No metadata"):
        run(make_image(tmp_path / "x.bmp", "BMP"))


# ---- data after the end of the image ----

def test_motion_photo_video_is_removed(qapp, tmp_path):
    from PyQt6.QtGui import QImage

    from tests.conftest import append_motion_video

    src = make_photo(tmp_path / "PXL_motion.jpg", size=(320, 240))
    add_exif_orientation(src, 1)
    append_motion_video(src)
    [out], info = run(src)
    data = out.read_bytes()
    assert b"GPS 12.97" not in data and b"ftyp" not in data
    assert data.endswith(b"\xff\xd9")  # a plain still photo now
    assert info["note"] == "Cleaned"
    assert info["detail"] == "Motion photo data removed; also EXIF"
    assert QImage(str(out)) == QImage(str(src))  # same picture


def test_motion_photo_without_other_metadata_is_not_skipped(qapp, tmp_path):
    from tests.conftest import append_motion_video

    src = make_photo(tmp_path / "motion.jpg", size=(64, 64))
    append_motion_video(src)
    [out], info = run(src)
    assert info["detail"] == "Motion photo data removed"
    assert b"GPS" not in out.read_bytes()


def test_unknown_trailing_data_is_removed(qapp, tmp_path):
    src = make_photo(tmp_path / "a.jpg", size=(64, 64))
    src.write_bytes(src.read_bytes() + b"appended by some tool: owner=Ravi")
    [out], info = run(src)
    assert b"Ravi" not in out.read_bytes()
    assert info["detail"] == "Hidden data after the image removed"


def test_zero_padding_alone_is_not_metadata(qapp, tmp_path):
    src = make_photo(tmp_path / "padded.jpg", size=(64, 64))
    src.write_bytes(src.read_bytes() + b"\x00" * 512)
    with pytest.raises(Skip, match="No metadata"):
        run(src)


def test_progressive_jpeg_scans_survive(qapp, tmp_path):
    """Progressive JPEGs have many scans with tables in between: all of
    them must be kept, only the data after the end marker goes."""
    from PyQt6.QtGui import QImage, QImageWriter

    from tests.conftest import append_motion_video

    img = QImage(str(make_photo(tmp_path / "base.jpg", size=(400, 300))))
    src = tmp_path / "prog.jpg"
    writer = QImageWriter(str(src), b"jpeg")
    writer.setProgressiveScanWrite(True)
    assert writer.write(img)
    original = src.read_bytes()
    assert original.count(b"\xff\xda") > 1  # really several scans
    add_jpeg_segment(src, 0xFE, b"comment")
    append_motion_video(src)
    [out], _ = run(src)
    assert out.read_bytes() == original  # exactly the untouched image back


def test_png_data_after_iend_is_removed(qapp, tmp_path):
    src = make_image(tmp_path / "logo.png", "PNG")
    src.write_bytes(src.read_bytes() + b"secret zip appended")
    [out], info = run(src)
    assert out.read_bytes().endswith(b"IEND\xaeB`\x82")
    assert info["detail"] == "Hidden data after the image removed"


def test_webp_data_after_riff_is_removed(qapp, tmp_path):
    plain = make_image(tmp_path / "p.webp", "WEBP").read_bytes()
    src = tmp_path / "pic.webp"
    src.write_bytes(plain + b"EXIF\x10\x00\x00\x00GPS-secret-here!")  # looks like a chunk, but outside RIFF
    [out], info = run(src)
    assert out.read_bytes() == plain
    assert info["detail"] == "Hidden data after the image removed"


def test_pdf_earlier_versions_are_dropped(tmp_path):
    """Metadata removed with an incremental save still sits in the file."""
    import pymupdf

    src = make_pdf(tmp_path / "cv.pdf", pages=1)
    with pymupdf.open(src) as doc:
        doc.set_metadata({"author": "Ravi Secret"})
        doc.save(tmp_path / "v1.pdf")
    with pymupdf.open(tmp_path / "v1.pdf") as doc:
        doc.set_metadata({"author": "", "producer": "", "creator": ""})  # ({} would be a no-op)
        doc.saveIncr()
    with pymupdf.open(tmp_path / "v1.pdf") as doc:  # looks clean now...
        assert not any(v for k, v in doc.metadata.items() if k != "format")
    assert b"Ravi Secret" in (tmp_path / "v1.pdf").read_bytes()
    [out], info = run(tmp_path / "v1.pdf")
    assert b"Ravi Secret" not in out.read_bytes()
    assert "earlier versions" in info["detail"]


def test_pdf_data_after_eof_is_removed(tmp_path):
    src = make_pdf(tmp_path / "plain.pdf", pages=1)
    import pymupdf

    with pymupdf.open(src) as doc:
        doc.set_metadata({})
        doc.save(tmp_path / "bare.pdf")
    bare = tmp_path / "bare.pdf"
    bare.write_bytes(bare.read_bytes() + b"\nappended: owner=Ravi\n")
    [out], info = run(bare)
    assert b"Ravi" not in out.read_bytes()
    assert info["detail"] == "Hidden data after the image removed"
