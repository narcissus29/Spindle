"""Image handlers. Imported only inside the helper process.

    convert  image -> PNG / JPG / WEBP / BMP / TIFF with Qt's image writer
             (no extra dependency), or -> PDF with PyMuPDF.

EXIF orientation is applied (phone photos come out upright). Formats
without transparency (JPG, BMP) get transparent areas filled with white.
Multi-page TIFFs become one page each in a PDF; to any other format they
are refused, as are animated GIF / WEBP / PNG: Qt decodes only the first
frame, and pages must never be dropped silently.

HEIC (iPhone photos) is read with pi-heif (app/heic.py); `_read` returns
it with no reader and the format b"heic". Spindle never writes HEIC.

Images put into a PDF carry no metadata: EXIF (GPS, camera), XMP,
comments and data after the image (a motion photo's video) are cut out of
the embedded bytes losslessly (metadata.strip_jpeg / strip_png). JPEGs and
PNGs that need no rotation go in as they are otherwise, so no quality is
lost.
"""

from __future__ import annotations

from pathlib import Path
from struct import error as struct_error

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice
from PyQt6.QtGui import QColor, QImage, QImageIOHandler, QImageReader, QImageWriter, QPainter

from .common import Context, HandlerError, Skip

# option -> (Qt format, extension)
_TARGETS = {
    "PNG": ("png", ".png"),
    "JPG": ("jpeg", ".jpg"),
    "WEBP": ("webp", ".webp"),
    "BMP": ("bmp", ".bmp"),
    "TIFF": ("tiff", ".tiff"),
}
_NO_ALPHA = {"jpeg", "bmp"}
_LOSSY_SOURCES = {b"jpeg", b"jpg", b"webp", b"heic"}

QImageReader.setAllocationLimit(1024)  # MB; Qt's default 256 refuses big scans


def _read(path: Path) -> tuple[QImage, QImageReader | None, bytes]:
    """(image with EXIF orientation applied, its reader, its format such as
    b"jpeg"). The format is taken before decoding: Qt reports an empty one
    afterwards. HEIC: (image, None, b"heic")."""
    if not path.exists():
        raise HandlerError("File not found")
    from ..filetypes import is_heic_file

    if is_heic_file(path):
        from .. import heic

        try:
            return heic.read(path), None, b"heic"
        except heic.HeicError as exc:
            if "Multi-image" in str(exc):
                raise Skip(str(exc)) from None
            raise HandlerError(str(exc)) from None
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)  # EXIF orientation
    fmt = bytes(reader.format())
    if problem := frame_problem(path, reader, fmt):
        raise Skip(problem)
    image = reader.read()
    if image.isNull():
        raise HandlerError(f"Can't read image ({reader.errorString()})")
    return image, reader, fmt


_MULTI_FRAME = {
    b"tiff": "Multi-page TIFF not supported",
    b"tif": "Multi-page TIFF not supported",
    b"gif": "Animated GIF not supported",
    b"webp": "Animated WEBP not supported",
    b"png": "Animated PNG not supported",
}


def frame_problem(path: Path, reader: QImageReader, fmt: bytes) -> str | None:
    """Why this image can't be handled as one picture ("Multi-page TIFF
    not supported"), or None. Checked before decoding."""
    if reader.imageCount() > 1 or (fmt == b"png" and _is_apng(path)):
        return _MULTI_FRAME.get(fmt, "Multi-frame image not supported")
    return None


def _is_apng(path: Path) -> bool:
    """An animated PNG has an acTL chunk before its image data (Qt shows
    only the first frame and reports a frame count of 1)."""
    import struct

    with path.open("rb") as f:
        f.seek(8)
        while head := f.read(8):
            if len(head) < 8:
                return False
            length, ctype = struct.unpack(">I", head[:4])[0], head[4:]
            if ctype == b"acTL":
                return True
            if ctype in (b"IDAT", b"IEND"):
                return False
            f.seek(length + 4, 1)
    return False


def has_transparency(image: QImage) -> bool:
    """True if any pixel is not fully opaque (an alpha channel alone isn't
    enough: many PNGs carry one that is 255 everywhere)."""
    if not image.hasAlphaChannel():
        return False
    alpha = image.convertToFormat(QImage.Format.Format_Alpha8)
    ptr = alpha.constBits()
    ptr.setsize(alpha.sizeInBytes())
    data = bytes(ptr)
    stride, width = alpha.bytesPerLine(), alpha.width()
    # min() over each row runs in C; rows skip the stride padding bytes.
    return any(min(data[y * stride:y * stride + width]) < 255 for y in range(alpha.height()))


def _flatten(image: QImage, color: QColor | None = None) -> QImage:
    if not image.hasAlphaChannel():
        return image
    flat = QImage(image.size(), QImage.Format.Format_RGB32)
    flat.setDotsPerMeterX(image.dotsPerMeterX())
    flat.setDotsPerMeterY(image.dotsPerMeterY())
    flat.fill(color or QColor("white"))
    painter = QPainter(flat)
    painter.drawImage(0, 0, image)
    painter.end()
    return flat


def convert(path: Path, option: str, ctx: Context) -> None:
    if option == "PDF":
        _to_pdf(path, ctx)
        return
    fmt, ext = _TARGETS[option]
    if tiff_pages(path) > 1:
        raise Skip("Multi-page TIFF: convert to PDF to keep every page")
    image, _reader, _fmt = _read(path)
    if fmt in _NO_ALPHA:
        image = _flatten(image)
    out = ctx.output_file(ext)
    writer = QImageWriter(str(out), fmt.encode())
    if fmt in ("jpeg", "webp"):
        writer.setQuality(int(ctx.settings.get("jpeg_quality", 90)))
    if fmt == "tiff":
        writer.setCompression(1)  # LZW
    if not writer.write(image):
        raise HandlerError(f"Can't write {option} ({writer.errorString()})")
    ctx.progress(1.0)


def _to_pdf(path: Path, ctx: Context) -> None:
    import pymupdf

    doc = pymupdf.open()
    add_pdf_pages(doc, path, ctx, on_page=lambda i, n: ctx.progress(0.9 * i / n))
    out = ctx.output_file(".pdf")
    doc.save(out, garbage=3, deflate=True)
    doc.close()
    ctx.progress(1.0)


def tiff_pages(path: Path) -> int:
    """Number of pages of a TIFF (0 for anything else)."""
    reader = QImageReader(str(path))
    if bytes(reader.format()) not in (b"tiff", b"tif"):
        return 0
    return max(1, reader.imageCount())


def add_pdf_pages(doc, path: Path, ctx: Context, on_page=None) -> int:
    """Append the image at `path` as a page sized to the image (every page
    of a multi-page TIFF), with no metadata in the embedded bytes. Returns
    the number of pages added. `on_page(done, total)` reports progress."""
    pages = tiff_pages(path)
    if pages > 1:
        reader = QImageReader(str(path))
        for i in range(pages):
            if not reader.jumpToImage(i):
                raise HandlerError(f"Can't read TIFF page {i + 1}")
            image = reader.read()
            if image.isNull():
                raise HandlerError(f"Can't read TIFF page {i + 1} ({reader.errorString()})")
            _add_page(doc, image, _encode(image, lossy=False, ctx=ctx))
            if on_page:
                on_page(i + 1, pages)
        return pages

    image, reader, source_fmt = _read(path)
    # Keep the original bytes when they can go in as they are (no re-encode,
    # no quality loss), minus their metadata; otherwise re-encode what Qt
    # decoded (WEBP, rotated photos, BMP/TIFF/GIF).
    rotated = reader is not None and reader.transformation() != QImageIOHandler.Transformation.TransformationNone
    data = None
    if source_fmt in (b"jpeg", b"jpg", b"png") and not rotated:
        data = _clean(path.read_bytes())
    if data is None:
        lossy = source_fmt in _LOSSY_SOURCES and not image.hasAlphaChannel()
        data = _encode(image, lossy, ctx)
    _add_page(doc, image, data)
    if on_page:
        on_page(1, 1)
    return 1


def _encode(image: QImage, lossy: bool, ctx: Context) -> bytes:
    buf = QByteArray()
    device = QBuffer(buf)
    device.open(QIODevice.OpenModeFlag.WriteOnly)
    if lossy:
        image.save(device, b"JPEG", int(ctx.settings.get("jpeg_quality", 90)))
    else:
        image.save(device, b"PNG")
    device.close()
    # Qt writes the image's text (e.g. a JPEG comment it read) back out.
    return _clean(bytes(buf)) or bytes(buf)


def _clean(data: bytes) -> bytes | None:
    """JPEG / PNG bytes without metadata or trailing data, or None if they
    can't be parsed (the caller then re-encodes)."""
    from .metadata import strip_jpeg, strip_png

    try:
        if data.startswith(b"\xff\xd8"):
            return strip_jpeg(data)[0]
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return strip_png(data)[0]
    except (HandlerError, ValueError, IndexError, struct_error):
        return None
    return None


def _add_page(doc, image: QImage, data: bytes) -> None:
    # Page size from the image's own DPI (96 when missing or implausible).
    dpi_x = image.dotsPerMeterX() * 0.0254
    dpi_y = image.dotsPerMeterY() * 0.0254
    dpi_x = dpi_x if 50 <= dpi_x <= 1200 else 96.0
    dpi_y = dpi_y if 50 <= dpi_y <= 1200 else 96.0
    width_pt = image.width() * 72.0 / dpi_x
    height_pt = image.height() * 72.0 / dpi_y

    page = doc.new_page(width=width_pt, height=height_pt)
    page.insert_image(page.rect, stream=data)
