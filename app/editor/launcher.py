"""Wheel side: start the editor process for one file.

Imported by the resident wheel process, so it must stay light: no
PyMuPDF, numpy or editor QML here.

The editor is started detached: it keeps running if the wheel quits, and
it tells the wheel when its window is up (or why it couldn't open the
file) through the wheel's single-instance socket ("editor-ready",
"editor-failed <message>"), so the wheel can show "Opening…" until then.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QProcess

from .. import PROJECT_DIR, platform_utils


def editor_command(tool: str, path: Path, software: bool) -> tuple[str, list[str]]:
    args = ["--editor", tool, str(path)] + (["--software"] if software else [])
    if getattr(sys, "frozen", False):  # packaged build: the executable is the app
        return sys.executable, args
    return sys.executable, [str(PROJECT_DIR / "main.py"), *args]


def launch(tool: str, path: Path, software: bool = False) -> bool:
    program, args = editor_command(tool, path, software)
    ok, pid = QProcess.startDetached(program, args, str(PROJECT_DIR))
    if not ok:
        print(f"[editor] can't start {program}", flush=True)
        return False
    platform_utils.allow_foreground_for(pid)
    print(f"[editor] started for {path.name} ({tool}), pid {pid}", flush=True)
    return True
