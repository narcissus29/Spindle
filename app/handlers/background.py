"""Add BG (Actions wedge): a solid color behind transparent areas.
Runs in the helper process. Images only (the wedge is hidden for PDFs).

    logo.png -> logo (bg).png      color from the `background_color` setting

Images without any transparent pixel are skipped ("No transparency"), and
no file is written. The output keeps the source format (PNG, WEBP, TIFF);
GIF, which Qt can't write, becomes PNG. Multi-page TIFFs and animated
images are refused (see image._read).
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtGui import QColor, QImageReader, QImageWriter

from .common import Context, HandlerError, Skip
from .image import _flatten, _read, has_transparency

_OPAQUE_FORMATS = {b"jpeg", b"jpg", b"bmp"}
_WRITE = {b"png": (b"png", ".png"), b"webp": (b"webp", ".webp"), b"tiff": (b"tiff", None), b"tif": (b"tiff", None)}


def add_bg(path: Path, option: str, ctx: Context) -> None:
    fmt = bytes(QImageReader(str(path)).format())
    if fmt in _OPAQUE_FORMATS:  # these can't hold transparency: no need to decode
        raise Skip("No transparency")
    image, _reader, _fmt = _read(path)
    if not has_transparency(image):
        raise Skip("No transparency")
    color = QColor(ctx.settings.get("background_color", "#ffffff"))
    flat = _flatten(image, color)
    out_fmt, ext = _WRITE.get(fmt, (b"png", ".png"))
    out = ctx.output_file(ext or path.suffix, tag="bg")
    writer = QImageWriter(str(out), out_fmt)
    if out_fmt == b"webp":
        writer.setQuality(100)  # don't add compression loss on top
    if out_fmt == b"tiff":
        writer.setCompression(1)
    if out_fmt == b"png":
        writer.setQuality(0)
    if not writer.write(flat):
        raise HandlerError(f"Can't write {out_fmt.decode().upper()} ({writer.errorString()})")
    ctx.progress(1.0)
