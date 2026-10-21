"""QObject exposed to QML as `bridge`.

Holds the wheel's state (the dropped files, which wheel, the options on it)
and the open/close state machine. QML only does drawing, animation and the
per-mouse-move hit-testing; it calls into Python a few times per drag
(enter, leave, drop, switch), never on every move.

Open/close lifecycle:
    hidden --open()--> open --dismiss()--> closing --closeFinished()--> hidden

Files: one or many can be dragged at once. A wheel only offers the options
valid for every file; if there are none, the drop is refused ("Mixed files").

Parked files are a stack that grows: dragging more files over a parked
wheel adds them (files already on it are skipped), and the wedges show
what works for the whole stack. Dropped on the center they join the
stack; dropped on a wedge, that option runs on the whole stack. The ×
on the stack clears it; closing the wheel does too.

Running an option (handlers run in a separate helper process, see
app/jobs, so the UI never stutters):
- Drop on a wedge, or park on the center and click a wedge later.
- Unpinned: the wheel stays open showing progress, then "Done" for a
  moment, then closes. Progress: a ring around the center fills with the
  current file's progress (it spins while that can't be told: a library
  loading, a document being analysed), and the pill says "Page 12/60" or
  "42%" for one file, "File 2/3 · 20%" for several.
- Pinned: the wheel stays open; it clears for the next drop right away and
  shows progress, then "Done" (or "2 failed") for a moment.
- Esc / clicking away only hides the wheel: the job keeps going and a
  desktop notification reports the result.
- Clicking the center pill while busy cancels: the helper is killed and the
  remaining files are marked cancelled.

Editor options (Crop, Edit, Annotate, Redact; one file only) start the
editor process instead. The pill says "Opening…" until the editor reports
its window is up, then the wheel closes (pinned: clears). If the file
can't be edited, the reason ("Password-protected PDF") shows instead.

Closing: Esc, the shortcut again, the rim × button, a click outside the
wheel, or the window losing focus while no drag is over it. Dropping outside
the ring counts as a click outside. When pinned, only Esc, the shortcut and
× close it.

Two ways the shortcut opens the wheel:
- popup (a drag is under way): the behavior above.
- drop zone (no drag): only the wheel takes input, so you can go and pick
  a file while it waits. × shows; focus loss and clicks elsewhere don't
  close it; it closes after one completed action, or via ×, Esc or the
  shortcut. Pin works on top of either.
Pinned or drop zone, the window's input region is the wheel circle only
(`wheel_only`).

Sub-rings (Compress -> target sizes): clicking Compress on parked files
swaps the wedges for Auto / 20 KB ... 1 MB / Custom (same swing animation
as switching wheels). Esc, scrolling, a right-click or a click on the
center go back. Custom turns the center pill into a number field. A size
run reports "48 KB ✓" or, if the target can't be reached, "Smallest:
340 KB" in the warning color; a batch "3 of 3 under 50 KB ✓".

Moving: a pinned wheel can be dragged by its rim and snaps to the nearest
screen edge. In overlay mode QML moves the drawn wheel inside the
full-screen window and reports where it ended up (wheelMoved); otherwise
QML asks for the real window to be moved (moveWindow -> moveRequested).
The last spot is saved in the config and reused the next time it is pinned.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QObject, QPointF, QTimer, QUrl, pyqtProperty, pyqtSignal, pyqtSlot

from . import config, filetypes, handlers
from .icons import icon_path
from .config import Config
from .jobs import Job, JobItem

_RESULT_FLASH_MS = 1500
_OPENING_TIMEOUT_MS = 10000  # stop showing "Opening…" if the editor never reports
_CLOSE_AFTER_DONE_MS = 900  # unpinned: how long "Done" shows before closing


def _size_label(n: int) -> str:
    from .handlers.target import size_label  # pure: no Qt widgets, no PyMuPDF

    return size_label(n)


def _short_error(message: str) -> str:
    """"Can't open PDF (code=7: no objects found)" -> "Can't open PDF"."""
    message = message.split(" (")[0].strip() or "Failed"
    return message if len(message) <= 36 else message[:35].rstrip() + "…"


def _size(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f} MB"
    return f"{max(1, round(n / 1000))} KB"


@dataclass(frozen=True)
class _File:
    path: Path
    kind: str | None  # None = unsupported type
    label: str

    @property
    def key(self) -> str:
        """The same file, however it was named (Windows: any case)."""
        return os.path.normcase(os.path.abspath(self.path))


def _added(stack: list[_File], new: list[_File]) -> list[_File]:
    """The stack plus the new files it doesn't have yet, in order."""
    seen = {f.key for f in stack}
    out = list(stack)
    for f in new:
        if f.key not in seen:
            seen.add(f.key)
            out.append(f)
    return out


def _batch_options(files: list[_File], wheel: str) -> list[str]:
    """Option names valid for every file, in the first file's wedge order,
    plus the combining option (one PDF from all) for several files."""
    common: list[str] | None = None
    for f in files:
        names = handlers.options_for(f.kind, wheel, f.label, len(files)) if f.kind else []
        common = names if common is None else [n for n in common if n in names]
        if not common:
            break
    common = common or []
    if all(f.kind for f in files):
        kinds = {f.kind for f in files}
        common += [n for n in handlers.combined_options(kinds, wheel, len(files)) if n not in common]
    return common


class Bridge(QObject):
    # to QML
    openRequested = pyqtSignal()
    closeRequested = pyqtSignal()
    stateChanged = pyqtSignal()
    optionsChanged = pyqtSignal()
    # to Python
    hidden = pyqtSignal()
    parkedChanged = pyqtSignal(bool)
    pinnedChanged = pyqtSignal(bool)
    jobRequested = pyqtSignal(object)
    editorRequested = pyqtSignal(str, str)     # tool, file path
    cancelRequested = pyqtSignal()
    thumbnailRequested = pyqtSignal(str)       # PDF path: render its first page
    notify = pyqtSignal(str, str)              # title, body (desktop notification)
    wheelCenterChanged = pyqtSignal()          # overlay: wheel moved inside the window
    moveRequested = pyqtSignal(str, float, float)  # small window: "start" / "move" / "end", dx, dy

    def __init__(self, cfg: Config, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._shown = "hidden"  # hidden | open | closing
        self._files: list[_File] = []
        self._status = ""  # "" (no file) | "ok" | "unsupported" | "mixed"
        self._wheels: list[str] = []
        self._kinds: set[str | None] = set()
        self._wheel = handlers.ACTIONS
        self._options: list[dict] = []
        self._drag_inside = False
        self._active_since_open = False
        self._parked = False
        self._stack: list[_File] = []  # the parked files (while parked)
        self._pinned = False
        self._drop_zone = False
        self._drag_seen = False  # a drag reached the wheel since it opened
        self._overlay = False
        self._wheel_center: tuple[float, float] | None = None  # overlay, window coords
        self._pdf_thumb = ""  # file:// URL of the rendered first page, when ready
        self._sub = ""           # parent option of the sub-ring shown ("Compress"), or ""
        self._custom_entry = False

        # Progress across every job queued on the helper (a "run").
        self._run_total = 0
        self._run_done = 0
        self._run_failed = 0
        self._run_errors: set[str] = set()  # why files failed
        self._run_cancelled = 0
        self._run_options: set[tuple[str, str]] = set()
        self._run_skipped = 0
        self._run_notes: set[str] = set()  # reasons files were skipped
        self._run_bytes = [0, 0]  # total size before / after, where reported
        self._run_first: tuple[str, str, str, dict] = ("", "", "", {})  # source, first output, error, info
        self._run_target = 0     # a size run: the target in bytes
        self._run_fit = 0        # ... files that ended up under it
        self._run_misses: list[str] = []  # "report.pdf: smallest 340 KB"
        self._file_fraction = -1.0  # the current file: 0..1, -1 = can't tell (yet)
        self._file_text = ""        # ... and what it is doing ("Page 12/60")
        self._close_when_done = False
        self._result_text = ""
        self._opening = ""  # file name while the editor starts for it
        self._opening_timer = QTimer(self)  # one-shot, only while opening
        self._opening_timer.setSingleShot(True)
        self._opening_timer.setInterval(_OPENING_TIMEOUT_MS)
        self._opening_timer.timeout.connect(self.editor_ready)
        # One-shot, only started while the wheel is visible.
        self._result_timer = QTimer(self)
        self._result_timer.setSingleShot(True)
        self._result_timer.setInterval(_RESULT_FLASH_MS)
        self._result_timer.timeout.connect(self._clear_result)
        # A refused drag gets no leave event from Qt, so "Mixed files" /
        # "Not supported" clears itself after a moment.
        self._refused_timer = QTimer(self)
        self._refused_timer.setSingleShot(True)
        self._refused_timer.setInterval(_RESULT_FLASH_MS)
        self._refused_timer.timeout.connect(lambda: self._restore_stack() if self.refused else None)

        self._rebuild_options()

    # ----------------------------------------------------------- properties

    @pyqtProperty(str, notify=stateChanged)
    def themeName(self) -> str:
        return self._cfg.theme

    @pyqtProperty(bool, notify=stateChanged)
    def reduceAnimations(self) -> bool:
        return self._cfg.reduce_animations

    @pyqtProperty(int, constant=True)
    def wheelSize(self) -> int:
        return self._cfg.wheel_size

    @pyqtProperty(bool, constant=True)
    def overlay(self) -> bool:
        """True when the wheel is drawn inside a full-screen window (Wayland)."""
        return self._overlay

    @pyqtProperty(QPointF, notify=stateChanged)
    def pinnedSpot(self) -> QPointF:
        """Saved pinned position as fractions of the screen, or (-1, -1)."""
        return QPointF(self._cfg.pinned_x, self._cfg.pinned_y)

    @pyqtProperty(bool, notify=stateChanged)
    def idle(self) -> bool:
        return self._status == ""

    @pyqtProperty(bool, notify=stateChanged)
    def refused(self) -> bool:
        return self._status in ("unsupported", "mixed")

    @pyqtProperty(str, notify=stateChanged)
    def refusedText(self) -> str:
        return {"unsupported": "Not supported", "mixed": "Mixed files"}.get(self._status, "")

    @pyqtProperty(int, notify=stateChanged)
    def fileCount(self) -> int:
        return len(self._files)

    @pyqtProperty(str, notify=stateChanged)
    def formatLabel(self) -> str:
        """"PDF" for one file, "10 PDFs" for a batch of one type, "3 files"
        for a mix."""
        if not self._files:
            return ""
        if len(self._files) == 1:
            return self._files[0].label
        labels = {f.label for f in self._files}
        if len(labels) == 1:
            return f"{len(self._files)} {self._files[0].label}s"
        return f"{len(self._files)} files"

    @pyqtProperty(str, notify=stateChanged)
    def firstLabel(self) -> str:
        return self._files[0].label if self._files else ""

    @pyqtProperty(str, notify=stateChanged)
    def wheelName(self) -> str:
        return self._wheel

    @pyqtProperty(str, notify=stateChanged)
    def wheelLabel(self) -> str:
        return handlers.WHEEL_LABELS.get(self._wheel, "")

    @pyqtProperty(bool, notify=stateChanged)
    def canSwitch(self) -> bool:
        return len(self._wheels) > 1

    @pyqtProperty(bool, notify=stateChanged)
    def parked(self) -> bool:
        return self._parked

    @pyqtProperty(bool, notify=stateChanged)
    def pinned(self) -> bool:
        return self._pinned

    @pyqtProperty(bool, notify=stateChanged)
    def dropZone(self) -> bool:
        return self._drop_zone

    @pyqtProperty(bool, notify=stateChanged)
    def busy(self) -> bool:
        return self._run_done < self._run_total

    @pyqtProperty(str, notify=stateChanged)
    def statusText(self) -> str:
        """Progress or a short result ("Done", "Cancelled"). One file: what
        the helper says it is doing ("Page 12/60"), else "42%", else
        "Working…". Several: "File 2/3 · 42%"."""
        if self._opening:
            return "Opening…"
        if self._run_done < self._run_total:
            pct = int(self._file_fraction * 100) if self._file_fraction >= 0 else -1
            if self._run_total == 1:
                return self._file_text or (f"{pct}%" if pct > 0 else "Working…")
            where = f"File {self._run_done + 1}/{self._run_total}"
            return f"{where} · {pct}%" if pct >= 0 else where
        return self._result_text

    @pyqtProperty(float, notify=stateChanged)
    def progress(self) -> float:
        """The current file's progress for the ring: 0..1, or -1 while
        that can't be told (the ring spins)."""
        return self._file_fraction

    @pyqtProperty(str, notify=stateChanged)
    def parkedThumb(self) -> str:
        """file:// URL for the hub thumbnail of the first parked file: the
        image itself, or for a PDF its first page once the helper has
        rendered it ("" until then: the hub shows a document icon)."""
        if not (self._parked and self._files):
            return ""
        if self._files[0].kind == filetypes.IMAGE and self._files[0].label != "HEIC":
            return QUrl.fromLocalFile(str(self._files[0].path)).toString()
        return self._pdf_thumb  # PDFs and HEIC: rendered by the helper

    @pyqtProperty("QVariantList", notify=optionsChanged)
    def options(self) -> list:
        return self._options

    @pyqtProperty(str, notify=stateChanged)
    def subRing(self) -> str:
        """The option whose choices are on the wheel ("Compress"), or ""."""
        return self._sub

    @pyqtProperty(str, notify=stateChanged)
    def subRingTitle(self) -> str:
        return "Compress to\u2026" if self._sub == "Compress" else self._sub

    @pyqtProperty(bool, notify=stateChanged)
    def customEntry(self) -> bool:
        """The center pill is asking for a custom size."""
        return self._custom_entry

    @pyqtProperty(str, constant=True)
    def lastCustom(self) -> str:
        return self._cfg.compress_custom

    @pyqtProperty(bool, notify=stateChanged)
    def statusWarn(self) -> bool:
        """The result shown is a failure or a miss ("Smallest: 340 KB")."""
        if not self._result_text or self._opening:
            return False
        if self._run_failed and not self._run_cancelled and self._run_done >= self._run_total:
            return True
        return (self._run_target > 0
                and self._run_fit < self._run_total - self._run_failed - self._run_cancelled)

    # ------------------------------------------------------- Python side API

    @property
    def is_shown(self) -> bool:
        return self._shown == "open"

    @property
    def is_hidden(self) -> bool:
        return self._shown == "hidden"

    @property
    def is_parked(self) -> bool:
        return self._parked

    @property
    def is_pinned(self) -> bool:
        return self._pinned

    @property
    def wheel_only(self) -> bool:
        """Only the wheel takes input (pinned or drop zone)."""
        return self._pinned or self._drop_zone

    @property
    def drag_seen(self) -> bool:
        return self._drag_seen

    @property
    def wheel_center(self) -> tuple[float, float] | None:
        """Overlay mode: where QML last put the wheel (None = centered)."""
        return self._wheel_center

    def set_overlay(self, overlay: bool) -> None:
        """Called once by the window before QML loads."""
        self._overlay = overlay

    def remember_pinned_spot(self, nx: float, ny: float) -> None:
        nx, ny = min(max(nx, 0.0), 1.0), min(max(ny, 0.0), 1.0)
        if (nx, ny) != (self._cfg.pinned_x, self._cfg.pinned_y):
            self._cfg.pinned_x, self._cfg.pinned_y = nx, ny
            config.save(self._cfg)
            self.stateChanged.emit()

    def open(self, drop_zone: bool = False) -> None:
        if self._shown == "hidden":
            self._drag_inside = False
            self._active_since_open = False
            self._drag_seen = False
            self._drop_zone = drop_zone
        self._shown = "open"
        self.stateChanged.emit()
        self.openRequested.emit()

    def set_drop_zone(self, on: bool) -> None:
        """The window decided (after open) which mode this is."""
        if on != self._drop_zone and self._shown == "open":
            self._drop_zone = on
            self.stateChanged.emit()

    def window_active_changed(self, active: bool) -> None:
        # Focus loss closes the wheel unless it is pinned or a drag is over
        # it (drag-first flow: the file manager may still hold focus
        # mid-drag). On Windows / X11 this is how a click outside the small
        # window is noticed.
        if active:
            self._active_since_open = True
            return
        # Only a focus loss after we had focus counts: when the wheel is
        # reopened right after closing, the compositor's late "deactivated"
        # for the old one can arrive after the reopen.
        if self._shown == "open" and self._active_since_open and not self._drag_inside and not self.wheel_only:
            self.dismiss()

    def file_progress(self, job: Job, index: int, fraction: float, text: str = "") -> None:
        self._file_fraction = fraction
        self._file_text = text
        self.stateChanged.emit()

    def file_done(self, job: Job, index: int, error: str, outputs: list, info: dict | None = None) -> None:
        """The helper finished (or failed / was cancelled / skipped) one file."""
        from .jobs.process import CANCELLED

        info = info or {}
        self._run_done += 1
        self._file_fraction, self._file_text = -1.0, ""
        if error == CANCELLED:
            self._run_cancelled += 1
        elif error:
            self._run_failed += 1
            self._run_errors.add(error)
        elif info.get("skipped"):
            self._run_skipped += 1
            self._run_notes.add(info.get("note", ""))
        elif "before" in info and "after" in info:
            self._run_bytes[0] += int(info["before"])
            self._run_bytes[1] += int(info["after"])
        if "target" in info and not error:
            self._run_target = int(info["target"])
            if info.get("fits"):
                self._run_fit += 1
            else:
                self._run_misses.append(f"{job.items[index].path.name}: {info.get('note', '').lower()}")
        if not self._run_first[0]:
            self._run_first = (job.items[index].path.name, Path(outputs[0]).name if outputs else "", error, info)
        self.stateChanged.emit()
        if self._run_done >= self._run_total:
            self._run_finished()

    def editor_ready(self) -> None:
        """The editor's window is up (or it took too long to say so)."""
        if not self._opening:
            return
        self._opening = ""
        self._opening_timer.stop()
        if self._close_when_done:
            self._close_when_done = False
            self.dismiss()  # the editor window appearing is the feedback
        self.stateChanged.emit()

    def editor_failed(self, message: str) -> None:
        name = self._opening
        if not name:
            return
        self._opening = ""
        self._opening_timer.stop()
        if self._shown == "open":
            self._result_text = message
            self._result_timer.start(_CLOSE_AFTER_DONE_MS + 900 if self._close_when_done else _RESULT_FLASH_MS)
        else:
            self._close_when_done = False
            self.notify.emit("Can't open the editor", f"{name}: {message}")
        self.stateChanged.emit()

    def thumbnail_ready(self, source: str, thumb: str) -> None:
        if thumb and self._parked and self._files and str(self._files[0].path) == source:
            self._pdf_thumb = QUrl.fromLocalFile(thumb).toString()
            self.stateChanged.emit()

    # -------------------------------------------------------- slots for QML

    @pyqtSlot(list, result=bool)
    def dragEnter(self, urls: list) -> bool:
        """A drag came over the wheel. Over parked files it would add to
        them: the wedges show what works for all of them together."""
        if self._close_when_done:
            return False  # this wheel closes once its run is done
        self._drag_inside = True
        self._drag_seen = True
        self._refused_timer.stop()

        files = []
        for u in urls:
            url = u if isinstance(u, QUrl) else QUrl(str(u))
            if url.isLocalFile():
                path = Path(url.toLocalFile())
                files.append(_File(path, filetypes.kind_from_path(path), filetypes.format_label(path) or "?"))
        if self._parked:
            files = _added(self._stack, files)
        else:
            files = _added([], files)
        self._set_files(files)
        if self._status != "ok":
            # Refused: Qt sends no move / drop / leave for it, so it is not
            # a drag "over the wheel" and focus loss may close us.
            self._drag_inside = False
            if self._shown == "open":
                self._refused_timer.start()
            return False
        return True

    @pyqtSlot()
    def dragLeave(self) -> None:
        self._drag_inside = False
        if self.refused or self._parked:
            self._restore_stack()  # the drag went away: just the parked files again

    @pyqtSlot(int, result=bool)
    def drop(self, index: int) -> bool:
        """Files dropped straight on wedge `index`. A drop that misses the
        ring (index -1) cancels like a click outside, unless only the wheel
        takes input (pinned / drop zone): then it just clears."""
        self._drag_inside = False
        if self._status != "ok" or not 0 <= index < len(self._options):
            if self.wheel_only:
                self._restore_stack()
            else:
                self.dismiss()
            return False
        return self._run(index)  # parked: on the whole stack, the new files included

    @pyqtSlot(result=bool)
    def park(self) -> bool:
        """Files dropped on the center: keep the wheel open with them parked
        (added to the files parked already)."""
        self._drag_inside = False
        if self._status != "ok":
            return False
        first = self._stack[0].key if self._stack else ""
        self._stack = list(self._files)
        self._set_parked(True)
        if self._files[0].key != first and (self._files[0].kind == filetypes.PDF or self._files[0].label == "HEIC"):
            self.thumbnailRequested.emit(str(self._files[0].path))
        self.stateChanged.emit()
        return True

    @pyqtSlot()
    def clearStack(self) -> None:
        """The × on the parked stack: put the files away, keep the wheel."""
        if self._parked:
            self._set_parked(False)
            self._set_files([])

    @pyqtSlot(int)
    def activate(self, index: int) -> None:
        """Wedge clicked while files are parked. An option with a sub-ring
        opens it; "Custom" in it asks for a size."""
        if not (self._parked and 0 <= index < len(self._options)):
            return
        name = self._options[index]["name"]
        if not self._sub and name in handlers.SUBRINGS:
            self._set_sub(name)
        elif self._sub and name == handlers.CUSTOM:
            self._custom_entry = True
            self.stateChanged.emit()
        else:
            self._run(index)

    @pyqtSlot()
    def leaveSubRing(self) -> None:
        """Back from a sub-ring (or from typing a custom size to it)."""
        if self._custom_entry:
            self._custom_entry = False
            self.stateChanged.emit()
        elif self._sub:
            self._set_sub("")

    @pyqtSlot(str, result=str)
    def runCustom(self, text: str) -> str:
        """Run the sub-ring's action with a typed size ("75", "75 KB",
        "1.5 MB"). Returns an error to show, or "" when it started."""
        from .handlers.target import parse_target, size_label

        size = parse_target(text)
        if size is None:
            return "1 KB to 100 MB"
        label = size_label(size)
        if self._cfg.compress_custom != label:
            self._cfg.compress_custom = label
            config.save(self._cfg)
        self._custom_entry = False
        self._start_sub(label)
        return ""

    @pyqtSlot()
    def switchWheel(self) -> None:
        # Only parked files can be switched; during a drag the file manager
        # keeps the keyboard and scroll wheel anyway. In a sub-ring it goes
        # back to the wheel instead.
        if self._sub:
            self.leaveSubRing()
            return
        if not self._parked or len(self._wheels) < 2:
            return
        self._wheel = self._wheels[(self._wheels.index(self._wheel) + 1) % len(self._wheels)]
        self.stateChanged.emit()
        self._rebuild_options()

    @pyqtSlot()
    def cancel(self) -> None:
        """Center pill clicked while busy: stop everything that is queued."""
        if self.busy:
            self.cancelRequested.emit()

    @pyqtSlot()
    def togglePin(self) -> None:
        self._pinned = not self._pinned
        self.stateChanged.emit()
        self.pinnedChanged.emit(self._pinned)

    @pyqtSlot(float, float, float, float, bool)
    def wheelMoved(self, cx: float, cy: float, nx: float, ny: float, remember: bool) -> None:
        """Overlay mode: the wheel now sits at (cx, cy) in window coordinates
        ((nx, ny) as fractions). The window moves its input region there."""
        self._wheel_center = (cx, cy)
        self.wheelCenterChanged.emit()
        if remember:
            self.remember_pinned_spot(nx, ny)

    @pyqtSlot(str, float, float)
    def moveWindow(self, phase: str, dx: float, dy: float) -> None:
        """Small-window mode: drag the real window by (dx, dy) global pixels
        since the press; "end" snaps it to the nearest screen edge."""
        self.moveRequested.emit(phase, dx, dy)

    @pyqtSlot()
    def dismiss(self) -> None:
        if self._shown != "open":
            return
        self._shown = "closing"
        self.closeRequested.emit()

    @pyqtSlot()
    def closeFinished(self) -> None:
        if self._shown != "closing":
            return  # reopened while the close animation was running
        self._shown = "hidden"
        self._close_when_done = False
        self._result_timer.stop()
        self._refused_timer.stop()
        self._result_text = ""
        self._set_parked(False)
        self._wheel_center = None  # every open starts centered
        self._drop_zone = False
        if self._pinned:
            self._pinned = False  # ... and unpinned
            self.pinnedChanged.emit(False)
        self.hidden.emit()
        self._set_files([])

    # -------------------------------------------------------------- helpers

    def _run(self, index: int) -> bool:
        option = self._options[index]["name"]
        if self._sub:
            return self._start_sub(option)
        if len(self._files) == 1:
            spec = handlers.get_handler(self._files[0].kind, self._wheel, option)
            if handlers.is_editor(spec):
                return self._open_editor(spec[len(handlers.EDITOR_PREFIX):], self._files[0].path)
        kinds = {f.kind for f in self._files}
        if len(self._files) > 1:
            spec = handlers.combined_handler(kinds, self._wheel, option, len(self._files))
            if spec:  # one output from every file, in drop order
                items = tuple(JobItem(f.path, f.kind, spec) for f in self._files)
                return self._start(Job(self._wheel, option, items, combine=True))
        items = []
        for f in self._files:
            handler = handlers.get_handler(f.kind, self._wheel, option, len(self._files))
            if handler is None or handlers.is_editor(handler):
                print(f"[bridge] no handler for {f.kind}/{self._wheel}/{option}")
                continue
            items.append(JobItem(f.path, f.kind, handler))
        if not items:
            return False
        return self._start(Job(self._wheel, option, tuple(items)))

    def _start_sub(self, choice: str) -> bool:
        """Run a sub-ring choice (or a custom size) on every parked file."""
        spec, option = handlers.subring_spec(self._sub, choice)
        items = tuple(JobItem(f.path, f.kind, spec) for f in self._files)
        self._set_sub("")
        return self._start(Job(self._wheel, option, items))

    def _set_sub(self, parent: str) -> None:
        if parent == self._sub and not self._custom_entry:
            return
        self._sub = parent
        self._custom_entry = False
        self.stateChanged.emit()
        self._rebuild_options()

    def _start(self, job: Job) -> bool:
        self._set_parked(False)
        if self._pinned:
            self._set_files([])  # ready for the next drop right away
        else:
            self._close_when_done = True
        self._submit(job)
        return True

    def _open_editor(self, tool: str, path: Path) -> bool:
        self._set_parked(False)
        self._result_timer.stop()
        self._result_text = ""
        self._opening = path.name
        self._opening_timer.start()
        if self._pinned:
            self._set_files([])
        else:
            self._close_when_done = True
        self.stateChanged.emit()
        self.editorRequested.emit(tool, str(path))
        return True

    def _submit(self, job: Job) -> None:
        if self._run_done >= self._run_total:  # nothing running: start fresh
            self._run_total = self._run_done = self._run_failed = self._run_cancelled = 0
            self._run_errors = set()
            self._run_options = set()
            self._run_skipped = 0
            self._run_notes = set()
            self._run_bytes = [0, 0]
            self._run_first = ("", "", "", {})
            self._run_target, self._run_fit, self._run_misses = 0, 0, []
        self._result_timer.stop()
        self._result_text = ""
        if self._run_done >= self._run_total:
            self._file_fraction, self._file_text = -1.0, ""
        self._run_total += 1 if job.combine else len(job.items)  # a combined job makes one file
        self._run_options.add((job.wheel, job.option))
        self.stateChanged.emit()
        self.jobRequested.emit(job)

    def _run_finished(self) -> None:
        total, failed, cancelled = self._run_total, self._run_failed, self._run_cancelled
        if self._shown == "open":
            self._result_text = self._result_label()
            # Unpinned: show the result briefly, then close.
            self._result_timer.start(_CLOSE_AFTER_DONE_MS if self._close_when_done else _RESULT_FLASH_MS)
        elif not cancelled:
            self.notify.emit(*self._summary())
        self.stateChanged.emit()

    def _saving(self) -> str:
        """"−62%" when the run reported sizes and saved at least 1%."""
        before, after = self._run_bytes
        if before > 0 and after < before:
            pct = round(100 * (before - after) / before)
            if pct >= 1:
                return f"\u2212{pct}%"
        return ""

    def _result_label(self) -> str:
        """Short text for the pill when a run ends."""
        total, failed, cancelled, skipped = self._run_total, self._run_failed, self._run_cancelled, self._run_skipped
        if cancelled:
            return "Cancelled"
        if failed:
            # Say why when there is one reason ("Password-protected PDF",
            # "The helper didn't start"), shortened to fit the pill.
            if len(self._run_errors) == 1 and (total == 1 or failed == total):
                return _short_error(next(iter(self._run_errors)))
            return f"{failed} failed"
        if self._run_target:
            if total == 1:
                return self._run_first[3].get("note", "Done")
            ok = "\u2713" if self._run_fit == total else ""
            return f"{self._run_fit} of {total} under {_size_label(self._run_target)} {ok}".strip()
        if skipped == total:  # nothing to do for any file: say why
            return next(iter(self._run_notes)) if len(self._run_notes) == 1 else "Nothing to do"
        if saving := self._saving():
            return saving
        if total == 1 and self._run_first[3].get("note"):
            return self._run_first[3]["note"]
        return "Done" if not skipped else f"Done, {skipped} skipped"

    def _summary(self) -> tuple[str, str]:
        """Notification for a run that finished after the wheel was closed."""
        total, failed, skipped = self._run_total, self._run_failed, self._run_skipped
        if len(self._run_options) == 1:
            wheel, option = next(iter(self._run_options))
            what = (f"Convert to {option}" if wheel == handlers.CONVERT
                    else f"Compress to {option}" if option[:1].isdigit() else option)
        else:
            what = "Spindle"
        if self._run_target:
            return self._target_summary(what)
        sizes = ""
        if saving := self._saving():
            sizes = f"{_size(self._run_bytes[0])} → {_size(self._run_bytes[1])} ({saving})"
        if total == 1:
            name, output, error, info = self._run_first
            if error:
                return f"{what} failed", f"{name}: {error}"
            if info.get("skipped"):
                return what, f"{name}: {info.get('note', 'nothing to do')}"
            if sizes:
                return f"{what}: done", f"{name}: {sizes}"
            if info.get("detail"):
                return f"{what}: done", f"{name}: {info['detail']}"
            return f"{what}: done", f"{name} → {output}" if output else name
        title = f"{what}: done" if not failed else f"{what}: {failed} failed"
        body = f"{total - failed - skipped} of {total} files done"
        if skipped:
            body += f", {skipped} skipped"
        if sizes:
            body += f" · {sizes}"
        return title, body

    def _target_summary(self, what: str) -> tuple[str, str]:
        total, failed = self._run_total, self._run_failed
        label = _size_label(self._run_target)
        if total == 1 and not failed:
            name, _output, _error, info = self._run_first
            body = f"{name}: {info.get('note', '')}"
            if info.get("detail"):
                body += f" ({info['detail']})"
            return (f"{what}: done" if info.get("fits") else f"{what}: not reachable"), body
        title = f"{what}: {self._run_fit} of {total} under {label}"
        body = "; ".join(self._run_misses[:3]) + (" …" if len(self._run_misses) > 3 else "")
        if failed:
            body = (body + "; " if body else "") + f"{failed} failed"
        return title, body or "All files fit"

    def _clear_result(self) -> None:
        self._result_text = ""
        if self._close_when_done:
            self._close_when_done = False
            self.dismiss()
        self.stateChanged.emit()

    def _restore_stack(self) -> None:
        """Back to just the parked files (none if nothing is parked)."""
        self._set_files(list(self._stack) if self._parked else [])

    def _set_parked(self, parked: bool) -> None:
        if parked == self._parked:
            return
        self._parked = parked
        if not parked:
            self._stack = []
            self._sub, self._custom_entry = "", False
        self.stateChanged.emit()
        self.parkedChanged.emit(parked)

    def _set_files(self, files: list[_File]) -> None:
        same_first = bool(files and self._files and files[0].key == self._files[0].key)
        self._files = files
        self._sub, self._custom_entry = "", False
        if not same_first:
            self._pdf_thumb = ""  # (more files on a stack: its top stays)
        if not files:
            status, wheels = "", []
        elif all(f.kind is None for f in files):
            status, wheels = "unsupported", []
        else:
            wheels = [w for w in handlers.WHEELS if _batch_options(files, w)]
            status = "ok" if wheels else "mixed"
        kinds = {f.kind for f in files}

        changed = status != self._status or wheels != self._wheels or kinds != self._kinds
        self._status, self._wheels, self._kinds = status, wheels, kinds
        if changed or self._wheel not in wheels:
            if len(kinds) == 1 and handlers.DEFAULT_WHEEL.get(next(iter(kinds))) in wheels:
                self._wheel = handlers.DEFAULT_WHEEL[next(iter(kinds))]
            elif handlers.ACTIONS in wheels or not wheels:
                self._wheel = handlers.ACTIONS
            else:
                self._wheel = wheels[0]
        self.stateChanged.emit()
        self._rebuild_options()

    def _rebuild_options(self) -> None:
        if self._sub:
            names = list(handlers.SUBRINGS[self._sub])
        elif self._status == "ok":
            names = _batch_options(self._files, self._wheel)
        else:
            # No file yet / refused: show the image Actions wheel, dimmed.
            names = handlers.options_for(filetypes.IMAGE, handlers.ACTIONS)
        options = [{"name": n, "icon": icon_path(handlers.ICONS.get(n, ""))} for n in names]
        if options != self._options:
            self._options = options
            self.optionsChanged.emit()
