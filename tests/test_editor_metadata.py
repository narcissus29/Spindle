"""Info tool (step 4c): the metadata viewer / editor, and the PDF deep
clean shared with the wheel's silent Metadata action."""

import struct

import pytest

from app.config import Config
from app.editor import containers, document, metadata as md, state as st
from app.editor.bridge import EditorBridge
from app.editor.exif import Exif
from app.icons import icon_path
from tests.conftest import (camera_exif, make_camera_photo, make_image, make_multipage_tiff, make_photo,
                            make_rich_pdf)
from tests.test_editor_bridge import wait_for

BENGALURU = (12.9716, 77.5946)


def image_data(data: bytes) -> bytes:
    """The scan data of a JPEG (from the real start of scan, not one inside
    an EXIF thumbnail)."""
    blocks = containers.split(data)
    return b"".join(b.raw for b in blocks if b.raw[:2] == b"\xff\xda" or b.raw == b"\xff\xd9")


def pillow_exif(path):
    from PIL import ExifTags, Image

    with Image.open(path) as im:
        ex = im.getexif()
        return dict(ex), dict(ex.get_ifd(ExifTags.IFD.Exif)), dict(ex.get_ifd(ExifTags.IFD.GPSInfo))


def changes(drop=(), **sets):
    return {"set": {k.replace("__", ":"): v for k, v in sets.items()}, "drop": list(drop), "clean": False}


def bridge_for(path, tool="metadata"):
    b = EditorBridge(document.open_document(path), tool, Config(), software=False, icon_paths=icon_path)
    b.loadMeta()  # the Info tool and the save sheet do this
    while b.metaStatus == "loading":
        wait_for(b.metaChanged)
    return b


# ------------------------------------------------------------------ EXIF ---

def test_exif_round_trip_is_exact_and_keeps_any_text():
    tiff = camera_exif(b"\xff\xd8thumb\xff\xd9", artist="Zoë Ravi")
    ex = Exif.parse(tiff)
    assert ex.to_bytes() == Exif.parse(ex.to_bytes()).to_bytes()
    again = Exif.parse(ex.to_bytes())
    assert again.ifds == ex.ifds and again.thumbnail == b"\xff\xd8thumb\xff\xd9"
    assert again.value("0", 0x013B) == "Zoë Ravi"  # Pillow's own writer makes this "Zo??"
    ex.set_text("0", 0x013B, "Ünïcødé ✓")
    assert Exif.parse(ex.to_bytes()).value("0", 0x013B) == "Ünïcødé ✓"


def test_big_endian_exif_survives(qapp):
    ex = Exif(">")
    ex.set_text("0", 0x010F, "Nikon")
    ex.set_rationals("gps", 2, [(12, 1), (58, 1), (1776, 100)])
    back = Exif.parse(ex.to_bytes())
    assert back.endian == ">" and back.value("0", 0x010F) == "Nikon"
    assert back.value("gps", 2) == pytest.approx((12, 58, 17.76))


# ---------------------------------------------------------------- viewer ---

def test_viewer_lists_a_phone_photo(qapp, tmp_path):
    meta = md.ImageMeta(make_camera_photo(tmp_path / "p.jpg"))
    rows = {r["key"]: r for s in meta.sections(st.NO_META) for r in s["items"]}
    assert rows["gps"]["value"] == "12.97160° N, 77.59460° E"
    assert rows["field:artist"]["value"] == "Ravi Tej" and rows["field:make"]["value"] == "Google"
    assert rows["field:datetaken"]["value"] == "2024-05-01 10:00:00"
    assert rows["tag:exif:33434"]["value"] == "1/120 s" and rows["tag:exif:33437"]["value"] == "f/1.8"
    assert rows["thumbnail"].get("thumb") and rows["xmp"].get("view")
    assert rows["comment"]["value"] == "taken at home"
    assert not rows["keep:orientation"]["removable"]
    assert "GPSLatitude" in meta.xmp_text() and meta.thumbnail()[:2] == b"\xff\xd8"


def test_nothing_to_show_for_a_clean_photo(qapp, tmp_path):
    b = bridge_for(make_photo(tmp_path / "plain.jpg", size=(64, 48)))
    assert b.metaStatus == "ready" and not b.metaAny and not b.metaClean


# ------------------------------------------------------------ remove all ---

def test_remove_all_is_lossless_and_named_clean(qapp, tmp_path):
    src = make_camera_photo(tmp_path / "trip.jpg", orientation=6)
    b = bridge_for(src)
    assert b.metaAny and not b.metaClean
    b.removeAllMeta()
    assert b.metaClean and b.outputName == "trip (clean).jpg" and b.undoText == "Remove all metadata"
    b.save()
    out = src.with_name(wait_for(b.saved)[0])
    data = out.read_bytes()
    for secret in (b"Google", b"Pixel", b"Ravi", b"MAKERNOTE", b"taken at home", b"xmpmeta", b"HDR+"):
        assert secret not in data
    assert image_data(data) == image_data(src.read_bytes())  # not re-encoded
    ifd0, exif, gps = pillow_exif(out)
    assert ifd0 == {0x0112: 6} and not gps  # only the orientation is left: still shown upright
    assert md.ImageMeta(out).keys() == []
    # the same as the wheel's silent strip
    from app.handlers.metadata import strip_jpeg

    assert image_data(strip_jpeg(src.read_bytes())[0]) == image_data(data)


def test_remove_all_drops_motion_photo_video(qapp, tmp_path):
    from tests.conftest import append_motion_video

    src = make_camera_photo(tmp_path / "m.jpg")
    append_motion_video(src, b"GPS 12.9716N")
    meta = md.ImageMeta(src)
    assert "trailing" in meta.keys()
    out = meta.apply({"set": {}, "drop": meta.keys(), "clean": True})
    assert b"ftyp" not in out and out.endswith(b"\xff\xd9")


# --------------------------------------------------------------- editing ---

def test_edit_fields_and_location_without_reencoding(qapp, tmp_path):
    src = make_camera_photo(tmp_path / "e.jpg")
    b = bridge_for(src)
    assert b.setMeta("field:artist", "Zoë Example") == ""
    assert b.setMeta("field:datetaken", "2023-12-24 18:30") == ""
    assert b.setMeta("gps", "48.8584, 2.2945") == ""
    assert b.setMeta("field:copyright", "CC BY 4.0") == ""
    b.removeMeta("tag:0:305")  # Software
    assert not b.metaClean and b.outputName == "e (edited).jpg"
    b.save()
    out = src.with_name(wait_for(b.saved)[0])
    ifd0, exif, gps = pillow_exif(out)
    assert ifd0[0x013B].encode("latin-1").decode("utf-8") == "Zoë Example"  # UTF-8 text intact
    assert ifd0[0x8298] == "CC BY 4.0" and 0x0131 not in ifd0 and ifd0[0x010F] == "Google"
    assert exif[0x9003] == "2023:12:24 18:30:00" and exif[0x927C].startswith(b"MAKERNOTE")
    assert gps[1] == "N" and gps[3] == "E" and gps[6] == pytest.approx(920.5)
    lat = gps[2][0] + gps[2][1] / 60 + gps[2][2] / 3600
    lon = gps[4][0] + gps[4][1] / 60 + gps[4][2] / 3600
    assert (lat, lon) == pytest.approx((48.8584, 2.2945), abs=1e-6)
    assert image_data(out.read_bytes()) == image_data(src.read_bytes())
    assert md.ImageMeta(out).thumbnail() == md.ImageMeta(src).thumbnail()  # kept when not removed


def test_bad_values_are_refused_with_a_reason(qapp, tmp_path):
    b = bridge_for(make_camera_photo(tmp_path / "x.jpg"))
    assert "date" in b.setMeta("field:datetaken", "next tuesday")
    assert "latitude" in b.setMeta("gps", "somewhere nice").lower()
    assert "-90" in b.setMeta("gps", "123, 45")
    assert not b.canUndo  # nothing was changed
    assert b.setMeta("gps", "33.8688° S, 151.2093° E") == ""
    assert st.meta(b._state)["set"]["gps"] == [-33.8688, 151.2093]


def test_changes_undo_and_restore(qapp, tmp_path):
    b = bridge_for(make_camera_photo(tmp_path / "u.jpg"))
    b.removeMeta("gps")
    b.setMeta("field:artist", "Someone")
    rows = {r["key"]: r for s in b.metaSections for r in s["items"]}
    assert rows["gps"]["state"] == "removed" and rows["tag:gps:6"]["state"] == "removed"
    assert rows["field:artist"]["state"] == "edited" and rows["field:artist"]["value"] == "Someone"
    b.restoreMeta("field:artist")
    assert st.meta(b._state)["set"] == {}
    for _ in range(3):
        b.undo()
    assert st.meta(b._state) == st.NO_META and not b.modified
    b.setMeta("field:artist", "Ravi Tej")  # the same as before: no change
    assert not b.canRedo or not b.modified


def test_png_text_and_new_exif(qapp, tmp_path):
    from PyQt6.QtGui import QImage

    src = make_image(tmp_path / "logo.png", "PNG", alpha=True)
    img = QImage(str(src))
    img.setText("parameters", "a prompt, seed 42")
    img.setText("Author", "Ravi")
    img.save(str(src))
    meta = md.ImageMeta(src)
    assert {"text:parameters", "text:Author"} <= set(meta.keys())
    out = tmp_path / "out.png"
    out.write_bytes(meta.apply(changes(["text:parameters"], field__artist="New Artist")))
    data = out.read_bytes()
    assert b"seed 42" not in data and b"Ravi" in data
    assert data.index(b"eXIf") < data.index(b"IDAT")
    assert pillow_exif(out)[0][0x013B] == "New Artist"
    assert QImage(str(out)) == QImage(str(src))


def test_webp_gets_exif_without_losing_pixels(qapp, tmp_path):
    """A simple WEBP has no room for metadata: the extended header is added."""
    from PyQt6.QtGui import QImage

    src = make_image(tmp_path / "w.webp", "WEBP", alpha=True)
    meta = md.ImageMeta(src)
    out = tmp_path / "w2.webp"
    out.write_bytes(meta.apply(changes(field__artist="Ravi", gps=[1.5, 2.5])))
    assert out.read_bytes()[12:16] == b"VP8X"
    assert pillow_exif(out)[0][0x013B] == "Ravi"
    assert QImage(str(out)) == QImage(str(src))
    back = md.ImageMeta(out)
    assert back.location() == pytest.approx([1.5, 2.5])
    plain = tmp_path / "w3.webp"
    plain.write_bytes(back.apply({"set": {}, "drop": back.keys(), "clean": True}))
    assert b"EXIF" not in plain.read_bytes() and QImage(str(plain)) == QImage(str(src))


def test_tiff_can_only_be_cleaned(qapp, tmp_path):
    from PIL import Image
    from PyQt6.QtGui import QImage

    src = tmp_path / "scan.tif"
    Image.new("RGB", (40, 30), "teal").save(src, tiffinfo={0x013B: "Scanner Person", 0x0131: "ScanApp"})
    b = bridge_for(src)
    assert not b.metaEditable and "TIFF" in b.metaNote and b.metaAny
    b.removeAllMeta()
    assert b.outputName == "scan (clean).tif"
    b.save()
    out = src.with_name(wait_for(b.saved)[0])
    assert b"Scanner Person" not in out.read_bytes()
    assert QImage(str(out)).convertToFormat(QImage.Format.Format_RGB32) == \
        QImage(str(src)).convertToFormat(QImage.Format.Format_RGB32)


# ----------------------------------------------------- edited picture copies ---

def test_edited_copies_keep_metadata_upright_and_without_thumbnail(qapp, tmp_path):
    from PyQt6.QtGui import QImageReader

    src = make_camera_photo(tmp_path / "turned.jpg", size=(320, 240), orientation=6)  # shown 240 x 320
    doc = document.open_document(src)
    state = {**doc.initial_state(), "crop": [0, 0, 0.5, 0.5]}
    out = doc.save(state, {"keep_location": True})
    ifd0, exif, gps = pillow_exif(out)
    assert ifd0[0x0112] == 1 and ifd0[0x010F] == "Google" and gps[1] == "N"
    assert (exif[0xA002], exif[0xA003]) == (120, 160)
    assert md.ImageMeta(out).thumbnail() is None  # it shows the uncropped photo
    assert b'tiff:Orientation="1"' in out.read_bytes() and b"exif:GPSLatitude" in out.read_bytes()
    reader = QImageReader(str(out))
    reader.setAutoTransform(True)
    assert reader.read().size().width() == 120  # not turned a second time
    # changes made in Info apply to the edited copy as well
    out2 = doc.save({**state, "meta": changes(["xmp", "field:artist"])}, {"keep_location": True})
    ifd0, _exif, gps2 = pillow_exif(out2)
    assert gps2 and 0x013B not in ifd0 and b"xmpmeta" not in out2.read_bytes()


@pytest.mark.parametrize("edit", [{"crop": [0, 0, 0.5, 0.5]}, {"adjust": {"brightness": 0.2, "contrast": 0, "saturation": 0}},
                                  {"marks": [{"id": 1, "type": "rect", "color": "#ff0000", "width": 3,
                                              "rect": [10, 10, 50, 40]}]}], ids=["crop", "adjust", "annotate"])
def test_edited_copies_leave_the_location_out_by_default(qapp, tmp_path, edit):
    src = make_camera_photo(tmp_path / "p.jpg")
    doc = document.open_document(src)
    out = doc.save({**doc.initial_state(), **edit})
    ifd0, exif, gps = pillow_exif(out)
    data = out.read_bytes()
    assert not gps and b"GPS" not in data  # neither in EXIF nor in XMP
    assert ifd0[0x010F] == "Google" and exif[0x9003] == "2024:05:01 10:00:00"  # the rest is kept
    assert b"xmpmeta" in data and b"taken at home" in data


def test_a_location_set_in_info_is_kept_in_edited_copies(qapp, tmp_path):
    src = make_camera_photo(tmp_path / "p.jpg")
    doc = document.open_document(src)
    out = doc.save({**doc.initial_state(), "crop": [0, 0, 0.5, 0.5], "meta": changes(gps=[48.8584, 2.2945])})
    gps = pillow_exif(out)[2]
    assert gps[1] == "N" and gps[2][0] == 48


def test_removing_the_location_in_info_also_cleans_xmp(qapp, tmp_path):
    src = make_camera_photo(tmp_path / "p.jpg")
    out = tmp_path / "out.jpg"
    out.write_bytes(md.ImageMeta(src).apply(changes(["gps"])))
    data = out.read_bytes()
    assert b"GPS" not in data and b"<dc:title>Trip</dc:title>" in data and not pillow_exif(out)[2]


def test_keep_location_is_offered_only_when_it_matters(qapp, tmp_path):
    b = bridge_for(make_camera_photo(tmp_path / "g.jpg"), tool="crop")
    assert not b.locationChoice  # nothing edited: Info decides
    b.setCrop(0, 0, 0.5, 0.5)
    assert b.locationChoice
    b.setTool("metadata")
    b.removeMeta("gps")
    assert not b.locationChoice  # already removed in Info
    b.undo()
    b.addRedaction(0, 0, 10, 10)
    assert not b.locationChoice  # redacted copies carry nothing
    plain = bridge_for(make_photo(tmp_path / "plain.jpg", size=(64, 48)), tool="crop")
    plain.setCrop(0, 0, 0.5, 0.5)
    assert not plain.locationChoice  # no location to keep


def test_redacted_copies_carry_no_metadata(qapp, tmp_path):
    src = make_camera_photo(tmp_path / "r.jpg")
    doc = document.open_document(src)
    out = doc.save({**doc.initial_state(), "redactions": [{"id": 1, "rect": [0, 0, 20, 20]}]})
    data = out.read_bytes()
    assert b"Exif" not in data and b"Google" not in data and b"xmpmeta" not in data


# ------------------------------------------------------------------- PDF ---

def _jpeg_streams(path):
    import pymupdf

    with pymupdf.open(path) as doc:
        return [doc.xref_stream_raw(x) for x in range(1, doc.xref_length())
                if doc.xref_get_key(x, "Subtype")[1] == "/Image"]


def _render(path):
    import pymupdf

    with pymupdf.open(path) as doc:
        return doc[0].get_pixmap(dpi=72).samples


def test_pdf_viewer_and_partial_changes(qapp, tmp_path):
    src = make_rich_pdf(tmp_path / "report.pdf", make_camera_photo(tmp_path / "photo.jpg"))
    b = bridge_for(src)
    rows = {r["key"]: r for s in b.metaSections for r in s["items"]}
    assert rows["info:author"]["value"] == "Dr Who" and rows["info:creationDate"]["value"] == "2024-05-01 10:00:00"
    assert rows["images"]["value"] == "1 photo, 1 with location"
    assert rows["comments"]["value"] == "Dr Who" and rows["attachments"]["value"] == "notes.txt"
    assert rows["custom:Company"]["value"] == "Acme Secret Corp"
    assert "dc:creator" in b.metaXmp()
    assert b.setMeta("info:title", "Public report") == ""
    assert b.setMeta("info:modDate", "2025-01-02") == ""
    b.removeMeta("images")
    b.removeMeta("custom:Company")
    b.save()
    out = src.with_name(wait_for(b.saved)[0])
    import pymupdf

    from app.handlers.metadata import _custom_info

    with pymupdf.open(out) as doc:
        info = doc.metadata
        assert _custom_info(doc) == {}
    assert info["title"] == "Public report" and info["author"] == "Dr Who"  # untouched fields stay
    assert info["modDate"].startswith("D:20250102")
    [photo] = _jpeg_streams(out)
    assert b"Google" not in photo and b"Exif" not in photo
    assert image_data(photo) == image_data(_jpeg_streams(src)[0])  # same JPEG, minus metadata
    assert _render(out) == _render(src)


def test_pdf_remove_all_deep_cleans(qapp, tmp_path):
    src = make_rich_pdf(tmp_path / "report.pdf", make_camera_photo(tmp_path / "photo.jpg"))
    b = bridge_for(src)
    b.removeAllMeta()
    assert b.metaClean and b.outputName == "report (clean).pdf"
    b.save()
    out = src.with_name(wait_for(b.saved)[0])
    from tests.test_editor_marks import _decoded_bytes

    data = _decoded_bytes(out)
    for secret in (b"Dr Who", b"Site visit", b"Quartz", b"private notes", b"secret working file", b"Google",
                   b"dc:creator", b"Acme"):
        assert secret not in data, secret
    import pymupdf

    from app.handlers.metadata import pdf_removed, survey_pdf

    with pymupdf.open(out) as doc:
        assert pdf_removed(survey_pdf(doc, out)) == []
        assert doc[0].annots().__next__().info["content"] == "Check this"  # the comment itself stays
    assert _render(out) == _render(src)


def test_wheel_strip_deep_cleans_pdf_photos(qapp, tmp_path):
    """The silent Metadata action (several files dropped) cleans photos
    inside PDFs too, not just the document info."""
    from app.handlers import metadata
    from app.handlers.common import Context

    src = make_rich_pdf(tmp_path / "report.pdf", make_camera_photo(tmp_path / "photo.jpg"))
    ctx = Context(src, {})
    metadata.strip(src, "Metadata", ctx)
    [out] = ctx.commit()
    assert "photo metadata (1 image)" in ctx.info["detail"] and "comment authors" in ctx.info["detail"]
    [photo] = _jpeg_streams(out)
    assert b"Exif" not in photo and not metadata.exif_has_gps(photo)
    assert image_data(photo) == image_data(_jpeg_streams(src)[0])
    assert _render(out) == _render(src)


def test_pdf_with_only_photo_metadata_is_not_skipped(qapp, tmp_path):
    import pymupdf

    from app.handlers import metadata
    from app.handlers.common import Context

    photo = make_camera_photo(tmp_path / "photo.jpg")
    src = tmp_path / "plain.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_image(pymupdf.Rect(0, 0, 100, 75), stream=photo.read_bytes())
    doc.save(src)
    doc.close()
    ctx = Context(src, {})
    metadata.strip(src, "Metadata", ctx)
    [out] = ctx.commit()
    assert ctx.info["note"] == "Cleaned" and b"Google" not in b"".join(_jpeg_streams(out))


def test_pdf_with_only_custom_info_is_not_skipped(qapp, tmp_path):
    import pymupdf

    from app.handlers import metadata
    from app.handlers.common import Context

    src = tmp_path / "word.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.set_metadata({"title": "x"})
    doc.xref_set_key(int(doc.xref_get_key(-1, "Info")[1].split()[0]), "Company", "(Acme Secret Corp)")
    doc.set_metadata({"title": ""})
    doc.save(src)
    doc.close()
    ctx = Context(src, {})
    metadata.strip(src, "Metadata", ctx)
    [out] = ctx.commit()
    assert b"Acme" not in out.read_bytes()


def test_gps_entries_removed_with_the_location_restore_with_it(qapp, tmp_path):
    meta = md.ImageMeta(make_camera_photo(tmp_path / "g.jpg"))
    rows = {r["key"]: r for s in meta.sections(changes(["gps"])) for r in s["items"]}
    assert rows["tag:gps:6"]["state"] == "removed" and rows["tag:gps:6"]["covered"]
    assert not rows["gps"]["covered"]


def test_redacted_pdf_copies_clean_their_photos(qapp, tmp_path):
    src = make_rich_pdf(tmp_path / "report.pdf", make_camera_photo(tmp_path / "photo.jpg"))
    doc = document.PdfDocument(src)
    out = doc.save(st.with_layer(doc.initial_state(), 0, redactions=[{"id": 1, "rect": [400, 700, 50, 50]}]))
    doc.close()
    [photo] = _jpeg_streams(out)
    assert b"Exif" not in photo and b"Google" not in photo


# ----------------------------------------------------------------- wheel ---

def test_metadata_wedge_opens_the_viewer_for_one_file_and_strips_many(qapp, tmp_path):
    from PyQt6.QtCore import QUrl

    from app import handlers
    from app.bridge import Bridge
    from app.filetypes import IMAGE, PDF

    assert handlers.get_handler(IMAGE, handlers.ACTIONS, "Metadata") == "editor:metadata"
    assert handlers.get_handler(PDF, handlers.ACTIONS, "Metadata", count=3) == "app.handlers.metadata:strip"
    b = Bridge(Config())
    asked, jobs = [], []
    b.editorRequested.connect(lambda tool, path: asked.append(tool))
    b.jobRequested.connect(jobs.append)
    one = make_photo(tmp_path / "a.jpg", size=(32, 32))
    b.open()
    assert b.dragEnter([QUrl.fromLocalFile(str(one))])
    assert b.drop([o["name"] for o in b.options].index("Metadata"))
    assert asked == ["metadata"] and not jobs
    b2 = Bridge(Config())
    b2.jobRequested.connect(jobs.append)
    two = make_photo(tmp_path / "b.jpg", size=(32, 32))
    b2.open()
    assert b2.dragEnter([QUrl.fromLocalFile(str(one)), QUrl.fromLocalFile(str(two))])
    assert b2.drop([o["name"] for o in b2.options].index("Metadata"))
    [job] = jobs
    assert {i.spec for i in job.items} == {"app.handlers.metadata:strip"} and len(job.items) == 2


def test_multipage_tiff_viewer_doesnt_open(qapp, tmp_path):
    with pytest.raises(document.OpenError):
        document.open_document(make_multipage_tiff(tmp_path / "pages.tif"))


def test_webp_container_header_is_valid(qapp, tmp_path):
    src = make_image(tmp_path / "s.webp", "WEBP")
    blocks = containers.split(src.read_bytes())
    data = containers.join(blocks + [containers.webp_chunk(b"EXIF", Exif().to_bytes(), "exif")], "webp")
    size = struct.unpack("<I", data[4:8])[0]
    assert size == len(data) - 8 and data[12:16] == b"VP8X" and data[20] & 0x08
