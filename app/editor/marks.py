"""Annotations ("marks") and redaction boxes: geometry, hit-testing, and
drawing them into a saved image (QPainter) or PDF page (PyMuPDF).

All lengths are content units (see state.py): image pixels, or PDF points
of the page as displayed with its own rotation, y down.

    {"id": 7, "type": "pen",       "color": "#e5322d", "width": 4.0, "points": [[x, y], ...]}
    {"id": 8, "type": "highlight", "color": "#ffd60a", "width": 18.0, "points": [[x, y], ...]}
    {"id": 9, "type": "arrow",     "color", "width", "p1": [x, y], "p2": [x, y]}
    {"id": 10, "type": "rect",     "color", "width", "rect": [x, y, w, h]}
    {"id": 11, "type": "text",     "color", "size": 18, "text": "Hello", "rect": [x, y, w, h]}
    redaction: {"id": 12, "rect": [x, y, w, h]}

The canvas (qml/editor/MarksLayer.qml) draws the same shapes with the same
numbers: highlighter strokes are see-through (HIGHLIGHT_OPACITY, applied to
the whole stroke at once, so where it crosses itself it isn't darker),
arrow heads use arrow_head(), text uses TEXT_FONT at `size` px, word-wrapped
in `rect`, and stays readable on a mirrored image. Marks are clipped to the
page, on screen and in the saved file.
"""

from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPainterPathStroker, QPen, QPolygonF, QTransform

TYPES = ("pen", "highlight", "arrow", "rect", "text")
HIGHLIGHT_OPACITY = 0.38
TEXT_FONT = "Helvetica"  # PDFs' built-in Helvetica; Arial / Liberation Sans stand in on screen


# ------------------------------------------------------------- geometry ---

def arrow_head(p1, p2, width: float) -> tuple[list, list, list, list]:
    """(tip, left, right, base): the filled head of an arrow from p1 to p2.
    The line itself ends at `base`, so a thick line never pokes through."""
    (x1, y1), (x2, y2) = p1, p2
    length = max(math.hypot(x2 - x1, y2 - y1), 1e-6)
    ux, uy = (x2 - x1) / length, (y2 - y1) / length
    head = min(max(width * 4.5, 8.0 * width ** 0.5), length * 0.6)
    half = head * 0.55
    bx, by = x2 - ux * head, y2 - uy * head
    return [x2, y2], [bx - uy * half, by + ux * half], [bx + uy * half, by - ux * half], [bx, by]


def bounds(mark: dict) -> tuple[float, float, float, float]:
    """(x0, y0, x1, y1) around everything the mark paints."""
    kind = mark["type"]
    if kind in ("pen", "highlight"):
        xs = [p[0] for p in mark["points"]]
        ys = [p[1] for p in mark["points"]]
        pad = mark["width"] / 2
        return min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad
    if kind == "arrow":
        pts = [mark["p1"], *arrow_head(mark["p1"], mark["p2"], mark["width"])[:3]]
        pad = mark["width"] / 2
        return (min(p[0] for p in pts) - pad, min(p[1] for p in pts) - pad,
                max(p[0] for p in pts) + pad, max(p[1] for p in pts) + pad)
    x, y, w, h = mark["rect"]
    return x, y, x + w, y + h


def _segment_distance(px, py, a, b) -> float:
    (ax, ay), (bx, by) = a, b
    dx, dy = bx - ax, by - ay
    t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def hit(mark: dict, x: float, y: float, tolerance: float) -> bool:
    """Is (x, y) on the mark? Rectangles and text count inside too, so they
    are easy to grab; lines count within half their width + tolerance."""
    kind = mark.get("type")
    if kind in ("pen", "highlight"):
        pts = mark["points"]
        reach = mark["width"] / 2 + tolerance
        if len(pts) == 1:
            return math.hypot(x - pts[0][0], y - pts[0][1]) <= reach
        return any(_segment_distance(x, y, pts[i], pts[i + 1]) <= reach for i in range(len(pts) - 1))
    if kind == "arrow":
        tip, left, right, _ = arrow_head(mark["p1"], mark["p2"], mark["width"])
        return (_segment_distance(x, y, mark["p1"], mark["p2"]) <= mark["width"] / 2 + tolerance
                or QPolygonF([QPointF(*tip), QPointF(*left), QPointF(*right)]).containsPoint(
                    QPointF(x, y), Qt.FillRule.OddEvenFill))
    rx, ry, rw, rh = mark["rect"]
    return rx - tolerance <= x <= rx + rw + tolerance and ry - tolerance <= y <= ry + rh + tolerance


def moved(mark: dict, dx: float, dy: float) -> dict:
    out = dict(mark)
    if "points" in mark:
        out["points"] = [[round(p[0] + dx, 3), round(p[1] + dy, 3)] for p in mark["points"]]
    for key in ("p1", "p2"):
        if key in mark:
            out[key] = [round(mark[key][0] + dx, 3), round(mark[key][1] + dy, 3)]
    if "rect" in mark:
        x, y, w, h = mark["rect"]
        out["rect"] = [round(x + dx, 3), round(y + dy, 3), w, h]
    return out


def _stroke_path(points: list) -> QPainterPath:
    path = QPainterPath(QPointF(*points[0]))
    if len(points) == 1:
        path.lineTo(QPointF(points[0][0] + 0.01, points[0][1]))  # a dot
    for p in points[1:]:
        path.lineTo(QPointF(*p))
    return path


def clamped(mark: dict, width: float, height: float) -> dict:
    """The mark kept inside the page (0..width, 0..height): boxes and text
    are moved / shrunk to fit, arrow ends pulled in. Freehand strokes are
    left as drawn; what lies outside the page is clipped, on screen and in
    the saved file alike."""
    def cx(v):
        return round(min(max(v, 0.0), width), 2)

    def cy(v):
        return round(min(max(v, 0.0), height), 2)

    out = dict(mark)
    if "p1" in mark:
        out["p1"] = [cx(mark["p1"][0]), cy(mark["p1"][1])]
        out["p2"] = [cx(mark["p2"][0]), cy(mark["p2"][1])]
    if "rect" in mark:
        x, y, w, h = mark["rect"]
        if mark.get("type") == "text":  # keep its size, move it in
            w, h = min(w, width), min(h, height)
            x, y = min(max(x, 0.0), width - w), min(max(y, 0.0), height - h)
            out["rect"] = [round(x, 2), round(y, 2), round(w, 2), round(h, 2)]
        else:  # cut it to the page
            x0, y0, x1, y1 = cx(x), cy(y), cx(x + w), cy(y + h)
            out["rect"] = [x0, y0, round(x1 - x0, 2), round(y1 - y0, 2)]
    return out


# ---------------------------------------------------------------- images ---

def orient_transform(width: int, height: int, rot: int, mirror: bool) -> QTransform:
    """Source pixel -> pixel of the image after imaging.orient()."""
    t = QTransform(-1, 0, 0, 1, width, 0) if mirror else QTransform()
    return t * QImage.trueMatrix(QTransform().rotate(rot % 360), width, height)


def burn_in(image: QImage, marks: list, redactions: list, transform: QTransform, rot: int, mirrored: bool) -> QImage:
    """Draw marks and solid redaction boxes into `image` (already oriented
    by `transform`). Redaction boxes go last, over everything: what they
    cover is gone from the saved pixels."""
    if not marks and not redactions:
        return image
    if image.format() not in (QImage.Format.Format_ARGB32_Premultiplied, QImage.Format.Format_RGB32):
        image = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied if image.hasAlphaChannel()
                                      else QImage.Format.Format_RGB32)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    for mark in marks:
        painter.save()
        _paint_mark(painter, mark, transform, rot, mirrored)
        painter.restore()
    painter.setTransform(transform)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)  # crisp, fully opaque edges
    for box in redactions:
        x, y, w, h = box["rect"]
        painter.fillRect(QRectF(x, y, w, h), QColor("black"))
    painter.end()
    return image


def _paint_mark(painter: QPainter, mark: dict, transform: QTransform, rot: int, mirrored: bool) -> None:
    color = QColor(mark["color"])
    kind = mark["type"]
    if kind == "text":
        # Readable on a mirrored image too: place by the transformed centre,
        # then turn by the rotation only (as the canvas does).
        x, y, w, h = mark["rect"]
        centre = transform.map(QPointF(x + w / 2, y + h / 2))
        painter.translate(centre)
        painter.rotate(rot % 360)
        scale = math.sqrt(abs(transform.determinant()))  # content units -> pixels
        painter.scale(scale, scale)
        painter.setPen(color)
        painter.setFont(text_font(mark["size"]))
        painter.drawText(QRectF(-w / 2, -h / 2, w, h),
                         int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop) | int(Qt.TextFlag.TextWordWrap),
                         mark["text"])
        return
    painter.setTransform(transform)
    width = mark["width"]
    pen = QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    if kind in ("pen", "highlight"):
        if kind == "highlight":
            painter.setOpacity(HIGHLIGHT_OPACITY)  # the whole stroke at once: no darker overlaps
        painter.strokePath(_stroke_path(mark["points"]), pen)
    elif kind == "arrow":
        tip, left, right, base = arrow_head(mark["p1"], mark["p2"], width)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.strokePath(_stroke_path([mark["p1"], base]), pen)
        head = QPainterPath()
        head.addPolygon(QPolygonF([QPointF(*tip), QPointF(*left), QPointF(*right)]))
        head.closeSubpath()
        painter.fillPath(head, color)
    elif kind == "rect":
        x, y, w, h = mark["rect"]
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(QRectF(x + width / 2, y + width / 2, max(w - width, 0), max(h - width, 0)))


def text_font(size: float) -> QFont:
    font = QFont(TEXT_FONT)
    font.setPixelSize(max(1, round(size)))
    return font


# ------------------------------------------------------------------ PDFs ---

def _rgb(color: str) -> tuple[float, float, float]:
    c = QColor(color)
    return c.redF(), c.greenF(), c.blueF()


# Two coordinate conversions, because PyMuPDF isn't consistent on pages that
# are rotated *and* whose crop / media box doesn't start at (0, 0):
# annotations, redaction areas and text search use the "unrotated page"
# space (derotation_matrix gets those right), but drawing into the page
# content lands somewhere else. Content is therefore placed from real PDF
# coordinates computed here (checked against rendering for every rotation
# and box offset in tests/test_editor_marks.py).

def _to_page(page, rect_or_point):
    """Displayed (own rotation applied) -> PyMuPDF's unrotated page
    coordinates, which annotations and redactions use."""
    return rect_or_point * page.derotation_matrix


def visible_box(page) -> tuple[float, float, float, float]:
    """The page's visible area (its crop box) in PDF coordinates, y up.
    PyMuPDF reports page.cropbox with x as in the file but y measured down
    from the top of the media box, so it is converted back here."""
    mb, cb = page.mediabox, page.cropbox
    return cb.x0, mb.y1 - cb.y1, cb.x1, mb.y1 - cb.y0


def pdf_point(page, x: float, y: float) -> tuple[float, float]:
    """Displayed point (the page's own rotation applied, y down) -> PDF
    coordinates (y up), as written in the file."""
    x0, y0, x1, y1 = visible_box(page)
    w, h = x1 - x0, y1 - y0
    u, v = {0: (x, y), 90: (y, h - x), 180: (w - x, h - y), 270: (w - y, x)}[page.rotation % 360]
    return x0 + u, y1 - v


def _content_rect(page, x: float, y: float, w: float, h: float):
    """Displayed rect -> the rect PyMuPDF's drawing methods need to draw there."""
    import pymupdf

    r = pymupdf.Rect(pymupdf.Point(*pdf_point(page, x, y)), pymupdf.Point(*pdf_point(page, x + w, y + h)))
    r.normalize()
    r = r * page.transformation_matrix
    r.normalize()
    return r


REDACTED = "[redacted]"
WHOLE_WORD_BELOW = 3  # shorter redacted bits (an initial "R") are struck from titles only as whole words


def redact_pdf_page(page, redactions: list) -> set[str]:
    """True redaction: the text under each box is deleted, image pixels
    under it are blanked, vector drawings fully under it are removed, and
    annotations, form fields and links touching it are deleted (they can
    hold the same text). The boxes are filled black.

    Returns the text that was under the boxes (one string per line), so
    the same words can be struck from bookmark titles (redact_titles)."""
    import pymupdf

    if not redactions:
        return set()
    removed: set[str] = set()
    rects = []
    for box in redactions:
        x, y, w, h = box["rect"]
        r = _to_page(page, pymupdf.Rect(x, y, x + w, y + h))
        r.normalize()
        rects.append(r)
        for line in page.get_textbox(r).splitlines():
            if line.strip():
                removed.add(" ".join(line.split()))
    for annot in list(page.annots() or []):
        if any(annot.rect.intersects(r) for r in rects):
            page.delete_annot(annot)
    for widget in list(page.widgets() or []):
        if any(widget.rect.intersects(r) for r in rects):
            page.delete_widget(widget)
    for link in page.get_links():
        if any(pymupdf.Rect(link["from"]).intersects(r) for r in rects):
            page.delete_link(link)
    for r in rects:
        page.add_redact_annot(r, fill=False)  # removal only; the fill is drawn below
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_PIXELS,
                          graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
                          text=pymupdf.PDF_REDACT_TEXT_REMOVE)
    # MuPDF would paint its own fill misplaced on rotated pages with an
    # offset crop box: draw the black boxes from real PDF coordinates.
    for box in redactions:
        page.draw_rect(_content_rect(page, *box["rect"]), color=None, fill=(0, 0, 0), overlay=True)
    return removed


def redact_titles(doc, removed: set[str]) -> int:
    """Bookmarks (the outline) are kept, but any text that was redacted on
    a page is replaced by "[redacted]" in every bookmark title, whatever
    page the bookmark points to. Matching ignores case and runs of spaces.
    Pieces shorter than WHOLE_WORD_BELOW characters only match as whole
    words: an initial "R" is struck from "Report by R Sharma", but the r's
    inside words stay. Returns how many titles changed."""
    import re

    if not removed:
        return 0
    toc = doc.get_toc(simple=False)
    if not toc:
        return 0
    parts = []
    for text in sorted(removed, key=len, reverse=True):  # longest first: "R Sharma" before "R"
        body = r"\s+".join(re.escape(word) for word in text.split())
        if len(text) < WHOLE_WORD_BELOW:
            body = rf"(?<!\w){body}(?!\w)"
        parts.append(body)
    # one pass, so a short piece never matches inside an inserted "[redacted]"
    pattern = re.compile("|".join(parts), re.IGNORECASE)
    changed = 0
    for entry in toc:
        title = pattern.sub(REDACTED, entry[1])
        if title != entry[1]:
            entry[1] = title
            changed += 1
    if changed:
        doc.set_toc(toc)  # rewrites the outline; the old title objects are dropped on save
    return changed


def annotate_pdf_page(page, marks: list) -> None:
    """Add the marks as real PDF annotations (viewers can still edit or
    delete them). Text other PDF fonts can't show (outside Latin-1) is
    written into the page content instead."""
    import pymupdf

    for mark in marks:
        kind = mark["type"]
        rgb = _rgb(mark["color"])
        if kind in ("pen", "highlight"):
            pts = [_to_page(page, pymupdf.Point(*p)) for p in mark["points"]]
            if len(pts) == 1:
                pts.append(pts[0] + (0.01, 0))
            annot = page.add_ink_annot([[(p.x, p.y) for p in pts]])
            annot.set_border(width=mark["width"])
            annot.set_colors(stroke=rgb)
            if kind == "highlight":
                annot.set_opacity(HIGHLIGHT_OPACITY)
            annot.update()
        elif kind == "arrow":
            tip, left, right, base = arrow_head(mark["p1"], mark["p2"], mark["width"])
            # The shaft as a line, the head as a filled triangle, so it looks
            # the same in every viewer (PDF line endings are drawn by each
            # viewer at its own size).
            line = page.add_line_annot(_to_page(page, pymupdf.Point(*mark["p1"])), _to_page(page, pymupdf.Point(*base)))
            line.set_border(width=mark["width"])
            line.set_colors(stroke=rgb)
            line.update()
            head = page.add_polygon_annot([_to_page(page, pymupdf.Point(*p)) for p in (tip, left, right)])
            head.set_border(width=0)
            head.set_colors(stroke=rgb, fill=rgb)
            head.update()
        elif kind == "rect":
            x, y, w, h = mark["rect"]
            r = _to_page(page, pymupdf.Rect(x, y, x + w, y + h))
            r.normalize()
            annot = page.add_rect_annot(r)
            annot.set_border(width=mark["width"])
            annot.set_colors(stroke=rgb)
            annot.update()
        elif kind == "text":
            _add_text(page, mark, rgb)


def draw_pdf_page(page, marks: list) -> None:
    """"Flatten annotations": draw the marks into the page content itself
    (they can't be edited or removed afterwards), looking like the
    annotations would."""
    import pymupdf

    def pt(p):
        return pymupdf.Point(*pdf_point(page, *p)) * page.transformation_matrix

    for mark in marks:
        kind = mark["type"]
        rgb = _rgb(mark["color"])
        if kind in ("pen", "highlight"):
            pts = [pt(p) for p in mark["points"]]
            if len(pts) == 1:
                pts.append(pts[0] + (0.01, 0))
            page.draw_polyline(pts, color=rgb, width=mark["width"], lineCap=1, lineJoin=1,
                               stroke_opacity=HIGHLIGHT_OPACITY if kind == "highlight" else 1, overlay=True)
        elif kind == "arrow":
            tip, left, right, base = arrow_head(mark["p1"], mark["p2"], mark["width"])
            page.draw_line(pt(mark["p1"]), pt(base), color=rgb, width=mark["width"], overlay=True)
            page.draw_polyline([pt(tip), pt(left), pt(right)], color=None, fill=rgb, closePath=True, overlay=True)
        elif kind == "rect":
            x, y, w, h = mark["rect"]
            half = mark["width"] / 2
            page.draw_rect(_content_rect(page, x + half, y + half, max(w - 2 * half, 0), max(h - 2 * half, 0)),
                           color=rgb, width=mark["width"], overlay=True)
        elif kind == "text":
            _add_text(page, mark, rgb, flatten=True)


def _add_text(page, mark: dict, rgb, flatten: bool = False) -> None:
    import pymupdf

    x, y, w, h = mark["rect"]
    size = mark["size"]
    # A little room: Helvetica in the PDF and its stand-in on screen differ
    # slightly in width, and a too-narrow box would wrap the text.
    box = pymupdf.Rect(x, y, x + w * 1.15 + size * 0.5, y + h + size * 0.35)
    box &= page.rect  # never past the page edge
    r = _to_page(page, box)
    r.normalize()
    try:
        mark["text"].encode("cp1252")
        latin = True
    except UnicodeEncodeError:
        latin = False
    if latin and not flatten:
        annot = page.add_freetext_annot(r, mark["text"], fontsize=size, fontname="Helv", text_color=rgb,
                                        rotate=page.rotation)
        annot.set_border(width=0)
        annot.update(text_color=rgb)
    else:  # flattened, or a script the PDF base fonts lack: into the page content
        css = f"* {{font-family: sans-serif; font-size: {size}px; color: rgb({','.join(str(round(v * 255)) for v in rgb)});}}"
        page.insert_htmlbox(_content_rect(page, box.x0, box.y0, box.width, box.height),
                            mark["text"].replace("&", "&amp;").replace("<", "&lt;").replace("\n", "<br>"),
                            css=css, rotate=page.rotation)
