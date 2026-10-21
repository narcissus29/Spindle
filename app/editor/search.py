"""Find text in a PDF for search-and-redact.

MuPDF's own search ignores case and can't match whole words only, so this
works on the characters themselves: each page's text is rebuilt from
rawdict (with the box of every character), searched with a regular
expression, and each match is turned back into one box per text line.

Lines are joined with a space and blocks with a newline, so a phrase that
wraps onto the next line is still found (and boxed on both lines).
Ligatures are expanded ("ﬁ" -> "fi") so words like "office" match.

Results are in displayed page coordinates (the page's own rotation
applied, y down), like the editor state.
"""

from __future__ import annotations

import re

MAX_RESULTS = 2000


def find_on_page(page, term: str, match_case: bool = False, whole_word: bool = False) -> list[dict]:
    """[{"rects": [[x, y, w, h], ...], "text": "matched", "context": "…around it…"}]"""
    import pymupdf

    if not term.strip():
        return []
    flags = pymupdf.TEXTFLAGS_RAWDICT & ~pymupdf.TEXT_PRESERVE_LIGATURES
    chars: list[str] = []
    boxes: list[tuple | None] = []  # (line id, rect) per character; None for joiners
    line_id = 0
    for block in page.get_text("rawdict", flags=flags)["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                for ch in span["chars"]:
                    chars.append(ch["c"])
                    boxes.append((line_id, pymupdf.Rect(ch["bbox"])))
            chars.append(" ")
            boxes.append(None)
            line_id += 1
        chars[-1:] = ["\n"] if chars else []
    text = "".join(chars)
    pattern = re.escape(term.strip())
    if whole_word:
        pattern = rf"(?<!\w){pattern}(?!\w)"
    pattern = pattern.replace(r"\ ", r"\s+")  # spaces in the term match any run of spaces / line breaks
    regex = re.compile(pattern, 0 if match_case else re.IGNORECASE)

    results = []
    to_display = page.rotation_matrix
    for m in regex.finditer(text):
        per_line: dict[int, pymupdf.Rect] = {}
        for i in range(m.start(), m.end()):
            if boxes[i] is None:
                continue
            lid, r = boxes[i]
            per_line[lid] = per_line[lid] | r if lid in per_line else pymupdf.Rect(r)
        rects = []
        for r in per_line.values():
            d = r * to_display
            d.normalize()
            rects.append([round(d.x0, 2), round(d.y0, 2), round(d.width, 2), round(d.height, 2)])
        if not rects:
            continue
        before = text[max(0, m.start() - 32):m.start()].replace("\n", " ")
        after = text[m.end():m.end() + 32].replace("\n", " ")
        results.append({"rects": rects, "text": m.group(0).replace("\n", " "),
                        "context": ("…" if m.start() > 32 else "") + before.lstrip(),
                        "after": after.rstrip() + ("…" if m.end() + 32 < len(text) else "")})
        if len(results) >= MAX_RESULTS:
            break
    return results
