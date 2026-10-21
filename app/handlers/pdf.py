"""PDF handlers (PyMuPDF, pdf2docx). Imported only inside the helper process.

    to_txt     PDF -> report.txt (UTF-8, pages separated by a blank line)
    to_images  PDF -> report.png / report.jpg for one page,
                      report (PNG)/page-001.png ... for several
    to_docx    PDF -> report.docx (pdf2docx)
    render_thumbnail  first page as a small PNG for the wheel's hub
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from pathlib import Path

import pymupdf

from .common import Context, HandlerError

_MAX_PIXELS = 80_000_000  # cap per rendered page (a poster at 150 DPI is huge)


def _open(path: Path) -> pymupdf.Document:
    try:
        doc = pymupdf.open(path)
    except FileNotFoundError:
        raise HandlerError("File not found") from None
    except Exception as exc:  # pymupdf.FileDataError and friends
        raise HandlerError(f"Can't open PDF ({exc})") from None
    if doc.needs_pass:
        doc.close()
        raise HandlerError("Password-protected PDF")
    if doc.page_count == 0:
        doc.close()
        raise HandlerError("PDF has no pages")
    return doc


def to_txt(path: Path, option: str, ctx: Context) -> None:
    with _open(path) as doc:
        out = ctx.output_file(".txt")
        n = doc.page_count
        with open(out, "w", encoding="utf-8", newline="\n") as fh:
            for i, page in enumerate(doc):
                if i:
                    fh.write("\n\n")
                fh.write(page.get_text("text").rstrip("\n"))
                ctx.progress((i + 1) / n, f"Page {i + 1}/{n}")
            fh.write("\n")


def to_images(path: Path, option: str, ctx: Context) -> None:
    fmt, ext = {"PNG": ("png", ".png"), "JPG": ("jpeg", ".jpg")}[option]
    dpi = int(ctx.settings.get("pdf_image_dpi", 150))
    quality = int(ctx.settings.get("jpeg_quality", 90))
    with _open(path) as doc:
        n = doc.page_count
        if n == 1:
            targets = [ctx.output_file(ext)]
        else:
            folder = ctx.output_dir(option)
            width = max(3, len(str(n)))
            targets = [folder / f"page-{i + 1:0{width}d}{ext}" for i in range(n)]
        for i, page in enumerate(doc):
            page_dpi = dpi
            pixels = (page.rect.width * dpi / 72) * (page.rect.height * dpi / 72)
            if pixels > _MAX_PIXELS:  # keep huge pages within memory
                page_dpi = max(36, int(dpi * (_MAX_PIXELS / pixels) ** 0.5))
            pix = page.get_pixmap(dpi=page_dpi, alpha=False)
            if fmt == "jpeg":
                pix.save(targets[i], output="jpeg", jpg_quality=quality)
            else:
                pix.save(targets[i], output="png")
            ctx.progress((i + 1) / n, f"Page {i + 1}/{n}")


class _Pdf2DocxProgress(logging.Handler):
    """pdf2docx reports "(i/n) Page i" while parsing pages and again while
    creating them; map the two phases onto 0..1. Opening and analysing
    the document come first and can't be measured."""

    _PHASE = re.compile(r"\[(\d)/4\]")
    _PAGE = re.compile(r"\((\d+)/(\d+)\) Page")

    def __init__(self, ctx: Context) -> None:
        super().__init__(logging.INFO)
        self.ctx = ctx
        self.phase = 0

    def emit(self, record: logging.LogRecord) -> None:
        msg = record.getMessage()
        if m := self._PHASE.search(msg):
            self.phase = int(m.group(1))
            if self.phase <= 2:  # opening / analysing
                self.ctx.progress(None, "Analyzing…")
        elif m := self._PAGE.search(msg):
            done, total = int(m.group(1)), int(m.group(2))
            reading = self.phase <= 3
            base, span = (0.0, 0.6) if reading else (0.6, 0.38)
            self.ctx.progress(base + span * done / total, f"{'Page' if reading else 'Writing'} {done}/{total}")


def to_docx(path: Path, option: str, ctx: Context) -> None:
    _open(path).close()  # same checks and messages as the other handlers
    from pdf2docx import Converter  # heavy (OpenCV, numpy): only when needed

    out = ctx.output_file(".docx")
    ctx.progress(None, "Analyzing…")
    # pdf2docx logs through the root logger. While it runs, our hook is the
    # only handler and INFO is let through: progress works however logging
    # was configured before, and the per-page lines don't flood the console.
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    root.handlers = [_Pdf2DocxProgress(ctx)]
    root.setLevel(logging.INFO)
    try:
        converter = Converter(str(path))
        try:
            converter.convert(str(out))
        finally:
            converter.close()
    finally:
        root.handlers = saved_handlers
        root.setLevel(saved_level)
    ctx.progress(1.0)


def render_thumbnail(path: Path, size: int, out_dir: Path) -> Path:
    """First page (or a HEIC photo), fitted into size x size px, cached by
    path + mtime."""
    st = path.stat()
    key = hashlib.sha1(f"{path.resolve()}|{st.st_mtime_ns}|{st.st_size}|{size}".encode()).hexdigest()
    out = out_dir / f"{key}.png"
    if out.exists():
        return out
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + f".{os.getpid()}.tmp")
    from ..filetypes import is_heic_file

    if is_heic_file(path):  # Qt can't show HEIC: the hub gets a PNG of it
        from .. import heic

        if not heic.read(path, max_side=size).save(str(tmp), "PNG"):
            raise HandlerError("Can't write the thumbnail")
    else:
        with _open(path) as doc:
            page = doc[0]
            zoom = size / max(page.rect.width, page.rect.height)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            pix.save(tmp, output="png")
    os.replace(tmp, out)
    _trim_cache(out_dir, keep=200)
    return out


def _trim_cache(folder: Path, keep: int) -> None:
    files = sorted(folder.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[keep:]:
        old.unlink(missing_ok=True)
