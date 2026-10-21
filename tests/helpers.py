"""Handlers used only by the tests (the helper process imports them by name)."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from app.handlers.common import Context, HandlerError


def slow(path: Path, option: str, ctx: Context) -> None:
    out = ctx.output_file(".txt")
    out.write_text("partial")
    for i in range(40):
        time.sleep(0.05)
        ctx.progress((i + 1) / 40)


def noisy(path: Path, option: str, ctx: Context) -> None:
    print("this is not JSON {", flush=True)          # Python-level stdout
    os.write(1, b"raw write to fd 1 from 'C code'\n")  # what a C library would do
    print("stderr chatter", file=sys.stderr)
    ctx.output_file(".txt").write_text("ok")


def crash_on_marked(path: Path, option: str, ctx: Context) -> None:
    out = ctx.output_file(".txt")
    out.write_text("partial")
    if "crash" in path.name:
        os._exit(3)  # like a segfault in a C library: no cleanup
    out.write_text("ok")


def fail(path: Path, option: str, ctx: Context) -> None:
    raise HandlerError("Nope")


def starts_a_child(path: Path, option: str, ctx: Context) -> None:
    """Like LibreOffice: a process of its own, reported, then a long wait."""
    from app import platform_utils

    child = platform_utils.start_hidden([sys.executable, "-c", "import time; time.sleep(120)"])
    ctx.child(child.pid)
    (path.parent / "child.pid").write_text(str(child.pid))
    time.sleep(120)
