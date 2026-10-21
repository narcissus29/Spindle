"""Redaction and annotations: what gets saved, and that it's really gone."""

import itertools

import pytest

from app.editor import document, marks, search, state as st
from tests.conftest import add_exif_gps, make_image, make_pdf, make_photo

SECRET = "SECRET-NAME-4711"


def _text_pdf(path, rotate=0, cropbox=None, mediabox=None):
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=400, height=600)
    page.insert_text((60, 120), f"Patient: {SECRET} lives here", fontsize=14)
    page.insert_text((60, 160), "Public line that stays", fontsize=14)
    page.insert_text((60, 200), "Category of cat food, CAT toys", fontsize=14)
    if mediabox:
        doc.xref_set_key(page.xref, "MediaBox", "[%g %g %g %g]" % mediabox)
    if cropbox:
        page.set_cropbox(pymupdf.Rect(cropbox))
    page.set_rotation(rotate)
    doc.set_metadata({"author": "Dr Who", "title": "Records"})
    doc.save(path)
    doc.close()
    return path


def _all_text(path) -> str:
    import pymupdf

    with pymupdf.open(path) as doc:
        return "\n".join(p.get_text() for p in doc)


def _decoded_bytes(path) -> bytes:
    """Every object and decoded stream: proof the text is gone, not hidden."""
    import pymupdf

    out = [path.read_bytes()]
    with pymupdf.open(path) as doc:
        for xref in range(1, doc.xref_length()):
            out.append(doc.xref_object(xref).encode("latin-1", "replace"))
            if doc.xref_is_stream(xref):
                out.append(doc.xref_stream(xref) or b"")
    return b"\n".join(out)


def _redact_found(src, term, **kw):
    doc = document.PdfDocument(src)
    page_state = doc.initial_state()
    with document.LOCK:
        hits = search.find_on_page(doc._doc[0], term, **kw)
    boxes = [{"id": i, "rect": r} for i, h in enumerate(hits) for r in h["rects"]]
    s = st.with_layer(page_state, 0, redactions=boxes)
    return doc, s, hits


# ------------------------------------------------------------- PDF redact ---

CASES = list(itertools.product((0, 90, 180, 270), (None, (40, 60, 380, 560))))


@pytest.mark.parametrize("rotate,cropbox,mediabox", [c + (None,) for c in CASES]
                         + [(r, None, (50, 80, 450, 680)) for r in (90, 270)])
def test_redaction_removes_the_text_on_any_page_rotation(qapp, tmp_path, rotate, cropbox, mediabox):
    src = _text_pdf(tmp_path / "records.pdf", rotate, cropbox, mediabox)
    doc, s, hits = _redact_found(src, SECRET)
    assert len(hits) == 1
    out = doc.save(s)
    doc.close()
    assert out.name == "records (redacted).pdf"
    text = _all_text(out)
    assert SECRET not in text and "Public line that stays" in text and "Patient:" in text
    assert SECRET.encode() not in _decoded_bytes(out)
    # the box is black where the text was shown
    import pymupdf

    with pymupdf.open(out) as saved:
        page = saved[0]
        x, y, w, h = hits[0]["rects"][0]
        pix = page.get_pixmap()
        assert pix.pixel(int(x + w / 2), int(y + h / 2)) == (0, 0, 0)


def test_redacted_pdf_has_no_metadata_and_no_attachments(qapp, tmp_path):
    import pymupdf

    src = _text_pdf(tmp_path / "r.pdf")
    with pymupdf.open(src) as d:
        d.embfile_add("notes.txt", f"original says {SECRET}".encode())
        d.saveIncr()
    doc, s, _ = _redact_found(src, SECRET)
    out = doc.save(s)
    doc.close()
    with pymupdf.open(out) as saved:
        assert not saved.metadata["author"] and not saved.metadata["title"]
        assert saved.embfile_count() == 0 and saved.xref_xml_metadata() == 0
        assert saved.version_count == 1
    assert SECRET.encode() not in _decoded_bytes(out)


def test_annotation_over_a_redaction_is_removed(qapp, tmp_path):
    import pymupdf

    src = _text_pdf(tmp_path / "a.pdf")
    with pymupdf.open(src) as d:
        d[0].add_freetext_annot(pymupdf.Rect(60, 105, 300, 125), f"note: {SECRET}")
        d[0].add_text_annot((350, 400), "unrelated sticky note")
        d.saveIncr()
    doc, s, _ = _redact_found(src, SECRET)
    out = doc.save(s)
    doc.close()
    with pymupdf.open(out) as saved:
        kinds = [a.type[1] for a in saved[0].annots()]
    assert kinds == ["Text"]  # the sticky note elsewhere stays
    assert SECRET.encode() not in _decoded_bytes(out)


def test_image_pixels_under_a_box_are_blanked(qapp, tmp_path):
    import pymupdf

    photo = make_photo(tmp_path / "face.jpg", size=(400, 300))
    src = tmp_path / "id.pdf"
    d = pymupdf.open()
    p = d.new_page(width=400, height=300)
    p.insert_image(p.rect, filename=str(photo))
    d.save(src)
    d.close()
    doc = document.PdfDocument(src)
    s = st.with_layer(doc.initial_state(), 0, redactions=[{"id": 1, "rect": [100, 100, 120, 80]}])
    out = doc.save(s)
    doc.close()
    with pymupdf.open(out) as saved:
        xref = saved[0].get_images()[0][0]
        pix = pymupdf.Pixmap(saved, xref)
        original = tuple(pymupdf.Pixmap(str(photo)).pixel(160, 140)[:3])
        blanked = tuple(pix.pixel(160, 140)[:3])
        assert blanked != original and blanked in ((255, 255, 255), (0, 0, 0))  # gone from the image itself
        assert tuple(pix.pixel(20, 20)[:3]) == tuple(pymupdf.Pixmap(str(photo)).pixel(20, 20)[:3])  # elsewhere untouched


# ------------------------------------------------------------------ search ---

def test_search_case_whole_word_and_line_breaks(qapp, tmp_path):
    src = _text_pdf(tmp_path / "s.pdf")
    doc = document.PdfDocument(src)
    page = doc._doc[0]
    with document.LOCK:
        assert len(search.find_on_page(page, "cat")) == 3                       # Category, cat, CAT
        assert len(search.find_on_page(page, "cat", whole_word=True)) == 2      # cat, CAT
        assert len(search.find_on_page(page, "cat", match_case=True, whole_word=True)) == 1
        across = search.find_on_page(page, "here Public")                       # wraps onto the next line
        found = search.find_on_page(page, SECRET.lower())
    doc.close()
    assert len(across) == 1 and len(across[0]["rects"]) == 2
    assert found[0]["text"] == SECRET and found[0]["context"].endswith("Patient: ")


# ------------------------------------------------------------ annotations ---

def _all_marks():
    return [
        {"id": 1, "type": "pen", "color": "#e5322d", "width": 3, "points": [[50, 300], [120, 330], [180, 300]]},
        {"id": 2, "type": "highlight", "color": "#ffd60a", "width": 16, "points": [[55, 155], [230, 155]]},
        {"id": 3, "type": "arrow", "color": "#1e5bd8", "width": 3, "p1": [60, 420], "p2": [220, 380]},
        {"id": 4, "type": "rect", "color": "#2fa84f", "width": 3, "rect": [250, 300, 100, 60]},
        {"id": 5, "type": "text", "color": "#000000", "size": 18, "text": "Checked", "rect": [60, 240, 80, 22]},
    ]


@pytest.mark.parametrize("rotate,cropbox", CASES)
def test_marks_become_real_pdf_annotations_where_drawn(qapp, tmp_path, rotate, cropbox):
    import pymupdf

    src = _text_pdf(tmp_path / "n.pdf", rotate, cropbox)
    doc = document.PdfDocument(src)
    w, h = doc.page_size(0)
    # place marks inside the displayed page whatever its shape
    s = st.with_layer(doc.initial_state(), 0, marks=_all_marks())
    out = doc.save(s)
    doc.close()
    assert out.name == "n (annotated).pdf"
    with pymupdf.open(out) as saved:
        page = saved[0]
        kinds = sorted(a.type[1] for a in page.annots())
        assert kinds == ["FreeText", "Ink", "Ink", "Line", "Polygon", "Square"]
        pix = page.get_pixmap()
        r, g, b = pix.pixel(120, 330)[:3]  # on the red pen stroke (displayed coordinates)
        assert r > 180 and g < 90 and b < 90
        r, g, b = pix.pixel(251, 330)[:3]  # left edge of the green rectangle
        assert g > 120 and r < 120


@pytest.mark.parametrize("rotate,cropbox", [(0, None), (90, (40, 60, 380, 560)), (270, (40, 60, 380, 560))])
def test_flatten_burns_annotations_into_the_page(qapp, tmp_path, rotate, cropbox):
    import pymupdf

    src = _text_pdf(tmp_path / "f.pdf", rotate, cropbox)
    doc = document.PdfDocument(src)
    s = st.with_layer(doc.initial_state(), 0, marks=_all_marks())
    out = doc.save(s, {"flatten": True})
    doc.close()
    with pymupdf.open(out) as saved:
        page = saved[0]
        assert list(page.annots()) == []
        assert "Checked" in page.get_text()
        r, g, b = page.get_pixmap().pixel(120, 330)[:3]
        assert r > 180 and g < 90


def test_marks_and_redactions_on_a_rotated_cropped_page_save_together(qapp, tmp_path):
    src = _text_pdf(tmp_path / "both.pdf")
    doc, s, _ = _redact_found(src, SECRET)
    s = st.with_layer(s, 0, marks=_all_marks()[:1])
    s = st.turn_page(s, 0, "cw")
    s = st.set_page(s, 0, crop=[0.0, 0.0, 0.9, 0.9])
    out = doc.save(s)
    doc.close()
    assert out.name == "both (redacted).pdf"
    assert SECRET not in _all_text(out)


# ------------------------------------------------------------------ images ---

def test_image_redaction_is_burned_in_and_metadata_free(qapp, tmp_path):
    from PyQt6.QtGui import QColor, QImage

    src = make_photo(tmp_path / "id.jpg", size=(600, 400))
    add_exif_gps(src, "GPS-SECRET-MARK")
    doc = document.open_document(src)
    s = {**doc.initial_state(), "redactions": [{"id": 1, "rect": [100, 50, 200, 100]}],
         "adjust": {"brightness": 0.4, "contrast": 0, "saturation": 0}}
    out = doc.save(s)
    assert out.name == "id (redacted).jpg"
    img = QImage(str(out))
    c = img.pixelColor(200, 100)
    assert max(c.red(), c.green(), c.blue()) <= 8  # black even with brightness raised
    assert b"GPS-SECRET-MARK" not in out.read_bytes() and b"Exif" not in out.read_bytes()


def test_image_marks_land_where_drawn_after_rotate_and_mirror(qapp, tmp_path):
    """Saved full size == the preview rendered with the same state."""
    import numpy as np
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QImage

    from app.editor import imaging
    from tests.test_editor_document import _array

    src = make_image(tmp_path / "plain.png", "PNG", size=(800, 500))
    doc = document.open_document(src)
    s = st.turn_image(st.turn_image(doc.initial_state(), "cw"), "h")
    s = {**s, "marks": _all_marks(), "redactions": [{"id": 9, "rect": [500, 100, 120, 90]}]}
    out = doc.save(s)
    saved = QImage(str(out))
    assert (saved.width(), saved.height()) == (500, 800)
    preview = imaging.render_image(doc.preview, s, doc.preview_scale())
    saved = saved.scaled(preview.size(), Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    assert np.abs(_array(saved) - _array(preview)).mean() < 2
    # the redaction box: source (500..620, 100..190) -> after cw + flip lands at x 100..190, y 500..620
    c = QImage(str(out)).pixelColor(145, 560)
    assert (c.red(), c.green(), c.blue()) == (0, 0, 0)


def test_edited_copies_keep_text_chunks_unless_removed_or_redacted(qapp, tmp_path):
    from PyQt6.QtGui import QImage

    src = make_image(tmp_path / "t.png", "PNG")
    img = QImage(str(src))
    img.setText("Author", "Private Person")
    img.save(str(src))
    doc = document.open_document(src)
    cropped = {**doc.initial_state(), "crop": [0, 0, 0.5, 0.5]}
    assert b"Private Person" in doc.save(cropped).read_bytes()  # carried over to the edited copy
    removed = {**cropped, "meta": {"set": {}, "drop": ["text:Author"], "clean": True}}
    assert b"Private Person" not in doc.save(removed).read_bytes()
    redacted = {**cropped, "redactions": [{"id": 1, "rect": [0, 0, 4, 4]}]}
    assert b"Private Person" not in doc.save(redacted).read_bytes()


# --------------------------------------------------------------- geometry ---

def test_hit_testing_and_moving():
    pen, _hl, arrow, rect, text = _all_marks()
    assert marks.hit(pen, 120, 331, tolerance=2) and not marks.hit(pen, 120, 360, tolerance=2)
    assert marks.hit(arrow, 140, 400, tolerance=2)
    assert marks.hit(rect, 300, 330, tolerance=0)            # inside counts
    assert marks.hit(text, 70, 250, tolerance=0)
    m = marks.moved(arrow, 10, -5)
    assert m["p1"] == [70, 415] and m["p2"] == [230, 375] and arrow["p1"] == [60, 420]


def test_output_tags_for_marks():
    s = st.new_image_state()
    assert st.output_tag({**s, "marks": _all_marks()}) == "annotated"
    assert st.output_tag({**s, "marks": _all_marks(), "crop": [0, 0, .5, .5]}) == "edited"
    assert st.output_tag({**s, "marks": _all_marks(), "redactions": [{"id": 1, "rect": [0, 0, 1, 1]}]}) == "redacted"


@pytest.mark.parametrize("rotate,cropbox", [(0, None), (90, (40, 60, 380, 560))])
def test_non_latin_text_is_written_into_the_page(qapp, tmp_path, rotate, cropbox):
    import pymupdf

    src = _text_pdf(tmp_path / "u.pdf", rotate, cropbox)
    doc = document.PdfDocument(src)
    mark = {"id": 1, "type": "text", "color": "#000000", "size": 16, "text": "Grüße Ωμέγα", "rect": [60, 300, 140, 20]}
    out = doc.save(st.with_layer(doc.initial_state(), 0, marks=[mark]))
    doc.close()
    with pymupdf.open(out) as saved:
        page = saved[0]
        words = page.get_text("words")
        hit = [w for w in words if "Ωμέγα" in w[4]]
        assert hit, page.get_text()
        r = pymupdf.Rect(hit[0][:4]) * page.rotation_matrix
        r.normalize()
        assert 55 < r.x0 < 260 and 290 < r.y0 < 330 and r.width > r.height  # where drawn, reading left to right


# ---- bookmarks ----

def _pdf_with_bookmarks(path):
    import pymupdf

    doc = pymupdf.open()
    p1 = doc.new_page(width=400, height=600)
    p1.insert_text((60, 120), f"Patient: {SECRET} lives here", fontsize=14)
    p2 = doc.new_page(width=400, height=600)
    p2.insert_text((60, 120), "Account holder Max Mustermann", fontsize=14)
    p2.insert_text((60, 200), "Public summary", fontsize=14)
    doc.set_toc([[1, f"Records of {SECRET.lower()}", 1],        # search term, other case
                 [2, "Summary", 1],
                 [1, "Account of Max  Mustermann", 2],          # box text, extra space
                 [1, "Appendix", 2]])
    doc.save(path)
    doc.close()
    return path


def test_redacted_text_is_struck_from_bookmark_titles(qapp, tmp_path):
    import pymupdf

    src = _pdf_with_bookmarks(tmp_path / "b.pdf")
    doc = document.PdfDocument(src)
    with document.LOCK:
        hit = search.find_on_page(doc._doc[0], SECRET)[0]
        name = search.find_on_page(doc._doc[1], "Max Mustermann")[0]
    s = st.with_layer(doc.initial_state(), 0, redactions=[{"id": 1, "rect": hit["rects"][0]}])
    x, y, w, h = name["rects"][0]
    s = st.with_layer(s, 1, redactions=[{"id": 2, "rect": [x - 2, y - 2, w + 4, h + 4]}])  # a drawn box
    out = doc.save(s)
    doc.close()
    with pymupdf.open(out) as saved:
        toc = saved.get_toc()
    assert toc == [[1, "Records of [redacted]", 1], [2, "Summary", 1],
                   [1, "Account of [redacted]", 2], [1, "Appendix", 2]]  # kept, pointing where they did
    data = _decoded_bytes(out)
    assert SECRET.encode() not in data and SECRET.lower().encode() not in data
    assert b"Mustermann" not in data


def test_short_redacted_pieces_are_struck_as_whole_words_only(qapp, tmp_path):
    """An initial "R" leaves the r's inside "Report" and "Quarterly" alone."""
    import pymupdf

    src = tmp_path / "r.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=400, height=600)
    page.insert_text((60, 120), "Report by R Sharma", fontsize=14)
    doc.set_toc([[1, "Report by R Sharma", 1], [1, "Quarterly results (r)", 1], [1, "R&D", 1]])
    doc.save(src)
    doc.close()
    doc = document.PdfDocument(src)
    with document.LOCK:
        [hit] = search.find_on_page(doc._doc[0], "R", match_case=True, whole_word=True)
    s = st.with_layer(doc.initial_state(), 0, redactions=[{"id": 1, "rect": hit["rects"][0]}])
    out = doc.save(s)
    doc.close()
    with pymupdf.open(out) as saved:
        assert [t[1] for t in saved.get_toc()] == [
            "Report by [redacted] Sharma", "Quarterly results ([redacted])", "[redacted]&D"]
        assert saved[0].get_text().split() == ["Report", "by", "Sharma"]


def test_bookmarks_untouched_without_redaction(qapp, tmp_path):
    import pymupdf

    src = _pdf_with_bookmarks(tmp_path / "b.pdf")
    doc = document.PdfDocument(src)
    out = doc.save(st.turn_page(doc.initial_state(), 0, "cw"))
    doc.close()
    with pymupdf.open(out) as saved:
        assert saved.get_toc()[0][1] == f"Records of {SECRET.lower()}"
