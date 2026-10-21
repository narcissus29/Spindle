"""Image files as a list of blocks, so metadata can be swapped in and out
without touching the image data (no re-encoding, the pixels stay byte
for byte the same).

    blocks = split(data)          # [Block(key, raw), ...] in file order
    data = join(blocks)           # the same bytes back

Each block has a `key` saying what it is to the metadata editor:

    "exif"         EXIF (camera, dates, GPS, ...)
    "xmp"          XMP packet(s)
    "iptc"         IPTC / Photoshop block (JPEG)
    "comment"      JPEG comment
    "text:<kw>"    PNG text chunk with keyword <kw>
    "block:<name>" other metadata-like blocks (unknown app blocks, PNG
                   time, private chunks)
    "trailing"     data after the end of the image (motion photo video,
                   extra preview images) and, for JPEG, the MPF block
                   that points to it
    ""             part of the image itself: always kept

Only JPEG, PNG and WEBP are handled; other formats return None from
split().
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

_XMP_SIG = b"http://ns.adobe.com/xap/1.0/\x00"
_XMP_EXT_SIG = b"http://ns.adobe.com/xmp/extension/\x00"
_PNG_SIG = b"\x89PNG\r\n\x1a\n"
_PNG_KEEP = {b"tRNS", b"gAMA", b"cHRM", b"sRGB", b"iCCP", b"sBIT", b"pHYs", b"bKGD",
             b"hIST", b"sPLT", b"acTL", b"fcTL", b"fdAT", b"cICP", b"mDCv", b"cLLi"}
_WEBP_IMAGE = {b"VP8X", b"VP8 ", b"VP8L", b"ALPH", b"ICCP", b"ANIM", b"ANMF"}


@dataclass(frozen=True)
class Block:
    key: str
    raw: bytes
    payload: bytes = b""  # the metadata itself (EXIF: the TIFF data; text: the value)


def kind_of(data: bytes) -> str:
    if data[:2] == b"\xff\xd8":
        return "jpeg"
    if data[:8] == _PNG_SIG:
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return ""


def split(data: bytes) -> list[Block] | None:
    kind = kind_of(data)
    if kind == "jpeg":
        return _split_jpeg(data)
    if kind == "png":
        return _split_png(data)
    if kind == "webp":
        return _split_webp(data)
    return None


def join(blocks: list[Block], kind: str) -> bytes:
    if kind == "webp":
        return _join_webp(blocks)
    return b"".join(b.raw for b in blocks)


# ------------------------------------------------------------------ JPEG ---

def _split_jpeg(data: bytes) -> list[Block]:
    blocks = [Block("", b"\xff\xd8")]
    pos = 2
    while pos < len(data):
        start = pos
        if data[pos] != 0xFF:
            raise ValueError("Damaged JPEG")
        while pos < len(data) and data[pos] == 0xFF:
            pos += 1
        if pos >= len(data):
            break
        marker = data[pos]
        pos += 1
        if marker == 0xD9:  # end of image
            blocks.append(Block("", data[start:pos]))
            break
        if 0xD0 <= marker <= 0xD7 or marker == 0x01:
            blocks.append(Block("", data[start:pos]))
            continue
        length = struct.unpack(">H", data[pos:pos + 2])[0]
        payload = data[pos + 2:pos + length]
        end = pos + length
        if marker == 0xDA:  # start of scan: the image data follows
            end = _scan_end(data, end)
        blocks.append(Block(_jpeg_key(marker, payload), data[start:end],
                            payload[6:] if marker == 0xE1 and payload.startswith(b"Exif\x00\x00") else payload))
        pos = end
    else:
        return blocks  # no end-of-image marker: nothing trails
    if pos < len(data):
        blocks.append(Block("trailing", data[pos:]))
    return blocks


def _jpeg_key(marker: int, payload: bytes) -> str:
    if marker == 0xE0:
        return "" if payload.startswith(b"JFIF\x00") else "block:APP0"
    if marker == 0xE1:
        if payload.startswith(b"Exif\x00\x00"):
            return "exif"
        if payload.startswith((_XMP_SIG, _XMP_EXT_SIG)):
            return "xmp"
        return "block:APP1"
    if marker == 0xE2:
        if payload.startswith(b"ICC_PROFILE\x00"):
            return ""  # color profile: changes how the picture looks
        if payload.startswith(b"MPF\x00"):
            return "trailing"  # index of the extra images after the end
        return "block:APP2"
    if marker == 0xED:
        return "iptc"
    if marker == 0xEE:
        return ""  # Adobe: needed to read CMYK JPEGs right
    if 0xE3 <= marker <= 0xEF:
        return f"block:APP{marker - 0xE0}"
    if marker == 0xFE:
        return "comment"
    return ""


def _scan_end(data: bytes, pos: int) -> int:
    while True:
        i = data.find(b"\xff", pos)
        if i < 0 or i + 1 >= len(data):
            return len(data)
        nxt = data[i + 1]
        if nxt == 0x00 or nxt == 0xFF or 0xD0 <= nxt <= 0xD7:
            pos = i + 1
            continue
        return i


def jpeg_exif_block(tiff: bytes) -> Block:
    payload = b"Exif\x00\x00" + tiff
    return Block("exif", b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload, tiff)


def jpeg_insert_at(blocks: list[Block]) -> int:
    """Where a new metadata block goes: after SOI and the JFIF header."""
    i = 1
    while i < len(blocks) and blocks[i].raw[:2] == b"\xff\xe0" and blocks[i].key == "":
        i += 1
    return i


# ------------------------------------------------------------------- PNG ---

def _split_png(data: bytes) -> list[Block]:
    blocks = [Block("", data[:8])]
    pos = 8
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        ctype = data[pos + 4:pos + 8]
        raw = data[pos:pos + 12 + length]
        body = data[pos + 8:pos + 8 + length]
        blocks.append(Block(_png_key(ctype, body), raw, _png_payload(ctype, body)))
        pos += 12 + length
        if ctype == b"IEND":
            break
    if pos < len(data):
        blocks.append(Block("trailing", data[pos:]))
    return blocks


def _png_key(ctype: bytes, body: bytes) -> str:
    if ctype == b"eXIf":
        return "exif"
    if ctype in (b"tEXt", b"zTXt", b"iTXt"):
        keyword = body.split(b"\x00", 1)[0].decode("latin-1")
        return "xmp" if keyword == "XML:com.adobe.xmp" else f"text:{keyword}"
    if ctype == b"tIME":
        return "block:time"
    if ctype[:1].isupper() or ctype in _PNG_KEEP:
        return ""
    return f"block:{ctype.decode('latin-1')}"


def _png_payload(ctype: bytes, body: bytes) -> bytes:
    """The value of a text chunk (decompressed), or the chunk's data."""
    import zlib

    try:
        if ctype == b"tEXt":
            return body.split(b"\x00", 1)[1]
        if ctype == b"zTXt":
            return zlib.decompress(body.split(b"\x00", 1)[1][1:])
        if ctype == b"iTXt":
            _kw, rest = body.split(b"\x00", 1)
            compressed = rest[0]
            _lang, _tkw, text = rest[2:].split(b"\x00", 2)
            return zlib.decompress(text) if compressed else text
    except (IndexError, ValueError, zlib.error):
        return b""
    return body


def png_chunk(ctype: bytes, body: bytes, key: str) -> Block:
    import zlib

    raw = struct.pack(">I", len(body)) + ctype + body + struct.pack(">I", zlib.crc32(ctype + body))
    return Block(key, raw, body)


def png_insert_at(blocks: list[Block]) -> int:
    """New metadata goes before the image data (eXIf must)."""
    for i, b in enumerate(blocks):
        if b.raw[4:8] == b"IDAT":
            return i
    return len(blocks) - 1


# ------------------------------------------------------------------ WEBP ---

def _split_webp(data: bytes) -> list[Block]:
    riff_end = min(len(data), 8 + struct.unpack("<I", data[4:8])[0])
    blocks = []
    pos = 12
    while pos + 8 <= riff_end:
        ctype = data[pos:pos + 4]
        size = struct.unpack("<I", data[pos + 4:pos + 8])[0]
        raw = data[pos:pos + 8 + size + (size & 1)]
        body = data[pos + 8:pos + 8 + size]
        if ctype == b"EXIF":
            key = "exif"
            if body.startswith(b"Exif\x00\x00"):
                body = body[6:]
        elif ctype == b"XMP ":
            key = "xmp"
        elif ctype in _WEBP_IMAGE:
            key = ""
        else:
            key = f"block:{ctype.decode('latin-1').strip()}"
        blocks.append(Block(key, raw, body))
        pos += len(raw)
    if riff_end < len(data):
        blocks.append(Block("trailing", data[riff_end:]))
    return blocks


def webp_chunk(ctype: bytes, body: bytes, key: str) -> Block:
    return Block(key, ctype + struct.pack("<I", len(body)) + body + (b"\x00" if len(body) & 1 else b""), body)


def _join_webp(blocks: list[Block]) -> bytes:
    """RIFF container around the chunks. Metadata needs the extended
    format (a VP8X chunk whose flags say what is there): it is added or
    its flags are updated to match."""
    chunks = [b for b in blocks if b.key != "trailing"]
    trailing = b"".join(b.raw for b in blocks if b.key == "trailing")
    types = {b.raw[:4] for b in chunks}
    has_vp8x = b"VP8X" in types
    needs_vp8x = has_vp8x or types & {b"EXIF", b"XMP ", b"ICCP", b"ALPH", b"ANIM"}
    if needs_vp8x:
        flags = ((0x20 if b"ICCP" in types else 0) | (0x10 if _webp_alpha(chunks) else 0)
                 | (0x08 if b"EXIF" in types else 0) | (0x04 if b"XMP " in types else 0)
                 | (0x02 if b"ANIM" in types else 0))
        if has_vp8x:
            vp8x = next(b for b in chunks if b.raw[:4] == b"VP8X")
            width, height = vp8x.raw[12:15], vp8x.raw[15:18]
        else:
            w, h = _webp_size(chunks)
            width, height = (w - 1).to_bytes(3, "little"), (h - 1).to_bytes(3, "little")
        header = webp_chunk(b"VP8X", bytes([flags, 0, 0, 0]) + width + height, "")
        chunks = [header] + [b for b in chunks if b.raw[:4] != b"VP8X"]
        # metadata chunks go after the image data
        meta = [b for b in chunks if b.raw[:4] in (b"EXIF", b"XMP ")]
        chunks = [b for b in chunks if b.raw[:4] not in (b"EXIF", b"XMP ")] + meta
    body = b"".join(b.raw for b in chunks)
    return b"RIFF" + struct.pack("<I", len(body) + 4) + b"WEBP" + body + trailing


def _webp_alpha(chunks: list[Block]) -> bool:
    for b in chunks:
        ctype = b.raw[:4]
        if ctype == b"ALPH":
            return True
        if ctype == b"VP8X":
            return bool(b.raw[8] & 0x10)
        if ctype == b"VP8L" and len(b.raw) >= 13:
            bits = struct.unpack("<I", b.raw[9:13])[0]
            return bool(bits >> 28 & 1)
    return False


def _webp_size(chunks: list[Block]) -> tuple[int, int]:
    for b in chunks:
        ctype, body = b.raw[:4], b.raw[8:]
        if ctype == b"VP8 " and len(body) >= 10:
            w, h = struct.unpack("<HH", body[6:10])
            return w & 0x3FFF, h & 0x3FFF
        if ctype == b"VP8L" and len(body) >= 5:
            bits = struct.unpack("<I", body[1:5])[0]
            return (bits & 0x3FFF) + 1, (bits >> 14 & 0x3FFF) + 1
    raise ValueError("WEBP without image data")
