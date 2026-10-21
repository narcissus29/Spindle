"""What every handler gets: the Context, and HandlerError for clean failures.

Handler signature (runs inside the helper process, never in the UI):

    def handler(path: Path, option: str, ctx: Context) -> None

- Ask `ctx.output_file(".docx")` / `ctx.output_dir("PNG")` for where to
  write; they return hidden temporaries that become the real, collision-free
  names only if the handler returns normally.
- Report progress with `ctx.progress(0.0 .. 1.0)` (throttled, cheap to call),
  optionally with a short text for the pill: `ctx.progress(0.2, "Page 12/60")`.
  `ctx.progress(None, "Analyzing…")` says it is busy but can't tell how far.
- Raise HandlerError("Password-protected PDF") for expected failures; the
  message is shown to the user as is. Any other exception is reported as
  "<Type>: <message>" and its traceback goes to stderr.
- Raise Skip("No transparency") when there is nothing to do: no output is
  kept and the reason is shown instead of "Done" (it is not a failure).
- `ctx.note("−62%", before=..., after=...)` attaches a short result to show
  in the pill (and byte sizes for the notification).
- `ctx.child(pid)` reports a process the handler started (LibreOffice,
  Word): Cancel, or the helper dying, stops it too.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from .. import outputs


class HandlerError(Exception):
    """An expected failure with a user-facing message."""


class Skip(Exception):
    """Nothing to do for this file (not a failure); the message says why.
    Extra keyword values go to the UI with it (like Context.note)."""

    def __init__(self, message: str = "", **info) -> None:
        super().__init__(message)
        self.info = info


class Context:
    def __init__(
        self,
        src: Path,
        settings: dict | None = None,
        on_progress: Callable[[float | None, str], None] | None = None,
        on_temp: Callable[[Path], None] | None = None,
        on_child: Callable[[int], None] | None = None,
    ) -> None:
        self.src = src
        self.settings = settings or {}
        self._on_progress = on_progress
        self._on_temp = on_temp
        self._on_child = on_child
        self._outputs: list[tuple[Path, Path, bool]] = []  # (temp, final, is_dir)
        self._last_report = 0.0
        self._last_fraction: float | None = -1.0
        self._last_text = ""
        self.info: dict = {}  # extra result: "note", "before", "after"

    # ---- outputs ----

    def output_file(self, suffix: str, tag: str = "") -> Path:
        """Where to write the single output file: suffix ".docx" gives
        report.docx; with tag "compressed", report (compressed).pdf."""
        name = f"{self.src.stem} ({tag}){suffix}" if tag else f"{self.src.stem}{suffix}"
        return self._reserve(self.src.with_name(name), is_dir=False)

    def output_dir(self, label: str) -> Path:
        """A folder for many output files: "report (PNG)"."""
        path = self._reserve(self.src.with_name(f"{self.src.stem} ({label})"), is_dir=True)
        path.mkdir()
        return path

    def _reserve(self, final: Path, is_dir: bool) -> Path:
        # A file is created (empty) right away, exclusively; a folder is
        # made by output_dir (mkdir fails on anything already there).
        temp = outputs.temp_path_for(final) if is_dir else outputs.create_temp_file(final)
        self._outputs.append((temp, final, is_dir))
        if self._on_temp:
            self._on_temp(temp)
        return temp

    def commit(self) -> list[Path]:
        """Move temporaries to their final, collision-free names."""
        done = []
        for temp, final, is_dir in self._outputs:
            if not temp.exists() or (not is_dir and temp.stat().st_size == 0):
                outputs.remove_temp(temp)  # reserved but never written
                continue
            done.append(outputs.move_to_free_name(temp, final, is_dir))
        self._outputs.clear()
        return done

    def discard(self) -> None:
        for temp, _final, _is_dir in self._outputs:
            outputs.remove_temp(temp)
        self._outputs.clear()

    def child(self, pid: int) -> None:
        if self._on_child:
            self._on_child(pid)

    # ---- result ----

    def note(self, text: str, **extra) -> None:
        """Short result for the pill ("−62%"); extra values (before / after
        sizes in bytes) go to the UI as well."""
        self.info = {"note": text, **extra}

    # ---- progress ----

    def progress(self, fraction: float | None, text: str = "") -> None:
        """How far this file is (0..1, or None: busy, can't tell), and
        optionally what it is doing ("Page 12/60")."""
        if not self._on_progress:
            return
        if fraction is not None:
            fraction = min(max(fraction, 0.0), 1.0)
        now = time.monotonic()
        last = self._last_fraction
        if fraction is not None and fraction >= 1.0:
            due = last != fraction
        elif fraction is None or last is None:
            due = fraction != last or text != self._last_text
        else:
            # At most ~10 messages a second, and only on visible change.
            due = now - self._last_report >= 0.1 and (fraction - last >= 0.01 or text != self._last_text)
        if due:
            self._last_report, self._last_fraction, self._last_text = now, fraction, text
            self._on_progress(fraction, text)
