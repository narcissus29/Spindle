"""Pixel operations used both for the saved file and for the preview.

Brightness / contrast / saturation use exactly the math of Qt's
MultiEffect shader, which draws the live preview on the GPU. That way the
saved file looks like what was on screen (tests check they agree within
one 8-bit step). On the software renderer, which can't run shaders, the
preview is made with these same functions on a screen-sized copy.

Per pixel, in 0..1 (straight alpha):
    x    = (x - 0.5) * (1 + contrast) + 0.5 + brightness
    gray = 0.299 r + 0.587 g + 0.114 b               (of the new x)
    x    = gray + (x - gray) * (1 + saturation)
    clamp to 0..1
All of it is linear, so it folds into one 3x3 matrix plus an offset.
"""

from __future__ import annotations

import numpy as np
from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QImage, QTransform

_LUMA = np.array([0.299, 0.587, 0.114], dtype=np.float32)
_STRIPE = 512  # rows per chunk on full-size images: bounds the float copies


def adjust_matrix(adjust: dict) -> tuple[np.ndarray, np.ndarray]:
    """(M, o) so that out = M @ rgb + o, rgb in 0..255."""
    c = 1.0 + float(adjust.get("contrast", 0.0))
    b = float(adjust.get("brightness", 0.0))
    s = 1.0 + float(adjust.get("saturation", 0.0))
    # contrast + brightness: x' = c x + k, with k in 0..255 units
    k = (0.5 - 0.5 * c + b) * 255.0
    # saturation: x'' = s x' + (1 - s) * luma(x')
    sat = s * np.eye(3, dtype=np.float32) + (1.0 - s) * np.outer(np.ones(3, dtype=np.float32), _LUMA)
    m = (sat * c).astype(np.float32)
    o = (sat @ np.full(3, k, dtype=np.float32)).astype(np.float32)
    return m, o


def is_neutral(adjust: dict) -> bool:
    return all(abs(float(adjust.get(k, 0.0))) < 1e-6 for k in ("brightness", "contrast", "saturation"))


def apply_adjust(image: QImage, adjust: dict) -> QImage:
    """A copy of `image` with brightness / contrast / saturation applied.
    Alpha is left as it is."""
    if is_neutral(adjust):
        return image
    has_alpha = image.hasAlphaChannel()
    src = image.convertToFormat(QImage.Format.Format_RGBA8888 if has_alpha else QImage.Format.Format_RGBX8888)
    out = QImage(src.size(), src.format())
    out.setColorSpace(image.colorSpace())
    out.setDotsPerMeterX(image.dotsPerMeterX())
    out.setDotsPerMeterY(image.dotsPerMeterY())
    m, o = adjust_matrix(adjust)
    mt = np.ascontiguousarray(m.T)
    width, height = src.width(), src.height()
    a_in = _view(src)
    a_out = _view(out, writable=True)
    for y0 in range(0, height, _STRIPE):
        rows = a_in[y0:y0 + _STRIPE, :width]
        rgb = rows[..., :3].reshape(-1, 3).astype(np.float32)
        rgb = rgb @ mt
        rgb += o
        np.clip(rgb, 0, 255, out=rgb)
        np.rint(rgb, out=rgb)
        dest = a_out[y0:y0 + _STRIPE, :width]
        dest[..., :3] = rgb.reshape(rows.shape[0], width, 3).astype(np.uint8)
        dest[..., 3] = rows[..., 3]
    return out


def _view(image: QImage, writable: bool = False) -> np.ndarray:
    """The pixels of a 4-byte-per-pixel QImage as an (h, w, 4) array, with
    no copy. Rows may be padded: callers slice [:, :width]."""
    ptr = image.bits() if writable else image.constBits()  # bits(): writable, aliases the image
    ptr.setsize(image.sizeInBytes())
    return np.frombuffer(ptr, dtype=np.uint8).reshape(image.height(), image.bytesPerLine() // 4, 4)


def orient(image: QImage, rot: int, mirror: bool) -> QImage:
    """Mirror left-right first (if asked), then rotate clockwise by `rot`
    (a multiple of 90: exact, no resampling)."""
    if mirror:
        if hasattr(image, "flipped"):  # Qt >= 6.9
            image = image.flipped(Qt.Orientation.Horizontal)
        else:
            image = image.mirrored(True, False)
    if rot % 360:
        image = image.transformed(QTransform().rotate(rot % 360))
    return image


def crop_pixels(width: int, height: int, rect: list | None) -> QRect:
    """The normalized crop as whole pixels of a width x height image."""
    if rect is None:
        return QRect(0, 0, width, height)
    x, y, w, h = rect
    x0 = min(max(round(x * width), 0), width - 1)
    y0 = min(max(round(y * height), 0), height - 1)
    x1 = min(max(round((x + w) * width), x0 + 1), width)
    y1 = min(max(round((y + h) * height), y0 + 1), height)
    return QRect(x0, y0, x1 - x0, y1 - y0)


def render_image(image: QImage, state: dict, unit_scale: float = 1.0) -> QImage:
    """Everything in an image state applied to `image`: orientation, the
    color adjustments, then marks and redaction boxes drawn on top (so the
    adjustments never lighten a black box), then the crop, then the exact
    output size if one is set.

    Marks are in full-size pixels; `unit_scale` is pixels of `image` per
    full-size pixel (for a smaller preview copy)."""
    from . import marks

    width, height = image.width(), image.height()
    image = orient(image, state["rot"], state["mirror"])
    image = apply_adjust(image, state["adjust"])
    transform = QTransform.fromScale(unit_scale, unit_scale) * marks.orient_transform(
        width, height, state["rot"], state["mirror"])
    image = marks.burn_in(image, state.get("marks", []), state.get("redactions", []), transform,
                          state["rot"], state["mirror"])
    if state["crop"] is not None:
        image = image.copy(crop_pixels(image.width(), image.height(), state["crop"]))
    size = state.get("size")
    if size:  # "Exact size": the crop has that shape, so this only scales
        image = image.scaled(int(size[0]), int(size[1]), Qt.AspectRatioMode.IgnoreAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
    return image


def without_text(image: QImage) -> QImage:
    """The same pixels with none of the text Qt carries along from the
    source file (PNG text chunks, JPEG comments), which its writers would
    otherwise put back into the saved file. The color profile stays."""
    clean = QImage(image.size(), image.format())
    clean.setColorSpace(image.colorSpace())
    clean.setDotsPerMeterX(image.dotsPerMeterX())
    clean.setDotsPerMeterY(image.dotsPerMeterY())
    if image.colorTable():
        clean.setColorTable(image.colorTable())
    src, dst = image.constBits(), clean.bits()
    src.setsize(image.sizeInBytes())
    dst.setsize(clean.sizeInBytes())
    dst[:] = src
    return clean
