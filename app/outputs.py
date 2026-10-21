"""Collision-free output paths next to the source file.

    report.pdf -> report.docx, then report (1).docx, report (2).docx, ...
    report.pdf -> report (PNG)/ for multi-page images, then report (PNG) (1)/

Handlers never write straight to the final name. They write to a hidden
temporary (".~report.docx.<token>.part") and the runner renames it when the
handler succeeds, so a crash or a cancel never leaves a half-written file
under a real name. Temporaries left behind by a killed helper are removed by
the UI process (it is told their paths as they are created).

Safe in folders other people can write to: the token is random and the
temporary is created by us exclusively (an existing file or symlink of
that name is never written through), and the final rename never replaces
a file that appeared in the meantime: it takes the next free name.
"""

from __future__ import annotations

import itertools
import os
import secrets
import shutil
import sys
from pathlib import Path

TEMP_PREFIX = ".~"
TEMP_SUFFIX = ".part"


def _candidates(desired: Path, is_dir: bool):
    yield desired
    stem, suffix = (desired.name, "") if is_dir else (desired.stem, desired.suffix)
    for i in itertools.count(1):
        yield desired.with_name(f"{stem} ({i}){suffix}")


def free_path(desired: Path, is_dir: bool = False) -> Path:
    """`desired` if nothing exists there, else "name (1).ext", "name (2).ext", ..."""
    return next(c for c in _candidates(desired, is_dir) if not os.path.lexists(c))


def move_to_free_name(temp: Path, desired: Path, is_dir: bool = False) -> Path:
    """Rename `temp` to `desired` or the next free name, never replacing
    anything that is there, also if it appeared a moment ago."""
    for candidate in _candidates(desired, is_dir):
        if os.path.lexists(candidate):
            continue
        try:
            if sys.platform == "win32" or is_dir:
                os.rename(temp, candidate)  # Windows never replaces; a folder only replaces an empty one
            else:
                try:
                    os.link(temp, candidate)  # fails if the name exists
                except FileExistsError:
                    raise
                except OSError:  # no hard links here (FAT, some network drives)
                    os.rename(temp, candidate)
                else:
                    os.unlink(temp)
            return candidate
        except FileExistsError:
            continue
    raise AssertionError("unreachable")


def temp_path_for(final: Path) -> Path:
    token = secrets.token_hex(6)
    return final.with_name(f"{TEMP_PREFIX}{final.name}.{token}{TEMP_SUFFIX}")


def create_temp_file(final: Path) -> Path:
    """A new, empty temporary for `final`, created exclusively: never an
    existing file or a symlink someone put there."""
    while True:
        temp = temp_path_for(final)
        try:
            fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0), 0o666)
        except FileExistsError:
            continue
        os.close(fd)
        return temp


def is_temp_path(path: Path) -> bool:
    return path.name.startswith(TEMP_PREFIX) and path.name.endswith(TEMP_SUFFIX)


def remove_temp(path: Path) -> None:
    """Delete a temporary file or folder; refuses anything that isn't one."""
    if not is_temp_path(path):
        return
    try:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)
    except OSError:
        pass
