"""Running handlers in a separate helper process.

The UI process never imports PyMuPDF, pdf2docx or OpenCV. Jobs go to a
helper process (`main.py --job-runner`) over stdin/stdout:

    process.py   ProcessWorker: starts / feeds / supervises the helper (UI side)
    runner.py    the helper's main loop (helper side)
    protocol.py  the JSON-lines messages between the two

A job is one option applied to one or more files, processed one by one,
or, when `combine` is set, all together by one handler call that makes a
single output (several images -> one PDF, Merge).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class JobItem:
    path: Path
    kind: str
    spec: str  # "module:function"


@dataclass(frozen=True)
class Job:
    wheel: str
    option: str
    items: tuple[JobItem, ...]
    combine: bool = False  # one handler call for all items (items[0].spec)
