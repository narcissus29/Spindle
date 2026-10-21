"""JSON-lines protocol between the UI process and the helper.

One JSON object per line, UTF-8. The helper handles requests strictly in
order, one at a time.

UI -> helper
    {"type": "run",   "id": 7, "spec": "app.handlers.pdf:to_docx",
     "path": "/x/report.pdf", "kind": "pdf", "option": "DOCX", "settings": {...}}
    {"type": "run",   "id": 9, "spec": "app.handlers.combine:merge_pdfs",   (one output
     "paths": ["/x/a.pdf", "/x/b.pdf"], "kinds": ["pdf", "pdf"], ...}       from all files)
    {"type": "thumb", "id": 8, "path": "/x/report.pdf", "size": 128, "dir": "/cache/thumbs"}

helper -> UI
    {"type": "hello",    "pid": 4242, "ms": 120}         (first, once it reads requests)
    {"type": "temp",     "id": 7, "path": "/x/.~report.docx.123-1.part"}
    {"type": "child",    "id": 7, "pid": 5150}           (a process it started: LibreOffice, Word)
    {"type": "progress", "id": 7, "fraction": 0.42, "text": "Page 12/60"}
                         ("fraction": null: busy, can't tell how far; "text" may be "")
    {"type": "done",     "id": 7, "outputs": ["/x/report.docx"],
     "info": {"note": "−62%", "before": 4100000, "after": 1600000}}
    {"type": "done",     "id": 7, "outputs": [], "info": {"note": "No transparency", "skipped": true}}
    {"type": "thumb",    "id": 8, "path": "/cache/thumbs/ab12.png"}
    {"type": "error",    "id": 7, "message": "Password-protected PDF"}

"temp" tells the UI about a temporary output as soon as it exists, so the
UI can delete it if the helper is killed (cancel) or crashes mid-job.
The helper exits when stdin closes (the UI does that after it has been idle
for a while).
"""

from __future__ import annotations

import json


def encode(message: dict) -> bytes:
    return (json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def decode(line: bytes | str) -> dict | None:
    try:
        message = json.loads(line)
    except ValueError:
        return None
    return message if isinstance(message, dict) and "type" in message else None
