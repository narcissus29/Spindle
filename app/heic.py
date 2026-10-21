"""HEIC / HEIF photos (iPhones save these): decoded with pi-heif, the
decode-only build of libheif. Spindle never writes HEIC: anything made
from one comes out as JPG (or the format chosen in Convert).

Imported only where a HEIC is actually read (helper, editor), never by
the wheel. The picture comes out upright (HEIF stores rotation as part of
the image, and the decoder applies it), with its color profile (iPhones
use Display P3) attached so converted copies keep their colors.
"""

from __future__ import annotations

from pathlib import Path

# ftyp brands of HEVC-coded HEIF files. (AVIF uses the same container
# with other brands and isn't handled.)
_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis"}
_GENERIC = {b"mif1", b"msf1"}


def is_heic(head: bytes) -> bool:
    """From the first bytes of a file."""
    if head[4:8] != b"ftyp" or len(head) < 16:
        return False
    size = int.from_bytes(head[:4], "big")
    brands = {head[8:12]} | {head[i:i + 4] for i in range(16, min(size, len(head)) - 3, 4)}
    if brands & _BRANDS:
        return True
    return bool(brands & _GENERIC) and b"avif" not in brands and b"avis" not in brands


class HeicError(Exception):
    """The file can't be used; the message says why."""


def _open(path: Path):
    try:
        import pi_heif
    except ImportError:
        raise HeicError("HEIC support is missing") from None
    try:
        heif = pi_heif.open_heif(str(path), convert_hdr_to_8bit=True)
    except Exception as exc:  # damaged file, unsupported coding
        raise HeicError(f"Can't read HEIC ({exc})") from None
    if len(heif) > 1:
        raise HeicError("Multi-image HEIC not supported")
    return heif


def read(path: Path, max_side: int = 0):
    """The photo as a QImage (upright, color profile attached). With
    `max_side`, scaled down to fit it."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QImage

    heif = _open(path)
    try:
        pil = heif.to_pillow() if hasattr(heif, "to_pillow") else heif[0].to_pillow()
    except Exception as exc:
        raise HeicError(f"Can't read HEIC ({exc})") from None
    alpha = "A" in pil.getbands()
    pil = pil.convert("RGBA" if alpha else "RGB")
    fmt = QImage.Format.Format_RGBA8888 if alpha else QImage.Format.Format_RGB888
    data = pil.tobytes()
    image = QImage(data, pil.width, pil.height, pil.width * (4 if alpha else 3), fmt).copy()
    image = image.convertToFormat(QImage.Format.Format_ARGB32 if alpha else QImage.Format.Format_RGB32)
    space = _color_space(heif.info)
    if space is not None:
        image.setColorSpace(space)
    if max_side and max(image.width(), image.height()) > max_side:
        image = image.scaled(max_side, max_side, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
    return image


def _color_space(info: dict):
    from PyQt6.QtGui import QColorSpace

    icc = info.get("icc_profile")
    if icc:
        space = QColorSpace.fromIccProfile(bytes(icc))
        if space.isValid():
            return space
    nclx = info.get("nclx_profile") or {}
    primaries = nclx.get("color_primaries") if isinstance(nclx, dict) else None
    if primaries == 12:  # SMPTE EG 432-1: Display P3
        return QColorSpace(QColorSpace.NamedColorSpace.DisplayP3)
    return None


def size(path: Path) -> tuple[int, int]:
    """Width, height as shown (upright)."""
    heif = _open(path)
    return heif.size


def exif(path: Path) -> bytes | None:
    """The EXIF block as TIFF data (no "Exif" prefix), or None."""
    data = _open(path).info.get("exif")
    if not data:
        return None
    data = bytes(data)
    if data.startswith(b"Exif\x00\x00"):
        data = data[6:]
    return data if data[:4] in (b"II*\x00", b"MM\x00*") else None


def xmp(path: Path) -> bytes | None:
    data = _open(path).info.get("xmp")
    return bytes(data) if data else None
