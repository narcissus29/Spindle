"""EXIF read and write, entry by entry.

EXIF is a small TIFF structure: directories (IFDs) of 12-byte entries
(tag, type, count, value or offset). This module reads it into plain
dicts of entries and writes it back. Entries are copied byte for byte,
so whatever isn't edited comes out exactly as it went in, in any byte
order and whatever its type, text in any encoding included.

(Pillow's own EXIF writer re-types every value, which turns non-ASCII
text like "Zoë" into "Zo??", and its sub-directory handling can drop or
add blocks; its tables still give the tag names, see metadata.py.)

Directories:
    "0"        main (IFD0): camera make / model, artist, copyright, ...
    "exif"     the Exif sub-directory: exposure, dates, lens, ...
    "gps"      location
    "interop"  interoperability (inside "exif")
    "1"        the thumbnail's directory (IFD1); the thumbnail JPEG
               itself is `thumbnail`

The pointer entries that link them are not kept as entries: the writer
makes them for every directory that isn't empty.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

EXIF_POINTER, GPS_POINTER, INTEROP_POINTER = 0x8769, 0x8825, 0xA005
THUMB_OFFSET, THUMB_LENGTH = 0x0201, 0x0202
_POINTERS = {"0": {EXIF_POINTER: "exif", GPS_POINTER: "gps"}, "exif": {INTEROP_POINTER: "interop"}}
_ORDER = ("0", "exif", "interop", "gps", "1")
_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 13: 4}
ASCII, SHORT, LONG, RATIONAL, BYTE = 2, 3, 4, 5, 1


@dataclass
class Entry:
    tag: int
    type: int
    count: int
    data: bytes  # the value, in the file's byte order


@dataclass
class Exif:
    endian: str = "<"
    ifds: dict[str, dict[int, Entry]] = field(default_factory=lambda: {k: {} for k in _ORDER})
    thumbnail: bytes | None = None

    # ---------------------------------------------------------------- read

    @classmethod
    def parse(cls, tiff: bytes) -> "Exif":
        """Raises ValueError if the data isn't readable EXIF."""
        if tiff[:4] not in (b"II*\x00", b"MM\x00*"):
            raise ValueError("not EXIF data")
        ex = cls("<" if tiff[:2] == b"II" else ">")
        try:
            first = struct.unpack(ex.endian + "I", tiff[4:8])[0]
            next_ifd = ex._read_ifd(tiff, first, "0", set())
            if next_ifd:
                ex._read_ifd(tiff, next_ifd, "1", set())
                ifd1 = ex.ifds["1"]
                if THUMB_OFFSET in ifd1 and THUMB_LENGTH in ifd1:
                    start, length = ex.number("1", THUMB_OFFSET), ex.number("1", THUMB_LENGTH)
                    data = tiff[start:start + length]
                    ex.thumbnail = data if data[:2] == b"\xff\xd8" else None
                if ex.thumbnail is None:
                    ex.ifds["1"] = {}  # an uncompressed or broken thumbnail: not kept
        except (struct.error, IndexError) as exc:
            raise ValueError(f"damaged EXIF ({exc})") from None
        return ex

    def _read_ifd(self, tiff: bytes, offset: int, name: str, seen: set) -> int:
        if offset in seen or not 8 <= offset < len(tiff):
            return 0
        seen.add(offset)
        e = self.endian
        count = struct.unpack(e + "H", tiff[offset:offset + 2])[0]
        entries = self.ifds[name]
        for i in range(count):
            at = offset + 2 + 12 * i
            tag, typ, n = struct.unpack(e + "HHI", tiff[at:at + 8])
            size = _SIZES.get(typ)
            if size is None:
                continue  # unknown type: can't tell its size, drop it
            total = size * n
            if total <= 4:
                data = tiff[at + 8:at + 8 + total]
            else:
                start = struct.unpack(e + "I", tiff[at + 8:at + 12])[0]
                data = tiff[start:start + total]
                if len(data) != total:
                    continue  # points outside the block
            entry = Entry(tag, typ, n, data)
            child = _POINTERS.get(name, {}).get(tag)
            if child:
                self._read_ifd(tiff, struct.unpack(e + "I", data[:4])[0], child, seen)
            else:
                entries[tag] = entry
        end = offset + 2 + 12 * count
        return struct.unpack(e + "I", tiff[end:end + 4])[0] if end + 4 <= len(tiff) else 0

    def number(self, ifd: str, tag: int) -> int:
        entry = self.ifds[ifd][tag]
        fmt = {1: "B", 3: "H", 4: "I", 6: "b", 7: "B", 8: "h", 9: "i"}[entry.type]
        return struct.unpack(self.endian + fmt, entry.data[:_SIZES[entry.type]])[0]

    def value(self, ifd: str, tag: int):
        """The decoded value: str for text, int / float, a tuple when
        there are several, or bytes for raw data."""
        entry = self.ifds[ifd][tag]
        e, t, n, d = self.endian, entry.type, entry.count, entry.data
        if t == ASCII:
            return decode_text(d)
        if t in (1, 7):
            return d
        if t in (5, 10):
            fmt = "I" if t == 5 else "i"
            pairs = struct.unpack(f"{e}{2 * n}{fmt}", d)
            vals = tuple(pairs[i] / pairs[i + 1] if pairs[i + 1] else 0.0 for i in range(0, 2 * n, 2))
        else:
            fmt = {3: "H", 4: "I", 6: "b", 8: "h", 9: "i", 11: "f", 12: "d", 13: "I"}[t]
            vals = struct.unpack(f"{e}{n}{fmt}", d)
        return vals[0] if n == 1 else vals

    def fraction(self, ifd: str, tag: int) -> tuple[int, int] | None:
        """A single rational as (numerator, denominator)."""
        entry = self.ifds[ifd].get(tag)
        if entry is None or entry.type not in (5, 10) or len(entry.data) < 8:
            return None
        return struct.unpack(self.endian + ("II" if entry.type == 5 else "ii"), entry.data[:8])

    # --------------------------------------------------------------- write

    def set_text(self, ifd: str, tag: int, text: str) -> None:
        data = text.encode("utf-8") + b"\x00"
        self.ifds[ifd][tag] = Entry(tag, ASCII, len(data), data)

    def set_short(self, ifd: str, tag: int, value: int) -> None:
        self.ifds[ifd][tag] = Entry(tag, SHORT, 1, struct.pack(self.endian + "H", value))

    def set_long(self, ifd: str, tag: int, value: int) -> None:
        self.ifds[ifd][tag] = Entry(tag, LONG, 1, struct.pack(self.endian + "I", value))

    def set_rationals(self, ifd: str, tag: int, values: list[tuple[int, int]]) -> None:
        data = b"".join(struct.pack(self.endian + "II", a, b) for a, b in values)
        self.ifds[ifd][tag] = Entry(tag, RATIONAL, len(values), data)

    def set_bytes(self, ifd: str, tag: int, values: bytes) -> None:
        self.ifds[ifd][tag] = Entry(tag, BYTE, len(values), bytes(values))

    def remove(self, ifd: str, tag: int) -> None:
        self.ifds[ifd].pop(tag, None)

    def is_empty(self) -> bool:
        return not any(self.ifds[k] for k in ("0", "exif", "interop", "gps"))

    def to_bytes(self) -> bytes:
        """The TIFF data ("II*\\0..."), sub-directories after the main one,
        the thumbnail last."""
        e = self.endian
        ifds = {k: dict(v) for k, v in self.ifds.items()}
        if not ifds["exif"] and ifds["interop"]:
            ifds["interop"] = {}  # interop only lives inside exif
        has_thumb = bool(self.thumbnail) and bool(ifds["1"])
        if not has_thumb:
            ifds["1"] = {}
        # Pointer entries get their offsets once the layout is known.
        links = [("0", EXIF_POINTER, "exif"), ("0", GPS_POINTER, "gps"), ("exif", INTEROP_POINTER, "interop")]
        for parent, tag, child in links:
            if ifds[child]:
                ifds[parent][tag] = Entry(tag, LONG, 1, b"\x00" * 4)
        if has_thumb:
            ifds["1"][THUMB_OFFSET] = Entry(THUMB_OFFSET, LONG, 1, b"\x00" * 4)
            ifds["1"][THUMB_LENGTH] = Entry(THUMB_LENGTH, LONG, 1, struct.pack(e + "I", len(self.thumbnail)))
        order = [k for k in _ORDER if ifds[k]]
        if not order:
            order = ["0"]

        def size(name: str) -> int:
            entries = ifds[name].values()
            return 2 + 12 * len(entries) + 4 + sum(_even(len(x.data)) for x in entries if len(x.data) > 4)

        offsets, at = {}, 8
        for name in order:
            offsets[name] = at
            at += size(name)
        thumb_at = at
        for parent, tag, child in links:
            if ifds[child]:
                ifds[parent][tag].data = struct.pack(e + "I", offsets[child])
        if has_thumb:
            ifds["1"][THUMB_OFFSET].data = struct.pack(e + "I", thumb_at)

        out = bytearray(b"II*\x00" if e == "<" else b"MM\x00*")
        out += struct.pack(e + "I", 8)
        for name in order:
            entries = sorted(ifds[name].values(), key=lambda x: x.tag)
            start = offsets[name]
            values_at = start + 2 + 12 * len(entries) + 4
            table, values = bytearray(struct.pack(e + "H", len(entries))), bytearray()
            for x in entries:
                table += struct.pack(e + "HHI", x.tag, x.type, x.count)
                if len(x.data) <= 4:
                    table += x.data.ljust(4, b"\x00")
                else:
                    table += struct.pack(e + "I", values_at + len(values))
                    values += x.data + (b"\x00" if len(x.data) & 1 else b"")
            nxt = offsets["1"] if name == "0" and "1" in offsets else 0
            table += struct.pack(e + "I", nxt)
            out += table + values
        if has_thumb:
            out += self.thumbnail
        return bytes(out)


def _even(n: int) -> int:
    return n + (n & 1)


def decode_text(data: bytes) -> str:
    """EXIF text: officially ASCII, in practice often UTF-8."""
    data = data.split(b"\x00", 1)[0]
    try:
        return data.decode("utf-8").strip()
    except UnicodeDecodeError:
        return data.decode("latin-1").strip()


def to_rational(value: float, denominator: int = 1_000_000) -> tuple[int, int]:
    return round(value * denominator), denominator


def dms(value: float) -> list[tuple[int, int]]:
    """Degrees as EXIF GPS degrees / minutes / seconds rationals."""
    value = abs(value)
    degrees = int(value)
    minutes_f = (value - degrees) * 60
    minutes = int(minutes_f)
    seconds = (minutes_f - minutes) * 60
    return [(degrees, 1), (minutes, 1), (round(seconds * 10000), 10000)]


def degrees(parts) -> float:
    if isinstance(parts, (int, float)):
        return float(parts)
    parts = tuple(parts) + (0.0, 0.0)
    return parts[0] + parts[1] / 60 + parts[2] / 3600
