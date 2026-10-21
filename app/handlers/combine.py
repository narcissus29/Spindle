"""Several files in, one PDF out. Runs in the helper process.

The handler gets every dropped file at once, in the order the file manager
listed them, and writes one file next to the first:

    photo1.jpg, scan.tiff, report.pdf, ...  ->  photo1 (combined).pdf

- an image becomes one page sized to the image (a multi-page TIFF, one
  page per TIFF page), with no metadata in the embedded bytes (see
  image.add_pdf_pages)
- a PDF contributes all its pages, in order; its bookmarks are kept and
  point at the right pages

- an office document is first made a PDF with the office app installed
  (handlers/office.py), then added like a PDF

Offered as "Merge" on several files: any mix of PDFs, images and office
documents (see handlers/__init__.py, combined_options).

Signature:

    def handler(paths: list[Path], option: str, ctx: Context) -> None

ctx.src is the first file. A file that can't be used fails the whole job
with its name in the message ("b.pdf: Password-protected PDF"): a combined
file with a page silently missing would be worse than none.
"""

from __future__ import annotations

from pathlib import Path

import contextlib
import shutil
import tempfile

from .. import filetypes
from .common import Context, HandlerError, Skip


@contextlib.contextmanager
def _as_pdf(path: Path, kind: str, ctx: Context):
    """A PDF stays itself; an office document becomes a temporary PDF in a
    private folder, removed afterwards."""
    if kind == filetypes.PDF:
        yield path
        return
    from . import office

    folder = Path(tempfile.mkdtemp(prefix="spindle-merge-"))
    try:
        pdf = folder / f"{path.stem}.pdf"
        office.convert(path, pdf, ctx)
        yield pdf
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def to_one_pdf(paths: list[Path], option: str, ctx: Context) -> None:
    import pymupdf

    from .image import add_pdf_pages
    from .pdf import _open

    out_doc = pymupdf.open()
    toc: list = []
    try:
        for i, path in enumerate(paths):
            done = lambda part, whole=1, i=i: ctx.progress(0.9 * (i + part / whole) / len(paths),
                                                           f"Adding {i + 1}/{len(paths)}")
            try:
                kind = filetypes.sniff_kind(path)
                if kind in (filetypes.PDF, filetypes.DOCUMENT):
                    with _as_pdf(path, kind, ctx) as pdf_path, _open(pdf_path) as src:
                        offset = out_doc.page_count
                        out_doc.insert_pdf(src)
                        toc += [[level, title, page + offset] for level, title, page, *_ in src.get_toc(simple=True)]
                    done(1)
                else:
                    add_pdf_pages(out_doc, path, ctx, on_page=done)
            except (HandlerError, Skip) as exc:
                raise HandlerError(f"{path.name}: {exc}") from None
        if toc:
            try:
                out_doc.set_toc(toc)
            except Exception:  # odd bookmark levels in a source: keep the pages, drop bookmarks
                pass
        out = ctx.output_file(".pdf", tag="combined")
        out_doc.save(out, garbage=3, deflate=True)
    finally:
        out_doc.close()
    ctx.note("Combined")
    ctx.progress(1.0)
