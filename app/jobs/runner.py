"""The helper process: `main.py --job-runner`.

Reads requests from stdin, runs handlers one at a time, answers on stdout
(see protocol.py). Libraries print freely (pdf2docx logs every page, MuPDF
prints warnings from C), so before anything else the real stdout is set
aside for the protocol and file descriptor 1 is pointed at stderr: nothing
a library prints can corrupt the protocol stream.
"""

from __future__ import annotations

import faulthandler
import importlib
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Callable

from .. import filetypes
from ..handlers.common import Context, HandlerError, Skip
from . import protocol

_handlers: dict[str, Callable] = {}


def _resolve(spec: str) -> Callable:
    if spec not in _handlers:
        module_name, _, func_name = spec.partition(":")
        _handlers[spec] = getattr(importlib.import_module(module_name), func_name)
    return _handlers[spec]


def main() -> int:
    started = time.monotonic()
    proto = os.fdopen(os.dup(1), "wb", buffering=0)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    faulthandler.enable()  # a crash in a C library: its stack goes to the wheel's log

    def send(message: dict) -> None:
        proto.write(protocol.encode(message))

    # Up and reading: the wheel stops waiting for a helper that never starts.
    send({"type": "hello", "pid": os.getpid(), "ms": round((time.monotonic() - started) * 1000)})

    stdin = sys.stdin.buffer
    for line in iter(stdin.readline, b""):
        request = protocol.decode(line)
        if request is None:
            continue
        rid = request.get("id")
        try:
            if request["type"] == "run":
                _run(request, send)
            elif request["type"] == "thumb":
                from ..handlers.pdf import render_thumbnail

                out = render_thumbnail(Path(request["path"]), int(request["size"]), Path(request["dir"]))
                send({"type": "thumb", "id": rid, "path": str(out)})
        except HandlerError as exc:
            send({"type": "error", "id": rid, "message": str(exc)})
        except Exception as exc:
            traceback.print_exc()
            send({"type": "error", "id": rid, "message": f"{type(exc).__name__}: {exc}"})
    return 0


def _check(path: Path, kind: str) -> None:
    if not path.exists():
        raise HandlerError("File not found")
    if filetypes.sniff_kind(path) != kind:
        expected = {filetypes.PDF: "a PDF file", filetypes.IMAGE: "an image file",
                    filetypes.DOCUMENT: "an office document"}.get(kind, f"a {kind} file")
        raise HandlerError(f"Doesn't look like {expected}")


def _run(request: dict, send: Callable[[dict], None]) -> None:
    rid = request["id"]
    combined = "paths" in request  # one handler call for every file
    paths = [Path(p) for p in request["paths"]] if combined else [Path(request["path"])]
    path = paths[0]
    ctx = Context(
        path,
        request.get("settings"),
        on_progress=lambda f, text="": send({"type": "progress", "id": rid,
                                             "fraction": None if f is None else round(f, 4), "text": text}),
        on_temp=lambda p: send({"type": "temp", "id": rid, "path": str(p)}),
        on_child=lambda pid: send({"type": "child", "id": rid, "pid": pid}),
    )
    try:
        if combined:
            for p, kind in zip(paths, request["kinds"]):
                try:
                    _check(p, kind)
                except HandlerError as exc:
                    raise HandlerError(f"{p.name}: {exc}") from None
            _resolve(request["spec"])(paths, request["option"], ctx)
        else:
            _check(path, request["kind"])
            _resolve(request["spec"])(path, request["option"], ctx)
        outputs = ctx.commit()
    except Skip as skip:
        ctx.discard()
        send({"type": "done", "id": rid, "outputs": [],
              "info": {**getattr(skip, "info", {}), "note": str(skip), "skipped": True}})
        return
    except BaseException:
        ctx.discard()
        raise
    send({"type": "done", "id": rid, "outputs": [str(p) for p in outputs], "info": ctx.info})
