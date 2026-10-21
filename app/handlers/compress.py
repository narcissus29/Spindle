"""Compress (Actions wedge). Runs in the helper process.

    report.pdf -> report (compressed).pdf
    photo.jpg  -> photo (compressed).jpg

Strength comes from the `compress_preset` setting:

    light     lossless only: PDF fonts subset + objects cleaned and
              recompressed; PNG at maximum zlib level; TIFF as LZW.
              JPG / WEBP can't shrink without re-encoding, so they are skipped.
    balanced  + JPEG photos inside PDFs re-encoded at quality 75 (and
              downsampled above 200 DPI); JPG at 75, WEBP at 80. Lossless
              PDF images (screenshots, diagrams) are left crisp.
    strong    + every PDF image (also lossless ones) at quality 60, above
              120 DPI down to 100; JPG 60, WEBP 65; images capped at 2560 px.

If the result isn't at least 5% smaller it is dropped and the file is
reported "Already compact", so a "compressed" copy is never bigger.

to_target ("50 KB" from the target ring): fits the file under that size
(see target.py) and writes "photo (50 KB).jpg". Images other than JPEG /
WEBP come out as JPG. The pill says "48 KB ✓", or "Smallest: 340 KB" when
the target can't be reached (that smallest copy is still written).
Multi-page TIFFs and animated images are refused (see image._read).
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QImageWriter

from .common import Context, HandlerError, Skip

PRESETS = {
    "light":    {"pdf_images": None, "pdf_lossless": False, "jpeg": None, "webp": None, "max_side": 0},
    "balanced": {"pdf_images": (200, 150, 75), "pdf_lossless": False, "jpeg": 75, "webp": 80, "max_side": 0},
    "strong":   {"pdf_images": (120, 100, 60), "pdf_lossless": True, "jpeg": 60, "webp": 65, "max_side": 2560},
}
MIN_SAVING = 0.05


def compress(path: Path, option: str, ctx: Context) -> None:
    preset = PRESETS.get(ctx.settings.get("compress_preset", "balanced"), PRESETS["balanced"])
    if path.suffix.lower() == ".pdf":
        out = _compress_pdf(path, ctx, preset)
    else:
        out = _compress_image(path, ctx, preset)
    before, after = path.stat().st_size, out.stat().st_size
    if after > before * (1 - MIN_SAVING):
        raise Skip("Already compact")
    ctx.note(f"−{round(100 * (before - after) / before)}%", before=before, after=after)


def to_target(path: Path, option: str, ctx: Context) -> None:
    from . import target as tg

    size = tg.parse_target(option)
    if size is None:
        raise HandlerError(f"Not a size: {option}")
    before = path.stat().st_size
    if before <= size:
        raise Skip(f"Already {tg.result_label(before)} \u2713", target=size, fits=True, after=before)
    details = []
    if path.suffix.lower() == ".pdf":
        result = tg.fit_pdf(path, size, ctx.progress)
        suffix = ".pdf"
        if result["raster"]:
            details.append("pages saved as pictures (scanned PDF, no text to lose)")
    else:
        image, suffix, out_fmt, details = _target_image(path)
        result = tg.fit_image(image, out_fmt, size, ctx.progress)
        if (result["width"], result["height"]) != (image.width(), image.height()):
            details.append(f"resized to {result['width']} \u00d7 {result['height']} px")
    data = result["data"]
    if not result["fits"] and len(data) >= before:
        raise Skip(f"Smallest: {tg.result_label(before, up=True)}", target=size, fits=False, after=before)
    out = ctx.output_file(suffix, tag=tg.size_label(size))
    out.write_bytes(data)
    after = len(data)
    note = f"{tg.result_label(after)} \u2713" if result["fits"] else f"Smallest: {tg.result_label(after, up=True)}"
    ctx.note(note, before=before, after=after, target=size, fits=result["fits"], detail=", ".join(details))
    ctx.progress(1.0)


def _target_image(path: Path):
    """(upright image ready to encode, suffix, writer format, notes)."""
    from PyQt6.QtGui import QColor, QPainter

    from .image import _read, has_transparency

    image, _reader, raw_fmt = _read(path)
    fmt = raw_fmt.decode().lower()
    notes = []
    if fmt == "webp":
        return image, ".webp", b"webp", notes
    suffix = path.suffix if fmt in ("jpeg", "jpg") else ".jpg"
    if fmt not in ("jpeg", "jpg"):
        notes.append("saved as JPG")
    if image.hasAlphaChannel():
        if has_transparency(image):
            flat = QImage(image.size(), QImage.Format.Format_RGB32)
            flat.setColorSpace(image.colorSpace())
            flat.fill(QColor("white"))
            p = QPainter(flat)
            p.drawImage(0, 0, image)
            p.end()
            image = flat
            notes.append("transparent areas made white")
        else:
            image = image.convertToFormat(QImage.Format.Format_RGB32)
    return image, suffix, b"jpeg", notes


def _compress_pdf(path: Path, ctx: Context, preset: dict) -> Path:
    from .pdf import _open

    with _open(path) as doc:
        if preset["pdf_images"]:
            threshold, target, quality = preset["pdf_images"]
            doc.rewrite_images(dpi_threshold=threshold, dpi_target=target, quality=quality,
                               lossy=True, lossless=preset["pdf_lossless"], bitonal=False)
        ctx.progress(0.5)
        try:
            doc.subset_fonts()
        except Exception:  # unusual fonts: keep them whole rather than fail
            pass
        ctx.progress(0.7)
        out = ctx.output_file(".pdf", tag="compressed")
        doc.save(out, garbage=4, deflate=True, deflate_images=True, deflate_fonts=True,
                 clean=True, use_objstms=1)
    ctx.progress(1.0)
    return out


def _compress_image(path: Path, ctx: Context, preset: dict) -> Path:
    from .image import _read, has_transparency

    image, _reader, raw_fmt = _read(path)
    fmt = raw_fmt.decode().lower()
    if preset["max_side"] and max(image.width(), image.height()) > preset["max_side"]:
        side = preset["max_side"]
        image = image.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)

    if fmt in ("jpeg", "jpg"):
        if preset["jpeg"] is None:
            raise Skip("Already compact")
        out = ctx.output_file(path.suffix, tag="compressed")
        _write(out, image, b"jpeg", quality=preset["jpeg"], optimize=True)
    elif fmt == "heic":  # never written: a JPG copy (usually bigger: "Already compact")
        out = ctx.output_file(".jpg", tag="compressed")
        _write(out, _opaque(image), b"jpeg", quality=preset["jpeg"] or 90, optimize=True)
    elif fmt == "webp":
        if preset["webp"] is None:
            raise Skip("Already compact")
        out = ctx.output_file(".webp", tag="compressed")
        _write(out, image, b"webp", quality=preset["webp"])
    elif fmt in ("png", "bmp"):
        # BMP has no compression at all: it becomes a (lossless) PNG.
        if image.hasAlphaChannel() and not has_transparency(image):
            image = image.convertToFormat(QImage.Format.Format_RGB32)  # RGB is smaller than RGBA
        out = ctx.output_file(".png", tag="compressed")
        _write(out, image, b"png", quality=0)  # Qt: PNG quality 0 = maximum compression
    elif fmt in ("tiff", "tif"):
        out = ctx.output_file(path.suffix, tag="compressed")
        _write(out, image, b"tiff", compression=1)  # LZW, lossless
    else:  # GIF: Qt can't write it
        raise Skip("Already compact")
    ctx.progress(1.0)
    return out


def _opaque(image: QImage) -> QImage:
    from .image import _flatten

    return _flatten(image) if image.hasAlphaChannel() else image


def _write(out: Path, image: QImage, fmt: bytes, quality: int | None = None,
           compression: int | None = None, optimize: bool = False) -> None:
    writer = QImageWriter(str(out), fmt)
    if quality is not None:
        writer.setQuality(quality)
    if compression is not None:
        writer.setCompression(compression)
    if optimize:
        writer.setOptimizedWrite(True)
    if not writer.write(image):
        raise HandlerError(f"Can't write {fmt.decode().upper()} ({writer.errorString()})")
