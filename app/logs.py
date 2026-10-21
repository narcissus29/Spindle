"""The log file: every Spindle process writes what it prints there.

    Windows: %LOCALAPPDATA%\\spindle\\spindle.log
    Linux:   ~/.local/state/spindle/spindle.log

The wheel, the editor and the settings window call `setup()` first thing:
from then on whatever they print (the "[job] ..." lines, warnings, every
uncaught exception's traceback) also goes to the file, one line each with
the time and which process wrote it. The helper doesn't write the file
itself: the wheel reads the helper's error output and logs it ("helper").
The Windows app has no console, so before this, failures there went
nowhere.

Rotation: at 1 MB the file becomes spindle.log.1 (up to .3). Several
processes append to the same file: each write opens, appends and closes,
so no process keeps it open and any of them can rotate it.

A hard crash (a fault in a C library) can't run Python code; Python's
faulthandler writes its stack to crash.log in the same folder.
"""

from __future__ import annotations

import faulthandler
import io
import os
import sys
import threading
import time
from pathlib import Path

MAX_BYTES = 1_000_000
BACKUPS = 3

_lock = threading.Lock()
_path: Path | None = None
_tag = ""


def log_dir() -> Path:
    from . import app_name, platform_utils

    return platform_utils.log_dir(app_name())


def log_path() -> Path:
    return log_dir() / "spindle.log"


def _rotate(path: Path) -> None:
    try:
        for i in range(BACKUPS - 1, 0, -1):
            older = path.with_name(f"{path.name}.{i}")
            if older.exists():
                os.replace(older, path.with_name(f"{path.name}.{i + 1}"))
        os.replace(path, path.with_name(f"{path.name}.1"))
    except OSError:
        pass  # Windows: another process is writing this very moment; next time


def write(tag: str, text: str) -> None:
    """Append `text` (one or more lines) to the log, each line stamped."""
    path = _path
    lines = [line for line in text.splitlines() if line.strip()]
    if path is None or not lines:
        return
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    block = "".join(f"{stamp} {tag:<8} {line}\n" for line in lines)
    with _lock:
        try:
            if path.exists() and path.stat().st_size > MAX_BYTES:
                _rotate(path)
            with open(path, "a", encoding="utf-8", errors="replace") as fh:
                fh.write(block)
        except OSError:
            pass  # a log must never take the app down


class _Tee(io.TextIOBase):
    """sys.stdout / sys.stderr: to the console (when there is one) and,
    a whole line at a time, to the log."""

    def __init__(self, stream, tag: str) -> None:
        super().__init__()
        self._stream = stream
        self._tag = tag
        self._pending = ""

    @property
    def encoding(self):  # noqa: D401
        return getattr(self._stream, "encoding", "utf-8")

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        if self._stream is not None:
            try:
                self._stream.write(text)
            except (OSError, ValueError):
                pass
        self._pending += text
        if "\n" in self._pending:
            done, _, self._pending = self._pending.rpartition("\n")
            write(self._tag, done)
        return len(text)

    def flush(self) -> None:
        if self._stream is not None:
            try:
                self._stream.flush()
            except (OSError, ValueError):
                pass

    def fileno(self) -> int:
        if self._stream is None:
            raise io.UnsupportedOperation("no console")
        return self._stream.fileno()

    def isatty(self) -> bool:
        return bool(self._stream is not None and self._stream.isatty())


def setup(tag: str) -> Path | None:
    """Log this process ("wheel", "editor", "settings") from now on.
    Returns the log file, or None if its folder can't be made."""
    global _path, _tag
    if _path is not None:
        return _path
    folder = log_dir()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            os.chmod(folder, 0o700)  # file names are private: only this user reads the logs
    except OSError:
        return None
    _path, _tag = folder / "spindle.log", tag
    try:
        crash = open(folder / "crash.log", "a", encoding="utf-8")  # kept open: faulthandler needs a file
        faulthandler.enable(crash)
    except (OSError, RuntimeError):
        pass
    sys.stdout = _Tee(sys.stdout, tag)
    sys.stderr = _Tee(sys.stderr, tag)
    from . import __version__

    write(tag, f"--- {tag} started (pid {os.getpid()}, Spindle {__version__}, {sys.platform}): "
               f"{' '.join(sys.argv[1:]) or '(no arguments)'}")
    return _path


def show() -> None:
    """"Open log folder": the file manager with spindle.log selected."""
    from . import platform_utils

    path = log_path()
    if path.exists():
        platform_utils.reveal_in_file_manager(path)
    else:
        platform_utils.open_folder(log_dir())


def forward(tag: str, text: str) -> None:
    """Output of another process (the helper): to our console and the log."""
    stream = sys.stderr._stream if isinstance(sys.stderr, _Tee) else sys.stderr
    if stream is not None:
        try:
            stream.write(text if text.endswith("\n") else text + "\n")
            stream.flush()
        except (OSError, ValueError):
            pass
    write(tag, text)
