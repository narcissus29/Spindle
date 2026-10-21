"""The metadata viewer / editor (Info tool): what a file carries, and the
user's changes to it.

Changes are part of the edit state (state["meta"], so they undo like any
other edit):

    {"set": {key: value}, "drop": [key, ...], "clean": bool}

`clean` is True when nothing is left after the changes ("Remove all");
the copy is then called "name (clean).ext".

Image keys:
    field:<name>      the editable details (FIELDS): set text / drop
    gps               the location: set [lat, lon] / drop all of GPS
    tag:<ifd>:<id>    any other EXIF entry: drop
    thumbnail         the small preview picture inside EXIF: drop
    xmp, iptc, comment, text:<kw>, block:<name>, trailing
                      whole blocks (see containers.py): drop

PDF keys:
    info:<name>       document info fields (PDF_FIELDS): set / drop
    xmp, images, comments, attachments, javascript, thumbnails, private
                      see handlers/metadata.py survey_pdf: drop

Images are never re-encoded for metadata changes: the blocks are swapped
in the file as it is (JPEG, PNG, WEBP). Other formats can be viewed;
TIFF can be cleaned (re-saved losslessly), GIF and BMP carry nothing
Spindle can change.

When the picture itself was edited (crop, colors, marks, ...), the saved
copy is a new image: the original's metadata is carried over to it with
the changes applied, its orientation reset (the pixels are already
upright), its size updated, and without the thumbnail or anything
trailing (those show the old picture). Redacted copies carry nothing.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from . import containers as ct
from .exif import Exif, decode_text, degrees, dms

# key, label, directory, tag
FIELDS = (
    ("description", "Description", "0", 0x010E),
    ("artist", "Artist", "0", 0x013B),
    ("copyright", "Copyright", "0", 0x8298),
    ("datetaken", "Date taken", "exif", 0x9003),
    ("make", "Camera make", "0", 0x010F),
    ("model", "Camera model", "0", 0x0110),
)
_FIELD_TAGS = {(ifd, tag) for _k, _l, ifd, tag in FIELDS}
ORIENTATION = 0x0112
MAKER_NOTE = 0x927C
_DATE_TAGS = {0x0132, 0x9003, 0x9004}
_SIZE_TAGS = (0xA002, 0xA003)  # PixelXDimension / PixelYDimension

PDF_FIELDS = (
    ("title", "Title"), ("author", "Author"), ("subject", "Subject"), ("keywords", "Keywords"),
    ("creator", "Created with"), ("producer", "PDF made by"),
    ("creationDate", "Created"), ("modDate", "Modified"),
)
PDF_DATES = ("creationDate", "modDate")

NO_CHANGES = {"set": {}, "drop": [], "clean": False}


def changed(meta: dict | None) -> bool:
    return bool(meta and (meta["set"] or meta["drop"]))


class MetaError(ValueError):
    """A value the user typed can't be used; the message says why."""


# ------------------------------------------------------------- values ---

def parse_date(text: str) -> datetime:
    text = " ".join(text.strip().replace("T", " ").split())
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y:%m:%d %H:%M:%S", "%d.%m.%Y %H:%M",
                "%d.%m.%Y", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise MetaError("Use a date like 2024-05-31 18:30")


def parse_location(text: str) -> list[float]:
    """"48.8584, 2.2945", "48.8584 2.2945" or "48.8584° N, 2.2945° E"."""
    nums = re.findall(r"[-+]?\d+(?:\.\d+)?", text)
    if len(nums) != 2:
        raise MetaError("Use latitude, longitude like 48.8584, 2.2945")
    lat, lon = (float(n) for n in nums)
    up = text.upper()
    if re.search(r"\d\s*°?\s*S\b", up):
        lat = -abs(lat)
    if re.search(r"\d\s*°?\s*W\b", up):
        lon = -abs(lon)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise MetaError("Latitude goes from -90 to 90, longitude from -180 to 180")
    return [round(lat, 7), round(lon, 7)]


def format_location(lat: float, lon: float) -> str:
    return f"{abs(lat):.5f}° {'N' if lat >= 0 else 'S'}, {abs(lon):.5f}° {'E' if lon >= 0 else 'W'}"


def _exif_date(text: str) -> str:
    return text.replace("-", ":", 2) if re.match(r"\d{4}-\d\d-\d\d", text) else text


def _pretty_date(text: str) -> str:
    m = re.match(r"(\d{4}):(\d\d):(\d\d)[ T](\d\d:\d\d(?::\d\d)?)", text)
    return f"{m[1]}-{m[2]}-{m[3]} {m[4]}" if m else text


def _size_text(n: int) -> str:
    if n < 1024:
        return f"{n} bytes"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 / 1024:.1f} MB"


_NICE_NAMES = {("exif", 0x829A): "Shutter speed", ("exif", 0x829D): "Aperture", ("exif", 0x8827): "ISO",
               ("exif", 0x920A): "Focal length", ("exif", 0xA405): "Focal length (35 mm)",
               ("exif", 0xA434): "Lens", ("exif", 0xA433): "Lens make", ("exif", 0xA431): "Camera serial number",
               ("exif", 0xA435): "Lens serial number", ("exif", 0xA420): "Unique image ID",
               ("0", 0x0131): "Software", ("0", 0x0132): "Date changed", ("exif", 0x9004): "Date digitized",
               ("exif", 0x9010): "Time zone", ("exif", 0x9011): "Time zone (taken)",
               ("exif", 0xA430): "Owner name", ("0", 0x9C9D): "Author (Windows)"}


def _tag_name(ifd: str, tag: int) -> str:
    from PIL import ExifTags

    if (ifd, tag) in _NICE_NAMES:
        return _NICE_NAMES[(ifd, tag)]

    names = ExifTags.GPSTAGS if ifd == "gps" else ExifTags.TAGS
    name = names.get(tag)
    if not name:
        return f"Tag 0x{tag:04X}"
    if ifd == "gps" and name.startswith("GPS"):
        name = name[3:]
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", name)
    words = name.split()
    return " ".join([words[0]] + [w if w.isupper() else w.lower() for w in words[1:]]) if words else name


def _show(ex: Exif, ifd: str, tag: int) -> str:
    """A readable value for the viewer."""
    try:
        return _pretty(ex, ifd, tag, ex.value(ifd, tag))
    except Exception:  # odd data: say what it is
        return f"{_size_text(len(ex.ifds[ifd][tag].data))} of data"


def _pretty(ex: Exif, ifd: str, tag: int, value) -> str:
    if ifd == "exif" and tag == 0x829A:  # exposure time
        frac = ex.fraction(ifd, tag)
        if frac and frac[0] and frac[1] and frac[1] > frac[0]:
            return f"1/{round(frac[1] / frac[0])} s"
        return f"{value:g} s"
    if ifd == "exif" and tag == 0x829D:
        return f"f/{value:.1f}".replace(".0", "")
    if ifd == "exif" and tag in (0x920A, 0xA405):
        return f"{value:g} mm"
    if tag in _DATE_TAGS and isinstance(value, str):
        return _pretty_date(value)
    if ifd == "gps" and tag in (2, 4) and isinstance(value, tuple):
        return f"{degrees(value):.5f}°"
    if ifd == "gps" and tag == 6 and isinstance(value, float):
        return f"{value:.1f} m"
    if isinstance(value, bytes):
        text = value.rstrip(b"\x00")
        if text.startswith((b"ASCII\x00\x00\x00", b"UNICODE\x00", b"\x00" * 8)):  # UserComment
            text = text[8:].rstrip(b"\x00")
        if text and all(32 <= c < 127 for c in text) and len(text) <= 80:
            return text.decode()
        return _size_text(len(value)) + " of data"
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, tuple):
        if len(value) > 8:
            return f"{len(value)} values"
        return ", ".join(f"{v:.6g}" if isinstance(v, float) else str(v) for v in value)
    text = str(value)
    return text if len(text) <= 120 else text[:117] + "…"


# ------------------------------------------------------------- images ---

class ImageMeta:
    """Metadata of an image file, read once when the Info tool opens."""

    def __init__(self, path: Path) -> None:
        self.path = path
        data = path.read_bytes()
        self.kind = ct.kind_of(data) or _other_kind(data)
        try:
            self.blocks = ct.split(data)
        except (ValueError, IndexError):
            self.blocks = None
        self.editable = self.blocks is not None
        self.exif: Exif | None = None
        self.icc = ""
        self.extra: list[tuple[str, str]] = []  # read-only (label, value) for TIFF / GIF
        if self.blocks is not None:
            for b in self.blocks:
                if b.key == "exif" and self.exif is None:
                    try:
                        self.exif = Exif.parse(b.payload)
                    except ValueError:
                        self.exif = None  # broken EXIF: can still be removed
            self._has_exif_block = any(b.key == "exif" for b in self.blocks)
        else:
            self._has_exif_block = False
            if self.kind == "heic":
                self._read_heic()
            else:
                self._read_other()
        self.icc = _icc_name(path)
        self.iptc = _iptc_summary(path) if self.blocks and any(b.key == "iptc" for b in self.blocks) else ""
        self.trailing_kind = self._trailing_kind()

    def _trailing_kind(self) -> str | None:
        """What trails the image (handlers.metadata MOTION / TRAILING), or
        None if nothing does (zero padding doesn't count)."""
        from ..handlers.metadata import TRAILING, _trailing

        if not self.blocks:
            return None
        tail = b"".join(b.raw for b in self.blocks if b.key == "trailing" and b.raw[:2] != b"\xff\xe2")
        mpf = any(b.key == "trailing" and b.raw[:2] == b"\xff\xe2" for b in self.blocks)
        return _trailing(tail) or (TRAILING if mpf else None)

    def _read_heic(self) -> None:
        """HEIC: EXIF and XMP are shown (read only: Spindle can't write
        HEIC); "Remove all" makes a clean JPG."""
        from .. import heic

        self.blocks = []
        self.heic_xmp = None
        try:
            tiff = heic.exif(self.path)
            self.heic_xmp = heic.xmp(self.path)
        except heic.HeicError:
            return
        if tiff:
            try:
                self.exif = Exif.parse(tiff)
            except ValueError:
                self.exif = None

    def _read_other(self) -> None:
        """TIFF / GIF / BMP: shown read-only through Pillow."""
        from PIL import Image

        try:
            with Image.open(self.path) as im:
                if self.kind == "tiff":
                    tags = im.getexif()
                    for tag, label in ((0x010E, "Description"), (0x013B, "Artist"), (0x8298, "Copyright"),
                                       (0x0132, "Date"), (0x010F, "Camera make"), (0x0110, "Camera model"),
                                       (0x0131, "Software")):
                        if tag in tags and str(tags[tag]).strip():
                            self.extra.append((label, str(tags[tag]).strip()))
                    if tags.get_ifd(0x8825):
                        self.extra.append(("Location", "GPS data"))
                    for tag, label in ((700, "XMP"), (33723, "IPTC"), (34377, "Photoshop data")):
                        if tag in getattr(im, "tag_v2", {}):
                            self.extra.append((label, "present"))
                if "comment" in im.info:
                    raw = im.info["comment"]
                    self.extra.append(("Comment", raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)))
        except Exception:  # Pillow can't read it: show nothing extra
            pass

    # ---- what is there ----

    def keys(self) -> list[str]:
        """Every key the file has something for (what "Remove all" drops)."""
        if self.kind == "heic":
            return ["all"] if self.exif is not None or self.heic_xmp else []
        if not self.editable:
            return ["all"] if self.kind == "tiff" and self.extra else []
        out = []
        ex = self.exif
        if ex is not None:
            for name, _label, ifd, tag in FIELDS:
                if tag in ex.ifds[ifd]:
                    out.append(f"field:{name}")
            if ex.ifds["gps"]:
                out.append("gps")
            for ifd in ("0", "exif", "interop", "gps"):
                for tag in ex.ifds[ifd]:
                    if (ifd, tag) not in _FIELD_TAGS and not (ifd == "0" and tag == ORIENTATION):
                        out.append(f"tag:{ifd}:{tag}")
            if ex.thumbnail:
                out.append("thumbnail")
        elif self._has_exif_block:
            out.append("block:exif")
        for b in self.blocks:
            if b.key and b.key != "exif" and b.key not in out:
                if b.key == "trailing" and self.trailing_kind is None:
                    continue  # zero padding only
                out.append(b.key)
        return out

    def remaining(self, meta: dict) -> bool:
        """Is anything left after these changes?"""
        drop = set(meta["drop"])
        if any(v not in (None, "") for v in meta["set"].values()):
            return True
        return any(k not in drop and not (k.startswith("tag:gps:") and "gps" in drop) for k in self.keys())

    def thumbnail(self) -> bytes | None:
        return self.exif.thumbnail if self.exif else None

    def xmp_text(self) -> str:
        if self.kind == "heic":
            return (self.heic_xmp or b"").decode("utf-8", "replace")
        if not self.blocks:
            return ""
        parts = []
        for b in self.blocks:
            if b.key == "xmp":
                data = b.payload
                for sig in (ct._XMP_SIG, ct._XMP_EXT_SIG):
                    if data.startswith(sig):
                        data = data[len(sig):]
                if b.raw[:2] == b"\xff\xe1" and data[:1] != b"<":  # extended XMP: GUID + offsets first
                    data = data[40:]
                parts.append(data.decode("utf-8", "replace"))
        return "\n".join(parts)

    def location(self) -> list[float] | None:
        ex = self.exif
        if ex is None or 2 not in ex.ifds["gps"] or 4 not in ex.ifds["gps"]:
            return None
        try:
            lat, lon = degrees(ex.value("gps", 2)), degrees(ex.value("gps", 4))
            if 1 in ex.ifds["gps"] and ex.value("gps", 1).upper().startswith("S"):
                lat = -lat
            if 3 in ex.ifds["gps"] and ex.value("gps", 3).upper().startswith("W"):
                lon = -lon
        except (ValueError, TypeError, AttributeError):
            return None
        return [lat, lon]

    def field(self, name: str) -> str:
        ex = self.exif
        for key, _label, ifd, tag in FIELDS:
            if key == name and ex is not None and tag in ex.ifds[ifd]:
                value = ex.value(ifd, tag)
                text = value if isinstance(value, str) else decode_text(value) if isinstance(value, bytes) else str(value)
                return _pretty_date(text) if name == "datetaken" else text
        return ""

    def check(self, key: str, value) -> object:
        """The value to store for a change, or MetaError."""
        if key == "gps":
            return parse_location(value) if isinstance(value, str) else [float(v) for v in value]
        if key == "field:datetaken" and str(value).strip():
            return parse_date(str(value)).strftime("%Y-%m-%d %H:%M:%S")
        if key.startswith("field:"):
            text = str(value).strip()
            if len(text.encode()) > 2000:
                raise MetaError("That's too long for this field")
            return text
        raise MetaError("This can't be edited")

    # ---- the viewer ----

    def sections(self, meta: dict) -> list[dict]:
        drop, sets = set(meta["drop"]), meta["set"]

        def row(key, label, value, *, edit="", removable=True, hint="", extra=None):
            gone = key in drop or (key.startswith("tag:gps:") and "gps" in drop) or (
                "all" in drop and not key.startswith("keep:"))
            state = "removed" if gone else ("edited" if key in sets else "")
            if key in sets:
                v = sets[key]
                value = format_location(*v) if key == "gps" else (_pretty_date(v) if key == "field:datetaken" else v)
                if value == "":
                    state = "removed"
            r = {"key": key, "label": label, "value": value, "edit": edit, "removable": removable,
                 "state": state, "hint": hint,
                 # removed along with the whole location: restored with it, not alone
                 "covered": (key.startswith("tag:gps:") and "gps" in drop) or "all" in drop}
            if extra:
                r.update(extra)
            return r

        out = []
        if not self.editable and self.kind != "heic":
            items = [row(f"ro:{i}", label, value, removable=False) for i, (label, value) in enumerate(self.extra)]
            if items:
                out.append({"title": "Details", "items": items})
            return out
        ex = self.exif
        gps_rows = []
        loc = self.location()
        if loc or "gps" in sets:
            gps_rows.append(row("gps", "Coordinates", format_location(*loc) if loc else "", edit="gps",
                                hint="Where the photo was taken"))
            if ex is not None:
                for tag in sorted(ex.ifds["gps"]):
                    if tag not in (0, 1, 2, 3, 4):
                        gps_rows.append(row(f"tag:gps:{tag}", _tag_name("gps", tag), _show(ex, "gps", tag)))
        if gps_rows:
            out.append({"title": "Location", "items": gps_rows})
        out.append({"title": "Details", "items": [
            row(f"field:{name}", label, self.field(name), edit="date" if name == "datetaken" else "text",
                removable=ex is not None and tag in ex.ifds[ifd])
            for name, label, ifd, tag in FIELDS]})
        other = []
        if ex is not None:
            for ifd in ("0", "exif", "interop"):
                for tag in sorted(ex.ifds[ifd]):
                    if (ifd, tag) in _FIELD_TAGS or tag == MAKER_NOTE:
                        continue
                    if ifd == "0" and tag == ORIENTATION:
                        continue
                    other.append(row(f"tag:{ifd}:{tag}", _tag_name(ifd, tag), _show(ex, ifd, tag)))
        if other:
            out.append({"title": f"Camera and file ({len(other)})", "items": other})
        embedded = []
        if ex is not None and ex.thumbnail:
            embedded.append(row("thumbnail", "Thumbnail", _size_text(len(ex.thumbnail)),
                                hint="A small copy of the photo. It can show what was cropped out.",
                                extra={"thumb": True}))
        if ex is not None and MAKER_NOTE in ex.ifds["exif"]:
            embedded.append(row(f"tag:exif:{MAKER_NOTE}", "Maker notes",
                                _size_text(len(ex.ifds["exif"][MAKER_NOTE].data)),
                                hint="Camera-specific data, can include serial numbers"))
        seen = set()
        for b in self.blocks:
            if not b.key or b.key in seen or b.key in ("exif",):
                continue
            seen.add(b.key)
            size = sum(len(x.raw) for x in self.blocks if x.key == b.key)
            if b.key == "xmp":
                embedded.append(row("xmp", "XMP", _size_text(size), hint="Adobe metadata: can repeat the camera, "
                                    "dates, location and edit history", extra={"view": True}))
            elif b.key == "iptc":
                embedded.append(row("iptc", "IPTC", self.iptc or _size_text(size),
                                    hint="Captions, keywords, credits"))
            elif b.key == "comment":
                text = b.payload.decode("utf-8", "replace").strip()
                embedded.append(row("comment", "Comment", text[:200] or _size_text(size)))
            elif b.key.startswith("text:"):
                text = b.payload.decode("utf-8", "replace").strip()
                embedded.append(row(b.key, b.key[5:], text[:200] if len(text) <= 200 else text[:197] + "…"))
            elif b.key == "trailing":
                from ..handlers.metadata import MOTION

                if self.trailing_kind is None:
                    continue
                embedded.append(row("trailing", "Motion photo video" if self.trailing_kind == MOTION
                                    else "Hidden data after the image", _size_text(size),
                                    hint="Stored after the end of the picture; can carry its own location"))
            else:
                embedded.append(row(b.key, _block_label(b.key), _size_text(size)))
        if self.kind == "heic" and self.heic_xmp:
            embedded.append(row("xmp", "XMP", _size_text(len(self.heic_xmp)), extra={"view": True}))
        if self._has_exif_block and ex is None:
            embedded.append(row("block:exif", "EXIF (damaged)", "can't be read", hint="Removing it is safe"))
        if embedded:
            out.append({"title": "Embedded data", "items": embedded})
        kept = []
        if ex is not None and ORIENTATION in ex.ifds["0"]:
            kept.append(row("keep:orientation", "Orientation", _orientation_text(ex.number("0", ORIENTATION)),
                            removable=False, hint="Kept: the photo needs it to show upright"))
        if self.icc:
            kept.append(row("keep:icc", "Color profile", self.icc, removable=False,
                            hint="Kept: it changes how colors look"))
        if kept:
            out.append({"title": "Always kept", "items": kept})
        return out

    # ---- writing ----

    def apply(self, meta: dict) -> bytes:
        """The original file with the changes, image data untouched."""
        blocks = list(self.blocks)
        drop = set(meta["drop"])
        exif_block = self._new_exif(meta)
        out = []
        placed = False
        for b in blocks:
            if b.key == "exif":
                if not placed and exif_block is not None:
                    out.append(exif_block)
                placed = True
                continue
            if b.key and b.key in drop:
                continue
            if b.key == "xmp" and "gps" in drop:
                b = _edit_xmp(b, self.kind, no_gps=True)
            out.append(b)
        if not placed and exif_block is not None:
            at = ct.jpeg_insert_at(out) if self.kind == "jpeg" else (
                ct.png_insert_at(out) if self.kind == "png" else len(out))
            out.insert(at, exif_block)
        return ct.join(out, self.kind)

    def _exif_changes(self, meta: dict) -> bool:
        keys = set(meta["drop"]) | set(meta["set"])
        return any(k.startswith(("field:", "tag:")) or k in ("gps", "thumbnail", "block:exif") for k in keys)

    def _new_exif(self, meta: dict, *, upright: bool = False, size: tuple[int, int] | None = None,
                  thumbnail: bool = True, kind: str = "") -> ct.Block | None:
        """The EXIF block with the changes (None: no EXIF at all). The
        original block is reused as is when nothing in it changes."""
        rewrite = upright or size is not None or not thumbnail or self._exif_changes(meta)
        original = next((b for b in self.blocks if b.key == "exif"), None)
        if not rewrite:
            return original
        if "block:exif" in meta["drop"]:
            return None
        ex = Exif.parse(self.exif.to_bytes()) if self.exif is not None else Exif()
        drop, sets = set(meta["drop"]), meta["set"]
        for key in drop:
            if key.startswith("tag:"):
                _t, ifd, tag = key.split(":")
                ex.remove(ifd, int(tag))
        if "gps" in drop:
            ex.ifds["gps"] = {}
        if "thumbnail" in drop or not thumbnail:
            ex.thumbnail = None
            ex.ifds["1"] = {}
        for name, _label, ifd, tag in FIELDS:
            key = f"field:{name}"
            if key in drop:
                ex.remove(ifd, tag)
            if key in sets:
                text = sets[key]
                if not text:
                    ex.remove(ifd, tag)
                else:
                    ex.set_text(ifd, tag, _exif_date(text) if name == "datetaken" else text)
        if "gps" in sets:
            lat, lon = sets["gps"]
            gps = ex.ifds["gps"]
            if 0 not in gps:
                ex.set_bytes("gps", 0, bytes([2, 3, 0, 0]))
            ex.set_text("gps", 1, "N" if lat >= 0 else "S")
            ex.set_rationals("gps", 2, dms(lat))
            ex.set_text("gps", 3, "E" if lon >= 0 else "W")
            ex.set_rationals("gps", 4, dms(lon))
        if upright and ORIENTATION in ex.ifds["0"]:
            ex.set_short("0", ORIENTATION, 1)
        if size is not None:
            for tag, value in zip(_SIZE_TAGS, size):
                if tag in ex.ifds["exif"]:
                    ex.set_long("exif", tag, value)
        if ex.is_empty():
            return None
        tiff = ex.to_bytes()
        kind = kind or self.kind
        if kind == "png":
            return ct.png_chunk(b"eXIf", tiff, "exif")
        if kind == "webp":
            return ct.webp_chunk(b"EXIF", tiff, "exif")
        return ct.jpeg_exif_block(tiff)

    def carry_over(self, written: bytes, meta: dict, size: tuple[int, int]) -> bytes:
        """Metadata for a re-encoded copy (`written`, same format): the
        original's, with the changes, upright, at the new size, with no
        thumbnail and nothing trailing. The new file's own color profile
        and image data are kept."""
        new_blocks = ct.split(written)
        target = ct.kind_of(written)
        if new_blocks is None or not (target == self.kind or (self.kind == "heic" and target == "jpeg")):
            return written
        drop = set(meta["drop"])
        if "all" in drop:
            return written
        exif_block = self._new_exif(meta, upright=True, size=size, thumbnail=False, kind=target)
        carried = []
        for b in self.blocks:
            if b.key in ("xmp", "iptc", "comment") or b.key.startswith("text:"):
                if b.key not in drop:
                    carried.append(_edit_xmp(b, self.kind, upright=True, no_gps="gps" in drop)
                                   if b.key == "xmp" else b)
        if self.kind == "heic" and self.heic_xmp and "xmp" not in drop:  # into the JPG as an APP1 block
            import struct

            payload = ct._XMP_SIG + self.heic_xmp
            block = ct.Block("xmp", b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload, payload)
            carried.append(_edit_xmp(block, "jpeg", upright=True, no_gps="gps" in drop))
        # the new file's own metadata blocks (if any) are replaced
        out = [b for b in new_blocks if not b.key]
        meta_blocks = ([exif_block] if exif_block is not None else []) + carried
        if target == "jpeg":
            at = ct.jpeg_insert_at(out)
        elif target == "png":
            at = ct.png_insert_at(out)
        else:
            at = len(out)
        out[at:at] = meta_blocks
        return ct.join(out, target)


_XMP_GPS = (re.compile(rb'\s(?:exif|exifEX):GPS\w+="[^"]*"'),
            re.compile(rb"<((?:exif|exifEX):GPS\w+)\b[^>]*?(?:/>|>.*?</\1>)", re.S))


def _edit_xmp(block: ct.Block, kind: str, *, upright: bool = False, no_gps: bool = False) -> ct.Block:
    """XMP repeats some EXIF: say "upright" there too, and take the GPS
    position out of it when the location is removed."""
    if kind == "jpeg":
        if not block.payload.startswith(ct._XMP_SIG):
            return block  # extended XMP: big extras (depth maps, ...), no position
        xml = block.payload[len(ct._XMP_SIG):]
    elif kind == "png":
        xml = block.payload
    else:
        xml = block.payload
    fixed = xml
    if upright:
        fixed = re.sub(rb'tiff:Orientation="\d"', b'tiff:Orientation="1"', fixed)
        fixed = re.sub(rb"<tiff:Orientation>\d</tiff:Orientation>", b"<tiff:Orientation>1</tiff:Orientation>", fixed)
    if no_gps:
        for pattern in _XMP_GPS:
            fixed = pattern.sub(b"", fixed)
    if fixed == xml:
        return block
    if kind == "jpeg":
        payload = ct._XMP_SIG + fixed
        import struct

        return ct.Block("xmp", b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload, payload)
    if kind == "png":  # rewritten as plain (uncompressed) international text
        return ct.png_chunk(b"iTXt", b"XML:com.adobe.xmp\x00\x00\x00\x00\x00" + fixed, "xmp")
    return ct.webp_chunk(b"XMP ", fixed, "xmp")


def _orientation_text(value: int) -> str:
    return {1: "Upright", 2: "Mirrored", 3: "Upside down", 4: "Flipped", 5: "Mirrored, turned",
            6: "Turned right", 7: "Mirrored, turned", 8: "Turned left"}.get(value, str(value))


def _block_label(key: str) -> str:
    name = key.split(":", 1)[1]
    return {"time": "Last-modified time", "APP2": "FlashPix data", "APP1": "App data"}.get(name, f"{name} block")


def _other_kind(data: bytes) -> str:
    from ..heic import is_heic

    if is_heic(data[:64]):
        return "heic"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    if data[:3] == b"GIF":
        return "gif"
    if data[:2] == b"BM":
        return "bmp"
    return ""


def _icc_name(path: Path) -> str:
    try:
        from PIL import Image, ImageCms

        with Image.open(path) as im:
            icc = im.info.get("icc_profile")
            if not icc:
                return ""
            try:
                import io

                return ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(io.BytesIO(icc))).strip()
            except Exception:
                return _size_text(len(icc))
    except Exception:
        return ""


_IPTC_NAMES = {(2, 5): "Title", (2, 25): "Keywords", (2, 80): "By", (2, 90): "City", (2, 95): "State",
               (2, 101): "Country", (2, 105): "Headline", (2, 110): "Credit", (2, 116): "Copyright",
               (2, 120): "Caption"}


def _iptc_summary(path: Path) -> str:
    try:
        from PIL import Image, IptcImagePlugin

        with Image.open(path) as im:
            info = IptcImagePlugin.getiptcinfo(im) or {}
    except Exception:
        return ""
    parts = []
    for key, label in _IPTC_NAMES.items():
        value = info.get(key)
        if value:
            values = value if isinstance(value, list) else [value]
            parts.append(f"{label}: " + ", ".join(v.decode("utf-8", "replace") for v in values))
    return "; ".join(parts)[:200]


# ---------------------------------------------------------------- PDF ---

class PdfMeta:
    """Metadata of an open PDF (survey on the editor's PdfDocument)."""

    def __init__(self, found: dict, xmp: str) -> None:
        self.found = found
        self._xmp = xmp

    @classmethod
    def read(cls, doc, path: Path) -> "PdfMeta":
        from ..handlers.metadata import survey_pdf

        return cls(survey_pdf(doc, path), doc.get_xml_metadata() or "")

    def keys(self) -> list[str]:
        f = self.found
        out = [f"info:{k}" for k, _label in PDF_FIELDS if f["info"].get(k)]
        out += [f"custom:{k}" for k in f["custom"]]
        for key in ("xmp", "images", "comments", "attachments", "javascript", "thumbnails", "private"):
            if f[key]:
                out.append(key)
        return out

    def remaining(self, meta: dict) -> bool:
        if any(v for v in meta["set"].values()):
            return True
        drop = set(meta["drop"])
        return any(k not in drop for k in self.keys())

    def xmp_text(self) -> str:
        return self._xmp

    def thumbnail(self):
        return None

    def check(self, key: str, value) -> object:
        if not key.startswith("info:"):
            raise MetaError("This can't be edited")
        text = str(value).strip()
        if key[5:] in PDF_DATES and text:
            return parse_date(text).strftime("%Y-%m-%d %H:%M:%S")
        return text

    def sections(self, meta: dict) -> list[dict]:
        drop, sets = set(meta["drop"]), meta["set"]
        f = self.found

        def row(key, label, value, *, edit="", removable=True, hint="", extra=None):
            state = "removed" if key in drop else ("edited" if key in sets else "")
            if key in sets:
                value = sets[key]
                if value == "":
                    state = "removed"
            r = {"key": key, "label": label, "value": value, "edit": edit, "removable": removable,
                 "state": state, "hint": hint}
            if extra:
                r.update(extra)
            return r

        info = []
        for name, label in PDF_FIELDS:
            value = f["info"].get(name, "")
            if name in PDF_DATES:
                value = _pdf_date(value)
            info.append(row(f"info:{name}", label, value, edit="date" if name in PDF_DATES else "text",
                            removable=bool(f["info"].get(name))))
        for name, value in f["custom"].items():
            label = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)
            info.append(row(f"custom:{name}", label[:1].upper() + label[1:].lower(), value[:200]))
        out = [{"title": "Document", "items": info}]
        hidden = []
        if f["xmp"]:
            others = f["xmp"] - (1 if self._xmp else 0)
            text = ", ".join((["Document"] if self._xmp else [])
                             + ([f"{others} on pages or images"] if others else []))
            hidden.append(row("xmp", "XMP", text, hint="Adobe metadata: can repeat the author, apps and edit history",
                              extra={"view": bool(self._xmp)}))
        if f["images"]:
            n, g = f["images"], f["images_gps"]
            text = f"{n} photo{'s' if n != 1 else ''}" + (f", {g} with location" if g else "")
            hidden.append(row("images", "Photo metadata", text,
                              hint="Camera details and GPS inside the photos. Removed without re-encoding."))
        if f["comments"]:
            who = ", ".join(f["authors"][:4]) + ("…" if len(f["authors"]) > 4 else "")
            hidden.append(row("comments", "Comment authors", who or f"dates on {f['comments']} comments",
                              hint="Names and dates on comments; the comments stay"))
        if f["attachments"]:
            names = f["attachments"]
            hidden.append(row("attachments", "Attached files", ", ".join(names[:3]) + ("…" if len(names) > 3 else "")))
        if f["javascript"]:
            hidden.append(row("javascript", "JavaScript", f"{f['javascript']} script{'s' if f['javascript'] != 1 else ''}"))
        if f["thumbnails"]:
            hidden.append(row("thumbnails", "Page thumbnails", f"{f['thumbnails']} page{'s' if f['thumbnails'] != 1 else ''}",
                              hint="Small page pictures, can be out of date"))
        if f["private"]:
            hidden.append(row("private", "App data", f"{f['private']} block{'s' if f['private'] != 1 else ''}",
                              hint="Private data of the app that made it (Illustrator keeps the whole working file)"))
        if hidden:
            out.append({"title": "Hidden data", "items": hidden})
        auto = []
        if f["versions"]:
            auto.append(row("auto:versions", "Earlier versions", "in the file", removable=False,
                            hint="Never kept: every saved copy is written fresh"))
        if f["trailing"]:
            auto.append(row("auto:trailing", "Data after the end", "in the file", removable=False,
                            hint="Never kept in saved copies"))
        if auto:
            out.append({"title": "Removed in every copy", "items": auto})
        return out

    @staticmethod
    def apply(doc, meta: dict) -> None:
        """Write the changes into an open PDF (before saving it)."""
        from ..handlers.metadata import PDF_PARTS, clean_pdf

        drop, sets = set(meta["drop"]), meta["set"]
        current = {k: v for k, v in (doc.metadata or {}).items() if k in dict(PDF_FIELDS) and v}
        info_changed = False
        for name, _label in PDF_FIELDS:
            key = f"info:{name}"
            if key in drop:
                current.pop(name, None)
                info_changed = True
            if key in sets:
                value = sets[key]
                if name in PDF_DATES and value:
                    value = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").strftime("D:%Y%m%d%H%M%S")
                if value:
                    current[name] = value
                else:
                    current.pop(name, None)
                info_changed = True
        parts = {k for k in drop if k in PDF_PARTS}
        custom_drop = [k.split(":", 1)[1] for k in drop if k.startswith("custom:")]
        info_ref = doc.xref_get_key(-1, "Info")
        custom_left = []
        if info_ref[0] == "xref":
            from ..handlers.metadata import _custom_info

            custom_left = [k for k in _custom_info(doc) if k not in custom_drop]
        if info_changed or custom_drop:
            if current or custom_left:
                doc.set_metadata({name: current.get(name, "") for name, _l in PDF_FIELDS})
                if custom_drop and info_ref[0] == "xref":
                    xref = int(info_ref[1].split()[0])
                    for key in custom_drop:
                        doc.xref_set_key(xref, key, "null")
            else:
                parts.add("info")  # nothing left: the whole info dictionary goes
        if parts:
            clean_pdf(doc, parts)


def _pdf_date(value: str) -> str:
    m = re.match(r"D:(\d{4})(\d\d)?(\d\d)?(\d\d)?(\d\d)?(\d\d)?", value or "")
    if not m:
        return value or ""
    y, mo, d, h, mi, s = (g or "" for g in m.groups())
    text = f"{y}-{mo or '01'}-{d or '01'}"
    if h:
        text += f" {h}:{mi or '00'}" + (f":{s}" if s else "")
    return text
