"""Handler registry.

REGISTRY[file_kind][wheel][option_name] -> "module:function"

Handlers are named by string so the UI process never imports them (or
PyMuPDF / pdf2docx / OpenCV); only the helper process does (see
app/jobs/runner.py). Signature, in app/handlers/common.py:

    def handler(path: Path, option: str, ctx: Context) -> None

"editor:<tool>" instead opens the editor process on that tool (see
app/editor). An editor option can have a batch handler (BATCH): dropped
on with several files, it runs that on each file instead (Metadata: one
file opens the metadata viewer, several are cleaned silently).

Combining: when several files are dropped, "Merge" makes one PDF from all
of them (handlers/combine.py), in the order the files were dropped: any
mix of PDFs, images and office documents. "PDF" always makes one PDF per
file. Editor options work on one file at a time, so they are left off the
wheel when several files are dropped together.

Sub-rings: clicking an option listed in SUBRINGS while files are parked
swaps the wedges for its choices (Compress -> Auto, 20 KB ... 1 MB,
Custom). Dropping a file straight on that option still runs it at once.

Dict order is wedge order (clockwise from the top).
"""

from __future__ import annotations

from ..filetypes import DOCUMENT, IMAGE, PDF

CONVERT = "convert"
ACTIONS = "actions"
WHEELS = (CONVERT, ACTIONS)
WHEEL_LABELS = {CONVERT: "Convert", ACTIONS: "Actions"}

DEFAULT_WHEEL = {
    PDF: CONVERT,
    IMAGE: ACTIONS,
    DOCUMENT: CONVERT,
}

# Icon file (assets/icons/<name>.svg) per option.
ICONS = {
    # Convert: a file badge showing what kind of file comes out
    "DOCX": "fmt-doc",
    "TXT": "fmt-text",
    "PDF": "fmt-pdf",
    "JPG": "fmt-image",
    "PNG": "fmt-image",
    "WEBP": "fmt-image",
    "BMP": "fmt-image",
    "TIFF": "fmt-image",
    "Merge": "merge",
    # Actions
    "Compress": "compress",
    "Metadata": "metadata",
    "Edit": "edit",
    "Annotate": "annotate",
    "Add BG": "addbg",
    "Crop": "crop",
    "Redact": "redact",
    # Compress sub-ring
    "Auto": "compress",
    "Custom": "type",
}

EDITOR_PREFIX = "editor:"
_COMPRESS = "app.handlers.compress:compress"
_METADATA = "app.handlers.metadata:strip"
_METADATA_VIEWER = "editor:metadata"
_IMAGE_CONVERT = "app.handlers.image:convert"

REGISTRY: dict[str, dict[str, dict[str, str]]] = {
    PDF: {
        CONVERT: {
            "DOCX": "app.handlers.pdf:to_docx",
            "TXT": "app.handlers.pdf:to_txt",
            "JPG": "app.handlers.pdf:to_images",
            "PNG": "app.handlers.pdf:to_images",
        },
        ACTIONS: {  # no "Add BG": PDF pages have no transparency to fill
            "Compress": _COMPRESS,
            "Metadata": _METADATA_VIEWER,
            "Edit": "editor:edit",
            "Annotate": "editor:annotate",
            "Crop": "editor:crop",
            "Redact": "editor:redact",
        },
    },
    IMAGE: {
        CONVERT: {
            "PNG": _IMAGE_CONVERT,
            "JPG": _IMAGE_CONVERT,
            "WEBP": _IMAGE_CONVERT,
            "BMP": _IMAGE_CONVERT,
            "TIFF": _IMAGE_CONVERT,
            "PDF": _IMAGE_CONVERT,
        },
        ACTIONS: {
            "Compress": _COMPRESS,
            "Metadata": _METADATA_VIEWER,
            "Edit": "editor:edit",
            "Annotate": "editor:annotate",
            "Add BG": "app.handlers.background:add_bg",
            "Crop": "editor:crop",
            "Redact": "editor:redact",
        },
    },
    # Word / Excel / PowerPoint / OpenDocument: to PDF with the office app
    # installed (handlers/office.py). No Actions wheel.
    DOCUMENT: {
        CONVERT: {
            "PDF": "app.handlers.office:to_pdf",
        },
    },
}


COMBINE = "app.handlers.combine:to_one_pdf"  # takes every file at once

# Compress -> target sizes. "Auto" is the usual preset; "Custom" asks for a
# number in the center pill. Sizes are option names the handler parses.
COMPRESS_TARGETS = ("Auto", "20 KB", "50 KB", "100 KB", "200 KB", "500 KB", "1 MB", "Custom")
SUBRINGS = {"Compress": COMPRESS_TARGETS}
CUSTOM = "Custom"
_TARGET = "app.handlers.compress:to_target"


def subring_spec(parent: str, option: str) -> tuple[str, str]:
    """(handler, job option name) for a sub-ring choice: "Auto" is plain
    Compress, a size is "compress to that size"."""
    if parent == "Compress":
        return (_COMPRESS, "Compress") if option == "Auto" else (_TARGET, option)
    raise KeyError(parent)


# editor option -> what runs on each file when several are dropped
BATCH = {_METADATA_VIEWER: _METADATA}


def options_for(kind: str, wheel: str, source_format: str = "", count: int = 1) -> list[str]:
    """Option names shown on a wheel. Converting to the file's own format
    is pointless, so that target is left out (a PNG has no 'PNG' wedge).
    With `count` > 1 files, editor options without a batch handler are
    left out (combining options are added per batch: combined_options)."""
    options = REGISTRY.get(kind, {}).get(wheel, {})
    names = list(options)
    if wheel == CONVERT:
        names = [n for n in names if n != source_format]
    if count > 1:
        names = [n for n in names if not is_editor(options[n]) or options[n] in BATCH]
    return names


def combined_options(kinds: set, wheel: str, count: int) -> list[str]:
    """Options that make one PDF from a multi-file drop of these kinds:
    "Merge", for any mix of PDFs, images and office documents. (Their
    "PDF" wedge, where every file has one, makes one PDF per file.)"""
    if count < 2 or wheel != CONVERT or not kinds or not kinds <= {PDF, IMAGE, DOCUMENT}:
        return []
    return ["Merge"]


def combined_handler(kinds: set, wheel: str, option: str, count: int) -> str | None:
    """The all-files-at-once handler for `option` on a multi-file drop."""
    return COMBINE if option in combined_options(kinds, wheel, count) else None


def is_editor(spec: str | None) -> bool:
    return bool(spec) and spec.startswith(EDITOR_PREFIX)


def get_handler(kind: str, wheel: str, option: str, count: int = 1) -> str | None:
    """What runs for `option` on a file of `kind`, dropped with `count`
    files in all."""
    spec = REGISTRY.get(kind, {}).get(wheel, {}).get(option)
    if count > 1 and spec in BATCH:
        return BATCH[spec]
    return spec
