"""Fit a file under a target size ("compress to 50 KB"). Runs in the
helper process (and later the editor's save, so no UI imports here).

Sizes: "KB" is 1000 bytes. A file under 50,000 bytes is also under 51,200,
so it passes forms that count either way.

Images (fit_image): everything happens in memory; only the result is
written.
1. Quality first: the highest JPEG / WEBP quality between Q_MIN and Q_MAX
   that fits, at full size.
2. Below Q_MIN a smaller picture looks better than a blocky one: the size
   at quality 75 tells how much to shrink, then the scale is narrowed down
   (bisection) to the largest one that fits, each with its best quality.
3. Can't fit even at MIN_SIDE px and quality 10: the smallest result is
   returned with fits=False ("Smallest: 3 KB"), never claimed as a fit.

PDFs (fit_pdf): a ladder of steps, gentlest first, each applied to a fresh
copy of the original: lossless clean-up, then image downsampling / JPEG
quality, then also re-encoding lossless images. A PDF with no text layer
at all (a scan) can also have its pages rasterized as a last resort,
which loses nothing there. Pages with real text are never rasterized.
The strongest step is tried first: if even that doesn't fit, it is the
smallest possible result; otherwise the gentlest fitting step is found by
bisection.
"""

from __future__ import annotations

import math
import re

KB = 1000
Q_MIN, Q_MAX = 50, 95
Q_FLOOR = 10       # last resort, at the smallest size
MIN_SIDE = 16      # px: never shrink below this


# ------------------------------------------------------------------ sizes ---

def parse_target(text: str) -> int | None:
    """"50 KB" -> 50000, "1 MB" / "1.5mb" -> bytes, "75" -> 75 KB.
    None if it isn't a usable size (under 1 KB or over 100 MB)."""
    m = re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*(kb|k|mb|m)?\s*", text.lower())
    if not m:
        return None
    value = float(m[1].replace(",", "."))
    unit = 1_000_000 if (m[2] or "kb").startswith("m") else KB
    size = round(value * unit)
    return size if KB <= size <= 100_000_000 else None


def size_label(n: int) -> str:
    """50000 -> "50 KB", 1000000 -> "1 MB", 1500000 -> "1.5 MB"."""
    if n >= 1_000_000:
        mb = n / 1_000_000
        return f"{mb:.1f} MB".replace(".0 MB", " MB")
    return f"{max(1, math.floor(n / KB))} KB" if n >= KB else f"{n} bytes"


def result_label(n: int, up: bool = False) -> str:
    """A result size. Rounded down for a fit (49,700 bytes is "49 KB",
    never "50 KB" next to a 50 KB target), up for "Smallest: ..." (so it
    never looks smaller than it is)."""
    rnd = math.ceil if up else math.floor
    if n >= 1_000_000:
        return f"{rnd(n / 10_000) / 100:.2f} MB"
    if n >= 10 * KB:
        return f"{rnd(n / KB)} KB"
    return f"{rnd(n / 100) / 10:.1f} KB"


# ----------------------------------------------------------------- images ---

def encode(image, fmt: bytes, quality: int) -> bytes:
    """`image` (QImage) as JPEG / WEBP bytes, in memory. JPEG is baseline
    with optimized coding: some old upload forms reject progressive JPEGs."""
    from PyQt6.QtCore import QBuffer, QByteArray, QIODevice
    from PyQt6.QtGui import QImageWriter

    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    writer = QImageWriter(buf, fmt)
    writer.setQuality(quality)
    if fmt == b"jpeg":
        writer.setOptimizedWrite(True)
    if not writer.write(image):
        raise RuntimeError(f"can't encode {fmt.decode()} ({writer.errorString()})")
    buf.close()
    return bytes(data)


def _best_quality(image, fmt: bytes, target: int, lo: int = Q_MIN, hi: int = Q_MAX):
    """(bytes, quality) for the highest quality in lo..hi that fits, or
    (smallest bytes, lo) with fits False."""
    smallest = encode(image, fmt, lo)
    if len(smallest) > target:
        return smallest, lo, False
    best, best_q = smallest, lo
    while lo < hi:
        mid = (lo + hi + 1) // 2
        data = encode(image, fmt, mid)
        if len(data) <= target:
            best, best_q, lo = data, mid, mid
        else:
            hi = mid - 1
    return best, best_q, True


def _scaled(image, scale: float):
    from PyQt6.QtCore import Qt

    w = max(1, round(image.width() * scale))
    h = max(1, round(image.height() * scale))
    return image.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)


def fit_image(image, fmt: bytes, target: int, progress=None) -> dict:
    """Best encoding of `image` (QImage, upright, no alpha for JPEG) that
    is at most `target` bytes. Returns {"data", "fits", "quality",
    "width", "height"}."""
    def report(f):
        if progress:
            progress(f)

    data, q, fits = _best_quality(image, fmt, target)
    if fits:
        return {"data": data, "fits": True, "quality": q, "width": image.width(), "height": image.height()}
    report(0.3)
    side = max(image.width(), image.height())
    min_scale = min(1.0, MIN_SIDE / side)
    # First guess from the size at quality 75: bytes grow with the pixel count.
    probe = encode(image, fmt, 75)
    hi = 1.0                                   # known not to fit
    lo = max(min_scale, min(0.95, math.sqrt(target / len(probe)) * 0.95))
    found = None
    for _ in range(12):                        # find a scale that fits
        img = _scaled(image, lo)
        data, q, fits = _best_quality(img, fmt, target)
        if fits:
            found = (lo, data, q, img)
            break
        hi = lo
        if lo <= min_scale:
            break
        lo = max(min_scale, lo * min(0.85, math.sqrt(target / len(data)) * 0.97))
    report(0.6)
    if found is None:
        # Not even at the smallest size and Q_MIN: lower the quality there.
        img = _scaled(image, min_scale)
        data, q, fits = _best_quality(img, fmt, target, lo=Q_FLOOR, hi=Q_MIN)
        return {"data": data, "fits": fits, "quality": q, "width": img.width(), "height": img.height()}
    # Narrow down to the largest scale that fits (closest to the target).
    for _ in range(5):
        if hi - found[0] < 0.02 * hi or len(found[1]) >= 0.96 * target:
            break  # close enough: another step changes little
        mid = (found[0] + hi) / 2
        img = _scaled(image, mid)
        data, q, fits = _best_quality(img, fmt, target)
        if fits:
            found = (mid, data, q, img)
        else:
            hi = mid
    report(0.9)
    _scale, data, q, img = found
    return {"data": data, "fits": True, "quality": q, "width": img.width(), "height": img.height()}


# ------------------------------------------------------------------- PDFs ---

# (dpi target, JPEG quality, also re-encode lossless images); None = lossless only
PDF_LADDER = [None, (150, 75, False), (120, 65, False), (100, 55, False), (100, 50, True),
              (85, 45, True), (72, 40, True), (60, 30, True), (50, 25, True)]
# Scans only (no text layer): pages become JPEG pictures.
RASTER_LADDER = [(150, 60), (120, 50), (100, 45), (85, 40), (72, 35), (60, 30), (50, 25)]


def has_text_layer(doc) -> bool:
    """Any page with extractable text (real text, or an OCR layer)."""
    return any(page.get_text("text").strip() for page in doc)


def _pdf_step(path, step) -> bytes:
    from .pdf import _open

    with _open(path) as doc:
        if step is not None:
            dpi, quality, lossless = step
            doc.rewrite_images(dpi_threshold=dpi + 10, dpi_target=dpi, quality=quality,
                               lossy=True, lossless=lossless, bitonal=False)
        try:
            doc.subset_fonts()
        except Exception:  # unusual fonts: keep them whole rather than fail
            pass
        return doc.tobytes(garbage=4, deflate=True, deflate_images=True, deflate_fonts=True,
                           clean=True, use_objstms=1)


def _raster_step(path, step) -> bytes:
    """Every page as one JPEG picture (scans only). Gray pages are stored
    as grayscale, a third of the size."""
    import pymupdf

    from .pdf import _open

    dpi, quality = step
    out = pymupdf.open()
    with _open(path) as doc:
        for page in doc:
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            if pix.n >= 3 and _is_gray(pix):
                pix = pymupdf.Pixmap(pymupdf.csGRAY, pix)
            new = out.new_page(width=page.rect.width, height=page.rect.height)
            new.insert_image(new.rect, stream=pix.tobytes("jpeg", jpg_quality=quality))
    data = out.tobytes(garbage=4, deflate=True)
    out.close()
    return data


def _is_gray(pix) -> bool:
    import numpy as np

    a = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[::7, ::7, :3].astype(np.int16)
    return bool(np.abs(a[..., 0] - a[..., 1]).max() <= 12 and np.abs(a[..., 1] - a[..., 2]).max() <= 12)


def fit_pdf(path, target: int, progress=None) -> dict:
    """{"data", "fits", "step", "raster"} for the gentlest step that fits,
    or the smallest one with fits False."""
    from .pdf import _open

    with _open(path) as doc:
        scan = not has_text_layer(doc)
    steps = [(_pdf_step, s) for s in PDF_LADDER]
    if scan:
        steps += [(_raster_step, s) for s in RASTER_LADDER]
    tried: dict[int, bytes] = {}

    def size_at(i: int) -> int:
        if i not in tried:
            fn, step = steps[i]
            tried[i] = fn(path, step)
            if progress:
                progress(min(0.95, 0.1 + 0.15 * len(tried)))
        return len(tried[i])

    last = len(steps) - 1
    if size_at(0) <= target:
        best = 0
    elif size_at(last) > target:
        smallest = min(tried, key=lambda i: len(tried[i]))
        return {"data": tried[smallest], "fits": False, "step": smallest, "raster": steps[smallest][0] is _raster_step}
    else:
        lo, hi = 0, last          # lo doesn't fit, hi fits
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if size_at(mid) <= target:
                hi = mid
            else:
                lo = mid
        best = hi
    return {"data": tried[best], "fits": True, "step": best, "raster": steps[best][0] is _raster_step}
