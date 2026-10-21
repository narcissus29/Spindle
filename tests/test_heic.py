"""HEIC / HEIF (iPhone photos): read with pi-heif, never written. Anything
made from one is a JPG (or the Convert target)."""

import pytest

from app import filetypes, handlers, heic
from app.handlers import compress, image, metadata
from app.handlers.common import Context, Skip
from tests.conftest import make_heic

GREEN, RED = (30, 190, 60), (220, 40, 40)


def near(color, rgb, tol=25):
    return all(abs(a - b) <= tol for a, b in zip((color.red(), color.green(), color.blue()), rgb))


def run(fn, src, option):
    ctx = Context(src, {})
    fn(src, option, ctx)
    return ctx.commit(), ctx.info


def test_detected_by_name_and_by_content(qapp, tmp_path):
    src = make_heic(tmp_path / "IMG_0001.HEIC")
    assert filetypes.kind_from_path(src) == filetypes.IMAGE and filetypes.format_label(src) == "HEIC"
    assert filetypes.sniff_kind(src) == filetypes.IMAGE
    renamed = tmp_path / "photo.bin"
    renamed.write_bytes(src.read_bytes())
    assert filetypes.sniff_kind(renamed) == filetypes.IMAGE
    avif = b"\x00\x00\x00\x1cftypavif\x00\x00\x00\x00avifmif1miaf"
    assert not heic.is_heic(avif)  # same container, not HEVC: not ours


def test_read_upright_with_its_color_profile(qapp, tmp_path):
    from PyQt6.QtGui import QColorSpace

    p3 = bytes(QColorSpace(QColorSpace.NamedColorSpace.DisplayP3).iccProfile().data())
    src = make_heic(tmp_path / "turned.heic", size=(640, 480), orientation=6, icc=p3)
    img, reader, fmt = image._read(src)
    assert fmt == b"heic" and reader is None
    assert (img.width(), img.height()) == (480, 640)  # turned like the phone showed it
    assert near(img.pixelColor(240, 10), GREEN) and near(img.pixelColor(240, 630), RED)
    assert "P3" in img.colorSpace().description()


def test_convert_options_and_outputs(qapp, tmp_path):
    from PyQt6.QtGui import QImage, QImageReader

    src = make_heic(tmp_path / "trip.heic")
    names = handlers.options_for(filetypes.IMAGE, handlers.CONVERT, "HEIC")
    assert names == ["PNG", "JPG", "WEBP", "BMP", "TIFF", "PDF"]
    [jpg], _ = run(image.convert, src, "JPG")
    assert jpg.name == "trip.jpg" and QImageReader(str(jpg)).format() == b"jpeg"
    assert near(QImage(str(jpg)).pixelColor(20, 20), GREEN)
    [pdf], _ = run(image.convert, src, "PDF")
    import pymupdf

    with pymupdf.open(pdf) as doc:
        assert len(doc) == 1 and b"Exif" not in doc.xref_stream_raw(doc[0].get_images()[0][0])


def test_metadata_strip_makes_a_clean_jpg(qapp, tmp_path):
    from PIL import ExifTags, Image

    src = make_heic(tmp_path / "IMG_1.heic")
    [out], info = run(metadata.strip, src, "Metadata")
    assert out.name == "IMG_1 (clean).jpg" and "saved as JPG" in info["detail"]
    data = out.read_bytes()
    assert b"Exif" not in data and b"Google" not in data and b"GPSLatitude" not in data
    with Image.open(out) as im:
        assert not im.getexif().get_ifd(ExifTags.IFD.GPSInfo)


def test_heic_without_metadata_is_skipped(qapp, tmp_path):
    import pillow_heif
    from PIL import Image

    plain = tmp_path / "plain.heic"
    pillow_heif.from_pillow(Image.new("RGB", (64, 48), (1, 2, 3))).save(str(plain))
    with pytest.raises(Skip, match="No metadata"):
        run(metadata.strip, plain, "Metadata")


def test_compress_to_a_size_gives_a_jpg(qapp, tmp_path):
    src = make_heic(tmp_path / "big.heic", size=(3000, 2000))
    try:
        [out], info = run(compress.to_target, src, "20 KB")
    except Skip as skip:  # flat test picture: the HEIC may already be tiny
        assert skip.info["fits"]
        return
    assert out.suffix == ".jpg" and out.stat().st_size <= 20_000 and "saved as JPG" in info["detail"]


def test_multi_image_heic_is_refused_not_cut(qapp, tmp_path):
    src = make_heic(tmp_path / "burst.heic", images=2)
    with pytest.raises(Skip, match="Multi-image HEIC"):
        image._read(src)


def test_hub_thumbnail_is_rendered_by_the_helper(qapp, tmp_path):
    from PyQt6.QtGui import QImage

    from app.handlers.pdf import render_thumbnail

    out = render_thumbnail(make_heic(tmp_path / "t.heic", size=(800, 600)), 128, tmp_path / "thumbs")
    thumb = QImage(str(out))
    assert max(thumb.width(), thumb.height()) == 128


def test_wheel_asks_the_helper_for_a_heic_thumbnail(qapp, tmp_path):
    from PyQt6.QtCore import QUrl

    from app.bridge import Bridge
    from app.config import Config

    b = Bridge(Config())
    asked = []
    b.thumbnailRequested.connect(asked.append)
    src = make_heic(tmp_path / "IMG.HEIC")
    b.open()
    assert b.dragEnter([QUrl.fromLocalFile(str(src))]) and b.park()
    assert asked == [str(src)] and b.parkedThumb == ""  # until the PNG is ready


# ------------------------------------------------------------------ editor ---

def bridge_for(path, tool="crop"):
    from app.config import Config
    from app.editor import document
    from app.editor.bridge import EditorBridge
    from app.icons import icon_path
    from tests.test_editor_bridge import wait_for

    b = EditorBridge(document.open_document(path), tool, Config(), software=False, icon_paths=icon_path)
    b.loadMeta()
    while b.metaStatus == "loading":
        wait_for(b.metaChanged)
    return b


def saved(b):
    from tests.test_editor_bridge import wait_for

    got = []
    b.saved.connect(got.append)
    b.save()
    if not got:
        wait_for(b.saved)
    return b._doc.path.with_name(got[0])


def test_editor_opens_heic_and_saves_jpg_with_its_details(qapp, tmp_path):
    from PIL import ExifTags, Image

    src = make_heic(tmp_path / "IMG_7.heic", size=(640, 480), orientation=6)
    b = bridge_for(src)
    assert (b.pageWidth, b.pageHeight) == (480, 640)
    b.setCrop(0, 0, 1, 0.5)
    assert b.outputName == "IMG_7 (cropped).jpg" and b.locationChoice
    out = saved(b)
    with Image.open(out) as im:
        ex = im.getexif()
        assert im.format == "JPEG" and im.size == (480, 320)
        assert ex[0x010F] == "Google" and ex.get(0x0112, 1) == 1  # camera kept, upright
        assert not ex.get_ifd(ExifTags.IFD.GPSInfo)              # location left out by default
    assert b"GPSLatitude" not in out.read_bytes()


def test_info_shows_heic_details_read_only_and_cleans_to_jpg(qapp, tmp_path):
    src = make_heic(tmp_path / "IMG_9.heic")
    b = bridge_for(src, tool="metadata")
    rows = {r["key"]: r for s in b.metaSections for r in s["items"]}
    assert rows["gps"]["value"].startswith("12.97160° N") and rows["field:make"]["value"] == "Google"
    assert not b.metaEditable and "HEIC" in b.metaNote and b.metaAny
    assert "GPSLatitude" in b.metaXmp()
    b.removeAllMeta()
    assert b.metaClean and b.outputName == "IMG_9 (clean).jpg"
    rows = {r["key"]: r for s in b.metaSections for r in s["items"]}
    assert rows["gps"]["state"] == "removed"
    out = saved(b)
    assert out.name == "IMG_9 (clean).jpg" and b"Exif" not in out.read_bytes()
