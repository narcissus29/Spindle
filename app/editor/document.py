"""Opening a file in the editor, rendering what the canvas shows, and
saving the result as a new file next to the original.

The original is never written to. Saving goes through the same safe path
as the wheel's handlers (handlers.common.Context): a hidden temporary file
that is renamed to a free name ("photo (cropped).jpg", "photo (cropped)
(1).jpg", ...) only once it is complete.

Images: the canvas shows a preview copy at most PREVIEW_MAX px on its long
side (JPEGs are decoded straight to that size, so even a 50 MP photo opens
quickly). Saving re-reads the original at full size and applies the edit
state to it (imaging.render_image).

PDFs: pages are rendered on demand at the size the canvas needs. MuPDF is
not thread-safe, so every PyMuPDF call in the process goes through LOCK
(the image provider renders on Qt's loader thread, saving runs on its own).
Saving opens a fresh copy of the file and, page by page, applies the
redactions (true redaction: the text is deleted), the annotations (real
PDF annotations, or drawn into the page content when "Flatten
annotations" is ticked), rotation and crop,
then drops deleted pages, and writes it out in full (never as an
incremental update, which would keep the old content in the file).

Metadata (Info tool, metadata.py): for images, changes to metadata alone
are swapped into the original file without re-encoding it. A copy whose
picture changed (crop, colors, marks) is a new image: it gets the
original's metadata with the changes applied (upright, new size, no
thumbnail; JPEG, PNG and WEBP), but without the location unless "Keep
location" is ticked in the save sheet. For PDFs the changes are written into
the copy before it is saved.

Anything redacted -> the saved file carries no metadata at all: for PDFs
document info, XMP, attachments, JavaScript, page thumbnails (which
would still show the unredacted page), private app data, comment authors
and the photos' own metadata are removed and unused objects dropped;
redacted images carry no metadata. Bookmarks stay, but text that was
redacted anywhere is replaced by "[redacted]" in their titles.
"""

from __future__ import annotations

import threading
from pathlib import Path

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QImage, QImageIOHandler, QImageReader, QImageWriter

from .. import filetypes
from ..handlers.common import Context, HandlerError, Skip
from . import imaging, state as st

PREVIEW_MAX = 4096       # px, long side of an image's on-screen copy
THUMB_HEIGHT = 160       # px, page strip thumbnails (shown at ~80 logical px)
MAX_RENDER_PIXELS = 40_000_000  # cap for one zoomed-in page render

LOCK = threading.RLock()  # every PyMuPDF call goes through this

QImageReader.setAllocationLimit(1024)  # MB, like the helper: big scans are fine


class OpenError(Exception):
    """The file can't be edited; the message is shown on the wheel."""


def open_document(path: Path) -> "ImageDocument | PdfDocument":
    if not path.is_file():
        raise OpenError("File not found")
    try:
        kind = filetypes.sniff_kind(path)
    except OSError as exc:
        raise OpenError(f"Can't read file ({exc.strerror or exc})") from None
    if kind == filetypes.PDF:
        return PdfDocument(path)
    if kind == filetypes.IMAGE:
        return ImageDocument(path)
    raise OpenError("Not supported")


# ------------------------------------------------------------------ image ---

# reader format -> (writer format, extension or None for the source's own)
_IMAGE_OUT = {
    b"jpeg": (b"jpeg", None), b"jpg": (b"jpeg", None),
    b"png": (b"png", None), b"webp": (b"webp", None), b"bmp": (b"bmp", None),
    b"tiff": (b"tiff", None), b"tif": (b"tiff", None),
    b"gif": (b"png", ".png"),  # Qt can't write GIF
    b"heic": (b"jpeg", ".jpg"),  # nor HEIC (Spindle only decodes it)
}
_JPEG_QUALITY = 95


class ImageDocument:
    kind = filetypes.IMAGE

    def __init__(self, path: Path) -> None:
        from ..handlers.image import frame_problem

        self.path = path
        self._meta = None
        self._meta_lock = threading.Lock()
        self.last_note = ""  # after a save with a size limit: "48 KB"
        self._lossless_webp = False
        if filetypes.is_heic_file(path):
            self._open_heic(path)
            return
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        self.format = bytes(reader.format())
        if not self.format:
            raise OpenError(f"Can't read image ({reader.errorString()})")
        if problem := frame_problem(path, reader, self.format):
            raise OpenError(problem)
        raw = reader.size()  # as stored, before the EXIF orientation
        turned = bool(reader.transformation() & QImageIOHandler.Transformation.TransformationRotate90)
        self.width, self.height = (raw.height(), raw.width()) if turned else (raw.width(), raw.height())
        if self.width <= 0 or self.height <= 0:
            raise OpenError(f"Can't read image ({reader.errorString()})")
        scale = min(1.0, PREVIEW_MAX / max(self.width, self.height))
        if scale < 1.0:
            reader.setScaledSize(QSize(max(1, round(raw.width() * scale)), max(1, round(raw.height() * scale))))
        preview = reader.read()
        if preview.isNull():
            raise OpenError(f"Can't read image ({reader.errorString()})")
        self.preview = preview
        self.has_alpha = preview.hasAlphaChannel()
        self._lossless_webp = self.format == b"webp" and b"VP8L" in path.read_bytes()[:64]

    def _open_heic(self, path: Path) -> None:
        """HEIC: decoded once with pi-heif; saved copies are JPG."""
        from .. import heic

        self.format = b"heic"
        try:
            full = heic.read(path)
        except heic.HeicError as exc:
            raise OpenError(str(exc)) from None
        self.width, self.height = full.width(), full.height()
        if max(self.width, self.height) > PREVIEW_MAX:
            full = full.scaled(PREVIEW_MAX, PREVIEW_MAX, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
        self.preview = full
        self.has_alpha = full.hasAlphaChannel()

    def metadata(self):
        """What the file carries (metadata.ImageMeta), read on first use."""
        from .metadata import ImageMeta

        with self._meta_lock:
            if self._meta is None:
                self._meta = ImageMeta(self.path)
            return self._meta

    @property
    def page_count(self) -> int:
        return 1

    def page_size(self, index: int = 0) -> tuple[float, float]:
        """Size as displayed (EXIF orientation applied), in pixels."""
        return float(self.width), float(self.height)

    def initial_state(self) -> dict:
        return st.new_image_state()

    # ---- what the canvas shows ----

    def render_page(self, index: int, width: int) -> QImage:
        if width <= 0 or width >= self.preview.width():
            return self.preview
        return self.preview.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)

    def thumbnail(self, index: int) -> QImage:
        return self.preview.scaledToHeight(THUMB_HEIGHT, Qt.TransformationMode.SmoothTransformation)

    def preview_scale(self) -> float:
        """Preview pixels per full-size pixel."""
        return self.preview.width() / self.width

    def adjusted_preview(self, width: int, adjust: dict) -> QImage:
        """Software renderer only (no shaders): the preview with the color
        adjustments baked in, at the size it is shown."""
        return imaging.apply_adjust(self.render_page(0, width), adjust)

    # ---- saving ----

    def save(self, state: dict, options: dict | None = None) -> Path:
        from ..handlers.image import _read

        limit = (options or {}).get("limit")
        self.last_note = ""
        if st.pixels_unchanged(state) and st.meta_changed(state) and not limit:
            return self._save_metadata(st.meta(state), st.output_tag(state))
        if limit:
            return self._save_limited(state, int(limit))
        out_fmt, ext = _IMAGE_OUT.get(self.format, (b"png", ".png"))
        ctx = Context(self.path)
        try:
            try:
                image, _reader, _fmt = _read(self.path)
            except (HandlerError, Skip) as exc:
                raise OpenError(str(exc)) from None
            result = imaging.render_image(image, state)
            if out_fmt in (b"jpeg", b"bmp") and result.hasAlphaChannel():
                result = result.convertToFormat(QImage.Format.Format_RGB32)
            result = imaging.without_text(result)
            out = ctx.output_file(ext or self.path.suffix, tag=st.output_tag(state))
            self._write(result, out, out_fmt)
            if not st.has_redactions(state):  # redacted copies carry no metadata
                meta = self.metadata()
                if meta.editable or meta.kind == "heic":
                    out.write_bytes(meta.carry_over(out.read_bytes(), _location_choice(state, options),
                                                    (result.width(), result.height())))
            [saved] = ctx.commit()
            return saved
        except BaseException:
            ctx.discard()
            raise

    def _save_limited(self, state: dict, limit: int) -> Path:
        """"Limit file size": the edited picture at the best quality (and
        if needed a smaller size) that fits under `limit` bytes, as JPEG
        (WEBP stays WEBP). No metadata: it would take space."""
        from PyQt6.QtGui import QColor, QPainter

        from ..handlers.image import _read
        from ..handlers.target import fit_image, result_label, size_label

        ctx = Context(self.path)
        try:
            try:
                image, _reader, _fmt = _read(self.path)
            except (HandlerError, Skip) as exc:
                raise OpenError(str(exc)) from None
            result = imaging.render_image(image, state)
            webp = self.format == b"webp"
            if not webp and result.hasAlphaChannel():
                flat = QImage(result.size(), QImage.Format.Format_RGB32)
                flat.setColorSpace(result.colorSpace())
                flat.fill(QColor("white"))
                painter = QPainter(flat)
                painter.drawImage(0, 0, result)
                painter.end()
                result = flat
            fit = fit_image(result, b"webp" if webp else b"jpeg", limit)
            ext = ".webp" if webp else (self.path.suffix if self.format in (b"jpeg", b"jpg") else ".jpg")
            out = ctx.output_file(ext, tag=_limited_tag(state, size_label(limit)))
            out.write_bytes(fit["data"])
            n = len(fit["data"])
            self.last_note = (result_label(n) if fit["fits"]
                              else f"smallest possible: {result_label(n, up=True)}, over {size_label(limit)}")
            if (fit["width"], fit["height"]) != (result.width(), result.height()):
                self.last_note += f", {fit['width']} \u00d7 {fit['height']} px"
            [saved] = ctx.commit()
            return saved
        except BaseException:
            ctx.discard()
            raise

    def _write(self, image: QImage, out: Path, out_fmt: bytes) -> None:
        writer = QImageWriter(str(out), out_fmt)
        if out_fmt == b"jpeg":
            writer.setQuality(_JPEG_QUALITY)
            writer.setOptimizedWrite(True)
        elif out_fmt == b"webp":
            writer.setQuality(100 if self._lossless_webp else _JPEG_QUALITY)  # 100 = lossless
        elif out_fmt == b"tiff":
            writer.setCompression(1)  # LZW
        if not writer.write(image):
            raise OpenError(f"Can't write {out_fmt.decode().upper()} ({writer.errorString()})")

    def _save_metadata(self, changes: dict, tag: str) -> Path:
        """Only metadata changed: the original file with new metadata,
        image data untouched. TIFF can only be cleaned: it is re-saved
        losslessly without any (its metadata sits in the image's own
        directory). HEIC can only be cleaned too: the copy is a JPG."""
        meta = self.metadata()
        ctx = Context(self.path)
        try:
            out = ctx.output_file(".jpg" if meta.kind == "heic" else self.path.suffix, tag=tag)
            if meta.editable:
                out.write_bytes(meta.apply(changes))
            elif meta.kind == "heic" and "all" in changes["drop"]:
                from ..handlers.image import _flatten, _read

                image, _reader, _fmt = _read(self.path)  # HEIC can't be rewritten: a clean JPG
                self._write(imaging.without_text(_flatten(image)), out, b"jpeg")
            elif meta.kind == "tiff" and "all" in changes["drop"]:
                from ..handlers.image import _read

                try:
                    image, _reader, _fmt = _read(self.path)
                except (HandlerError, Skip) as exc:
                    raise OpenError(str(exc)) from None
                self._write(imaging.without_text(image), out, b"tiff")
            else:
                raise OpenError("Spindle can't change metadata in this format")
            [saved] = ctx.commit()
            return saved
        except BaseException:
            ctx.discard()
            raise

    def close(self) -> None:
        pass


# -------------------------------------------------------------------- PDF ---

def _size_label(n) -> str:
    from ..handlers.target import size_label

    return size_label(int(n))


def _limited_tag(state: dict, limit_label: str) -> str:
    """"photo (50 KB).jpg" when only the size changes, else
    "photo (cropped, 50 KB).jpg"."""
    if st.is_identity(state):
        return limit_label
    return f"{st.output_tag(state)}, {limit_label}"


def _fit_saved_pdf(out: Path, limit: int) -> str:
    """Shrink a saved PDF under `limit` bytes (target.fit_pdf); the note
    for the toast."""
    from ..handlers.target import fit_pdf, result_label, size_label

    size = out.stat().st_size
    if size <= limit:
        return result_label(size)
    fit = fit_pdf(out, limit)
    if len(fit["data"]) < size:
        out.write_bytes(fit["data"])
        size = len(fit["data"])
    if fit["fits"]:
        return result_label(size)
    return f"smallest possible: {result_label(size, up=True)}, over {size_label(limit)}"


def _location_choice(state: dict, options: dict | None) -> dict:
    """Metadata changes for an edited copy: the location is left out
    unless "Keep location" was ticked or a location was set in Info."""
    changes = st.meta(state)
    if (options or {}).get("keep_location") or "gps" in changes["set"]:
        return changes
    return {**changes, "drop": sorted({*changes["drop"], "gps"})}


class PdfDocument:
    kind = filetypes.PDF

    def __init__(self, path: Path) -> None:
        from ..handlers.pdf import _open

        self.path = path
        with LOCK:
            try:
                self._doc = _open(path)
            except HandlerError as exc:
                raise OpenError(str(exc)) from None
            self._sizes = [(p.rect.width, p.rect.height) for p in self._doc]
        self._thumbs: dict[int, QImage] = {}
        self._meta = None
        self.last_note = ""

    def metadata(self):
        """What the file carries (metadata.PdfMeta), read on first use."""
        from .metadata import PdfMeta

        with LOCK:
            if self._meta is None:
                self._meta = PdfMeta.read(self._doc, self.path)
            return self._meta

    @property
    def page_count(self) -> int:
        return len(self._sizes)

    def page_size(self, index: int) -> tuple[float, float]:
        """Size as displayed with the page's own rotation, in points."""
        return self._sizes[index]

    def initial_state(self) -> dict:
        return st.new_pdf_state(self.page_count)

    # ---- what the canvas shows ----

    def render_page(self, index: int, width: int) -> QImage:
        import pymupdf

        w_pt, h_pt = self._sizes[index]
        width = max(16, width)
        zoom = width / w_pt
        if width * h_pt * zoom > MAX_RENDER_PIXELS:
            zoom = (MAX_RENDER_PIXELS / (w_pt * h_pt)) ** 0.5
        with LOCK:
            pix = self._doc[index].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False, annots=True)
            image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888).copy()
        return image

    def thumbnail(self, index: int) -> QImage:
        if index not in self._thumbs:
            w_pt, h_pt = self._sizes[index]
            self._thumbs[index] = self.render_page(index, max(16, round(THUMB_HEIGHT * w_pt / h_pt)))
        return self._thumbs[index]

    # ---- saving ----

    def save(self, state: dict, options: dict | None = None) -> Path:
        import pymupdf

        from ..handlers.metadata import PDF_PARTS, clean_pdf
        from . import marks
        from .metadata import PdfMeta

        options = options or {}
        pages = state["pages"]
        keep = [i for i, p in enumerate(pages) if not p["deleted"]]
        if not keep:
            raise OpenError("Can't delete every page")
        redacted = st.has_redactions(state)
        removed: set[str] = set()  # text that was under redaction boxes
        ctx = Context(self.path)
        try:
            with LOCK:
                doc = pymupdf.open(self.path)
                try:
                    for i, change in enumerate(pages):
                        if change["deleted"]:
                            continue
                        page = doc[i]
                        # Marks are in the page as displayed with its own
                        # rotation: place them before the user's rotation.
                        removed |= marks.redact_pdf_page(page, change["redactions"])
                        if options.get("flatten"):
                            marks.draw_pdf_page(page, change["marks"])
                        else:
                            marks.annotate_pdf_page(page, change["marks"])
                        if change["rot"]:
                            page.set_rotation((page.rotation + change["rot"]) % 360)
                        if change["crop"] is not None:
                            _set_crop(doc, page, change["crop"])
                    if len(keep) < len(pages):
                        doc.select(keep)
                    if redacted:
                        marks.redact_titles(doc, removed)
                        clean_pdf(doc, set(PDF_PARTS))
                    elif st.meta_changed(state):
                        PdfMeta.apply(doc, st.meta(state))
                    limit = options.get("limit")
                    tag = _limited_tag(state, _size_label(limit)) if limit else st.output_tag(state)
                    out = ctx.output_file(".pdf", tag=tag)
                    doc.save(out, garbage=4 if redacted else 3, deflate=True, clean=redacted)
                finally:
                    doc.close()
                self.last_note = ""
                if limit:
                    self.last_note = _fit_saved_pdf(out, int(limit))
            [saved] = ctx.commit()
            return saved
        except BaseException:
            ctx.discard()
            raise

    def close(self) -> None:
        with LOCK:
            self._doc.close()


def _set_crop(doc, page, crop: list) -> None:
    """Set the crop box from a crop that is normalized in the page as
    displayed (with its /Rotate applied, y down)."""
    from .marks import pdf_point, visible_box

    x0, y0, x1, y1 = visible_box(page)
    w, h = x1 - x0, y1 - y0
    disp_w, disp_h = (h, w) if page.rotation % 360 in (90, 270) else (w, h)
    cx, cy, cw, ch = crop
    ax, ay = pdf_point(page, cx * disp_w, cy * disp_h)
    bx, by = pdf_point(page, (cx + cw) * disp_w, (cy + ch) * disp_h)
    left, right = sorted((ax, bx))
    bottom, top = sorted((ay, by))
    doc.xref_set_key(page.xref, "CropBox", f"[{left:.3f} {bottom:.3f} {right:.3f} {top:.3f}]")
