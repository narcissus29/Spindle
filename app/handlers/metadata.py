"""Metadata (Actions wedge): remove it, for privacy. Runs in the helper.

    photo.jpg  -> photo (clean).jpg
    report.pdf -> report (clean).pdf

Pixels / page content are never touched:
- JPEG: EXIF (GPS, camera, dates), XMP, Photoshop/IPTC and comment blocks
  are cut out of the file byte for byte; the image data is copied as is.
  The ICC color profile and the Adobe block (needed for CMYK) are kept, and
  the orientation is written back alone so photos stay upright.
- PNG: text, time and EXIF chunks are dropped; everything that affects how
  the image looks (palette, transparency, gamma, color profile) is kept.
- WEBP: EXIF and XMP chunks are dropped (and their header flags cleared).
- TIFF: metadata lives in the image directory itself, so the image is
  re-saved losslessly (LZW) without it. Multi-page TIFFs are refused (Qt
  can't write them back, and dropping pages silently is never OK).
- PDF: document info (author, creator app, dates, ...), XMP metadata (the
  document's and any on pages or images), attached files, JavaScript,
  page thumbnails and private app data are removed, and comments lose
  their author names and dates. Photos inside the PDF are cleaned like
  JPEG files (EXIF with GPS, XMP, IPTC, comments; byte for byte, never
  re-encoded). Earlier versions kept by incremental saves (which can hold
  the old metadata) are dropped too: the file is always written out fresh.

Anything stored after the end of the image (a motion photo's video, which
can carry its own GPS; extra preview images; data appended by other tools)
is removed as well, so the output is a plain still image. "Cleaned" is
never reported while such data is left in the file.

HEIC (iPhone photos) can't be written back: the clean copy is a JPG
(quality 95), with no metadata.

Files with nothing to remove (BMP, GIF, already clean files) are skipped:
"No metadata".
"""

from __future__ import annotations

import struct
from pathlib import Path

from .common import Context, HandlerError, Skip

NOTHING = "No metadata"
MOTION = "motion photo data"
TRAILING = "hidden data after the image"


def strip(path: Path, option: str, ctx: Context) -> None:
    head = path.read_bytes()[:16]
    if head.startswith(b"\xff\xd8"):
        data, removed = strip_jpeg(path.read_bytes())
    elif head.startswith(b"\x89PNG\r\n\x1a\n"):
        data, removed = strip_png(path.read_bytes())
    elif head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        data, removed = strip_webp(path.read_bytes())
    elif head[:4] in (b"II*\x00", b"MM\x00*"):
        _strip_tiff(path, ctx)
        return
    elif b"%PDF-" in path.read_bytes()[:1024]:
        _strip_pdf(path, ctx)
        return
    elif head[4:8] == b"ftyp":
        _strip_heic(path, ctx)
        return
    else:  # BMP has none; GIF metadata is rare and Qt can't rewrite GIFs
        raise Skip(NOTHING)
    if not removed:
        raise Skip(NOTHING)
    ctx.output_file(path.suffix, tag="clean").write_bytes(data)
    ctx.note("Cleaned", detail=describe(removed))
    ctx.progress(1.0)


def describe(removed: list[str]) -> str:
    """Notification text: "Motion photo data removed; also EXIF, XMP"."""
    for lead in (MOTION, TRAILING):
        if lead in removed:
            rest = [r for r in removed if r != lead]
            text = f"{lead[0].upper()}{lead[1:]} removed"
            return f"{text}; also {', '.join(rest)}" if rest else text
    return f"Removed {', '.join(removed)}"


def _trailing(extra: bytes) -> str | None:
    """What data after the end of an image is, or None if it's only padding."""
    if not extra.strip(b"\x00\xff \r\n\t"):
        return None
    if b"ftyp" in extra[:64] or b"MotionPhoto" in extra or b"SEFT" in extra[-8:] or b"SEFH" in extra:
        return MOTION  # Google / Samsung motion photos: an MP4 (or Samsung trailer) appended
    return TRAILING


# ------------------------------------------------------------------ JPEG ---

_SOS, _EOI = 0xDA, 0xD9


def strip_jpeg(data: bytes) -> tuple[bytes, list[str]]:
    """Return (cleaned bytes, names of what was removed)."""
    if data[:2] != b"\xff\xd8":
        raise HandlerError("Not a JPEG file")
    out = bytearray(b"\xff\xd8")
    removed: list[str] = []
    orientation = 1
    pos = 2
    end = len(data)  # set to just past the end-of-image marker once found
    while pos < len(data):
        if data[pos] != 0xFF:
            raise HandlerError("Damaged JPEG")
        while pos < len(data) and data[pos] == 0xFF:  # fill bytes
            pos += 1
        if pos >= len(data):
            break
        marker = data[pos]
        pos += 1
        if marker == _EOI:
            out += b"\xff\xd9"
            end = pos
            break
        if 0xD0 <= marker <= 0xD7 or marker == 0x01:  # markers without a length
            out += bytes((0xFF, marker))
            continue
        length = struct.unpack(">H", data[pos:pos + 2])[0]
        segment = data[pos + 2:pos + length]
        keep = True
        if marker == 0xE1:  # APP1: EXIF or XMP
            if segment.startswith(b"Exif\x00\x00"):
                orientation = _exif_orientation(segment[6:])
                removed.append("EXIF")
            else:
                removed.append("XMP")
            keep = False
        elif marker == 0xE2 and not segment.startswith(b"ICC_PROFILE\x00"):  # FlashPix, MPF etc.
            keep = False
            removed.append("APP2")
        elif 0xE3 <= marker <= 0xEF and marker != 0xEE:  # APP3..APP15 except Adobe (APP14)
            keep = False
            removed.append("IPTC" if marker == 0xED else f"APP{marker - 0xE0}")
        elif marker == 0xFE:
            keep = False
            removed.append("comment")
        if keep:
            out += bytes((0xFF, marker)) + data[pos:pos + length]
        pos += length
        if marker == _SOS:  # image data follows: copy it untouched up to the next marker
            scan_end = _scan_end(data, pos)
            out += data[pos:scan_end]
            pos = scan_end
    kind = _trailing(data[end:])
    if kind:
        removed.append(kind)
    if removed and orientation != 1:
        # Put the orientation back on its own, right after SOI / JFIF.
        insert_at = 2
        if out[2:4] == b"\xff\xe0":
            insert_at = 4 + struct.unpack(">H", out[4:6])[0]
        out[insert_at:insert_at] = _orientation_segment(orientation)
    return bytes(out), list(dict.fromkeys(removed))


def _scan_end(data: bytes, pos: int) -> int:
    """Where the entropy-coded data starting at `pos` ends: the next marker
    that isn't a stuffed 0xFF00, a restart marker or fill."""
    while True:
        i = data.find(b"\xff", pos)
        if i < 0 or i + 1 >= len(data):
            return len(data)  # truncated file: no end-of-image marker
        nxt = data[i + 1]
        if nxt == 0x00 or nxt == 0xFF or 0xD0 <= nxt <= 0xD7:
            pos = i + 1
            continue
        return i


def _exif_orientation(tiff: bytes) -> int:
    try:
        endian = "<" if tiff[:2] == b"II" else ">"
        ifd = struct.unpack(endian + "I", tiff[4:8])[0]
        count = struct.unpack(endian + "H", tiff[ifd:ifd + 2])[0]
        for i in range(count):
            entry = tiff[ifd + 2 + 12 * i: ifd + 14 + 12 * i]
            tag, typ = struct.unpack(endian + "HH", entry[:4])
            if tag == 0x0112 and typ == 3:
                value = struct.unpack(endian + "H", entry[8:10])[0]
                return value if 1 <= value <= 8 else 1
    except (struct.error, IndexError):
        pass
    return 1


def _orientation_segment(orientation: int) -> bytes:
    tiff = (b"II*\x00" + struct.pack("<I", 8) + struct.pack("<H", 1)
            + struct.pack("<HHIH", 0x0112, 3, 1, orientation) + b"\x00\x00"
            + struct.pack("<I", 0))
    payload = b"Exif\x00\x00" + tiff
    return b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload


# ------------------------------------------------------------------- PNG ---

_PNG_DROP = {b"tEXt": "text", b"zTXt": "text", b"iTXt": "text", b"tIME": "time", b"eXIf": "EXIF"}
_PNG_KEEP_ANCILLARY = {b"tRNS", b"gAMA", b"cHRM", b"sRGB", b"iCCP", b"sBIT", b"pHYs", b"bKGD",
                       b"hIST", b"sPLT", b"acTL", b"fcTL", b"fdAT", b"cICP", b"mDCv", b"cLLi"}


def strip_png(data: bytes) -> tuple[bytes, list[str]]:
    out = bytearray(data[:8])
    removed: list[str] = []
    pos = 8
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        ctype = data[pos + 4:pos + 8]
        chunk = data[pos:pos + 12 + length]
        critical = ctype[:1].isupper()
        if ctype in _PNG_DROP:
            removed.append(_PNG_DROP[ctype])
        elif critical or ctype in _PNG_KEEP_ANCILLARY:
            out += chunk
        else:  # unknown private ancillary chunk: may hold anything
            removed.append(ctype.decode("latin-1"))
        pos += 12 + length
        if ctype == b"IEND":
            kind = _trailing(data[pos:])
            if kind:
                removed.append(kind)
            break
    return bytes(out), list(dict.fromkeys(removed))


# ------------------------------------------------------------------ WEBP ---

def strip_webp(data: bytes) -> tuple[bytes, list[str]]:
    riff_end = min(len(data), 8 + struct.unpack("<I", data[4:8])[0])
    chunks = []
    pos = 12
    while pos + 8 <= riff_end:
        ctype = data[pos:pos + 4]
        size = struct.unpack("<I", data[pos + 4:pos + 8])[0]
        chunks.append((ctype, data[pos:pos + 8 + size + (size & 1)]))
        pos += 8 + size + (size & 1)
    removed = [c.decode().strip() for c, _ in chunks if c in (b"EXIF", b"XMP ")]
    kind = _trailing(data[riff_end:])
    if kind:
        removed.append(kind)
    if not removed:
        return data, []
    body = bytearray()
    for ctype, raw in chunks:
        if ctype in (b"EXIF", b"XMP "):
            continue
        if ctype == b"VP8X":  # clear the EXIF (0x08) and XMP (0x04) flags
            raw = bytearray(raw)
            raw[8] &= ~0x0C & 0xFF
            raw = bytes(raw)
        body += raw
    return b"RIFF" + struct.pack("<I", len(body) + 4) + b"WEBP" + bytes(body), removed


# ------------------------------------------------------------- TIFF, PDF ---

def _strip_tiff(path: Path, ctx: Context) -> None:
    from PyQt6.QtGui import QImageWriter

    from .image import _read

    image, _reader, _fmt = _read(path)  # refuses multi-page TIFFs
    out = ctx.output_file(path.suffix, tag="clean")
    writer = QImageWriter(str(out), b"tiff")
    writer.setCompression(1)  # LZW: lossless
    if not writer.write(image):
        raise HandlerError(f"Can't write TIFF ({writer.errorString()})")
    ctx.note("Cleaned", detail="Removed metadata")
    ctx.progress(1.0)


def _strip_heic(path: Path, ctx: Context) -> None:
    """HEIC can't be rewritten (Spindle has no HEIC encoder): the clean copy
    is a JPG, at quality 95 so it looks the same."""
    from PyQt6.QtGui import QImageWriter

    from .. import heic
    from .image import _flatten, _read

    try:
        removed = (["EXIF"] if heic.exif(path) else []) + (["XMP"] if heic.xmp(path) else [])
    except heic.HeicError as exc:
        raise HandlerError(str(exc)) from None
    if not removed:
        raise Skip(NOTHING)
    image, _reader, _fmt = _read(path)
    out = ctx.output_file(".jpg", tag="clean")
    writer = QImageWriter(str(out), b"jpeg")
    writer.setQuality(95)
    if not writer.write(_flatten(image)):
        raise HandlerError(f"Can't write JPG ({writer.errorString()})")
    ctx.note("Cleaned", detail=describe(removed) + " (saved as JPG)")
    ctx.progress(1.0)


def _strip_pdf(path: Path, ctx: Context) -> None:
    from .pdf import _open

    with _open(path) as doc:
        found = survey_pdf(doc, path)
        removed = pdf_removed(found)
        if not removed:
            raise Skip(NOTHING)
        ctx.progress(0.3)
        clean_pdf(doc, set(PDF_PARTS))
        ctx.progress(0.6)
        out = ctx.output_file(".pdf", tag="clean")
        doc.save(out, garbage=3, deflate=True)
    ctx.note("Cleaned", detail=describe(removed))
    ctx.progress(1.0)


# --------------------------------------------------- PDF: what is in it ---

# What clean_pdf can remove. Saving any copy (always a full rewrite) also
# drops earlier versions and data after the end of the file.
PDF_PARTS = ("info", "xmp", "attachments", "javascript", "thumbnails", "images", "private", "comments")
_INFO_KEYS = ("title", "author", "subject", "keywords", "creator", "producer", "creationDate", "modDate", "trapped")


def survey_pdf(doc, path: Path | None = None) -> dict:
    """Everything that counts as metadata in an open PDF:

    info         document info fields that are set {key: value}
    custom       other document info entries apps add (Company, ...)
    xmp          XMP packets: the document's and any on pages, images, fonts
    attachments  names of attached files (document level and on pages)
    javascript   JavaScript actions
    thumbnails   pages with an embedded thumbnail picture
    images       photos (JPEG streams) carrying EXIF / XMP / IPTC / comments
    images_gps   ... of which carry a GPS location
    private      private app data (PieceInfo: Illustrator / Photoshop keep
                 whole working files there)
    comments     comments (annotations) with an author or dates, and the
                 author names
    versions     earlier versions left by incremental saves
    trailing     data after the end of the file (None if there is none)
    """
    import pymupdf

    found = {"info": {k: v for k, v in (doc.metadata or {}).items() if k in _INFO_KEYS and v},
             "custom": _custom_info(doc), "xmp": 0, "attachments": list(doc.embfile_names()), "javascript": 0, "thumbnails": 0,
             "images": 0, "images_gps": 0, "private": 0, "comments": 0, "authors": [],
             "versions": doc.version_count > 1, "trailing": _trailing(_after_eof(path)) if path else None}
    if doc.get_xml_metadata():
        found["xmp"] += 1
    catalog = doc.pdf_catalog()
    for xref in range(1, doc.xref_length()):
        try:
            if doc.xref_get_key(xref, "S")[1] == "/JavaScript":
                found["javascript"] += 1
                continue
            if xref != catalog and (doc.xref_get_key(xref, "Metadata")[0] != "null"):
                found["xmp"] += 1
            if doc.xref_get_key(xref, "PieceInfo")[0] != "null":
                found["private"] += 1
            if _is_jpeg_image(doc, xref):
                removed, gps = _jpeg_stream_metadata(doc.xref_stream_raw(xref))
                if removed:
                    found["images"] += 1
                    found["images_gps"] += gps
        except (RuntimeError, ValueError):  # a broken object: nothing to read there
            continue
    authors = []
    for page in doc:
        if doc.xref_get_key(page.xref, "Thumb")[0] != "null":
            found["thumbnails"] += 1
        for annot in page.annots() or []:
            if annot.type[0] == pymupdf.PDF_ANNOT_FILE_ATTACHMENT:
                found["attachments"].append(annot.file_info.get("filename") or "file")
            info = annot.info
            if info.get("title") or info.get("creationDate") or info.get("modDate"):
                found["comments"] += 1
                if info.get("title") and info["title"] not in authors:
                    authors.append(info["title"])
    found["authors"] = authors
    return found


def _custom_info(doc) -> dict:
    """Document info entries beyond the standard ones (Word adds Company,
    SourceModified, ...): {name: text}."""
    kind, value = doc.xref_get_key(-1, "Info")
    if kind != "xref":
        return {}
    xref = int(value.split()[0])
    out = {}
    for key in doc.xref_get_keys(xref):
        if key not in _STANDARD_INFO:
            kind, text = doc.xref_get_key(xref, key)
            if kind != "null" and text:
                out[key] = text
    return out


_STANDARD_INFO = {"Title", "Author", "Subject", "Keywords", "Creator", "Producer", "CreationDate", "ModDate",
                  "Trapped"}


def pdf_removed(found: dict) -> list[str]:
    """What cleaning would remove, for the notification."""
    out = []
    if found["info"] or found["custom"]:
        out.append("document info")
    if found["xmp"]:
        out.append("XMP")
    if found["images"]:
        n = found["images"]
        out.append(f"photo metadata ({n} image{'s' if n != 1 else ''})")
    if found["comments"]:
        out.append("comment authors")
    if found["attachments"]:
        out.append("attachments")
    if found["javascript"]:
        out.append("JavaScript")
    if found["thumbnails"]:
        out.append("page thumbnails")
    if found["private"]:
        out.append("app data")
    if found["versions"]:
        out.append("earlier versions")
    if found["trailing"]:
        out.append(found["trailing"])
    return out


def _is_jpeg_image(doc, xref: int) -> bool:
    if doc.xref_get_key(xref, "Subtype")[1] != "/Image":
        return False
    kind, value = doc.xref_get_key(xref, "Filter")
    return value in ("/DCTDecode", "[/DCTDecode]") or (kind == "array" and value.replace(" ", "") == "[/DCTDecode]")


def _jpeg_stream_metadata(raw: bytes) -> tuple[list[str], bool]:
    """(what strip_jpeg would remove, whether there is a GPS block)."""
    try:
        _clean, removed = strip_jpeg(raw)
    except HandlerError:
        return [], False
    return removed, bool(removed) and exif_has_gps(raw)


def exif_has_gps(jpeg: bytes) -> bool:
    """Whether a JPEG's EXIF block points to GPS data."""
    pos = 2
    while pos + 4 <= len(jpeg) and jpeg[pos] == 0xFF:
        marker = jpeg[pos + 1]
        if marker in (_SOS, _EOI):
            break
        length = struct.unpack(">H", jpeg[pos + 2:pos + 4])[0]
        segment = jpeg[pos + 4:pos + 2 + length]
        if marker == 0xE1 and segment.startswith(b"Exif\x00\x00"):
            return _ifd0_has(segment[6:], 0x8825)
        pos += 2 + length
    return False


def _ifd0_has(tiff: bytes, wanted: int) -> bool:
    try:
        endian = "<" if tiff[:2] == b"II" else ">"
        ifd = struct.unpack(endian + "I", tiff[4:8])[0]
        count = struct.unpack(endian + "H", tiff[ifd:ifd + 2])[0]
        return any(struct.unpack(endian + "H", tiff[ifd + 2 + 12 * i: ifd + 4 + 12 * i])[0] == wanted
                   for i in range(count))
    except (struct.error, IndexError):
        return False


# ---------------------------------------------------- PDF: removing it ---

def clean_pdf(doc, parts: set[str]) -> None:
    """Remove the given PDF_PARTS from an open PDF. Page content is never
    touched: photos lose only their metadata blocks (byte for byte, no
    re-encoding), comments keep their text but lose author and dates."""
    if parts & {"info", "xmp", "attachments", "javascript", "thumbnails"}:
        doc.scrub(metadata="info" in parts, xml_metadata="xmp" in parts,
                  attached_files="attachments" in parts, embedded_files="attachments" in parts,
                  javascript="javascript" in parts, thumbnails="thumbnails" in parts,
                  # leave everything that changes what pages look like or do:
                  clean_pages=False, hidden_text=False, redactions=False, redact_images=0,
                  remove_links=False, reset_fields=False, reset_responses=False)
    if "images" in parts or "private" in parts:
        for xref in range(1, doc.xref_length()):
            try:
                if "private" in parts and doc.xref_get_key(xref, "PieceInfo")[0] != "null":
                    doc.xref_set_key(xref, "PieceInfo", "null")
                    doc.xref_set_key(xref, "LastModified", "null")
                if "images" in parts and _is_jpeg_image(doc, xref):
                    _clean_jpeg_stream(doc, xref)
            except (RuntimeError, ValueError):
                continue
    if "comments" in parts:
        for page in doc:
            for annot in page.annots() or []:
                for key in ("T", "M", "CreationDate"):
                    if doc.xref_get_key(annot.xref, key)[0] != "null":
                        doc.xref_set_key(annot.xref, key, "null")


def _clean_jpeg_stream(doc, xref: int) -> None:
    raw = doc.xref_stream_raw(xref)
    try:
        clean, removed = strip_jpeg(raw)
    except HandlerError:
        return  # not a JPEG we understand: leave it as it is
    if not removed:
        return
    # update_stream drops the filter: put it (and its parameters) back so
    # the stream stays the very same JPEG, minus the metadata.
    filt = doc.xref_get_key(xref, "Filter")
    parms = doc.xref_get_key(xref, "DecodeParms")
    doc.update_stream(xref, clean, compress=False)
    doc.xref_set_key(xref, "Filter", filt[1])
    if parms[0] != "null":
        doc.xref_set_key(xref, "DecodeParms", parms[1])


def _after_eof(path: Path) -> bytes:
    with path.open("rb") as f:  # only the end matters
        f.seek(max(0, path.stat().st_size - (1 << 20)))
        data = f.read()
    i = data.rfind(b"%%EOF")
    return data[i + 5:] if i >= 0 else b""
