"""File-type detection.

Two levels:
- kind_from_path(): extension only. No disk I/O, so it is safe to call on the
  UI thread during drag-enter (slow or network drives can't stall the wheel).
- sniff_kind(): reads the first bytes of the file to confirm the real type.
  Called from the worker thread right before a handler runs.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from .heic import is_heic

PDF = "pdf"
IMAGE = "image"
DOCUMENT = "document"  # Word / Excel / PowerPoint / OpenDocument (-> PDF with the office app installed)

_EXT_KIND = {
    ".pdf": PDF,
    ".png": IMAGE,
    ".jpg": IMAGE,
    ".jpeg": IMAGE,
    ".webp": IMAGE,
    ".bmp": IMAGE,
    ".gif": IMAGE,
    ".tif": IMAGE,
    ".tiff": IMAGE,
    ".heic": IMAGE,  # iPhone photos (read only; see app/heic.py)
    ".heif": IMAGE,
    **{ext: DOCUMENT for ext in (".docx", ".doc", ".docm", ".rtf", ".odt", ".xlsx", ".xls", ".xlsm", ".ods",
                                 ".pptx", ".ppt", ".pptm", ".odp")},
}

# Extensions that share one display label / target format.
_EXT_LABEL = {
    ".jpeg": "JPG",
    ".tif": "TIFF",
    ".heif": "HEIC",
}


def kind_from_path(path: Path) -> str | None:
    return _EXT_KIND.get(path.suffix.lower())


def format_label(path: Path) -> str:
    ext = path.suffix.lower()
    return _EXT_LABEL.get(ext, ext.lstrip(".").upper())


def sniff_kind(path: Path) -> str | None:
    """Return the kind from the file's magic bytes, or None if unrecognised."""
    with path.open("rb") as fh:
        head = fh.read(1024)

    # PDF readers accept the header anywhere in the first 1 KiB.
    if b"%PDF-" in head:
        return PDF
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return IMAGE
    if head.startswith(b"\xff\xd8\xff"):
        return IMAGE
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return IMAGE
    if head.startswith(b"BM"):
        return IMAGE
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return IMAGE
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return IMAGE
    if is_heic(head):
        return IMAGE
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):  # OLE: .doc / .xls / .ppt (or protected OOXML)
        return DOCUMENT
    if head.startswith(b"{\\rtf"):
        return DOCUMENT
    if head.startswith(b"PK\x03\x04") and _office_zip(path):
        return DOCUMENT
    return None


def _office_zip(path: Path) -> bool:
    """OOXML ([Content_Types].xml) or OpenDocument (a "mimetype" entry)."""
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            if "[Content_Types].xml" in names:
                return True
            return "mimetype" in names and z.read("mimetype").startswith(b"application/vnd.oasis.opendocument")
    except (OSError, zipfile.BadZipFile, KeyError):
        return False


def is_heic_file(path: Path) -> bool:
    with path.open("rb") as fh:
        return is_heic(fh.read(64))
