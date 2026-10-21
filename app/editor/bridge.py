"""QObject exposed to the editor's QML as `editor`.

QML draws and animates; this object owns the edit state and the undo
history (state.py). Drags and slider moves are kept in QML while they
happen and arrive here once, on release, as one undo step.

`turned(op)` tells QML which way the picture just turned ("cw", "ccw",
"h", "v"), also for undo / redo, so it can animate the turn instead of
jumping.

Annotate / Redact: marks and redaction boxes of the page on screen are
`marks` / `redactions` (content units, see state.py and marks.py). QML
draws a stroke or box while the pointer moves and hands it over once
(addMark / addRedaction), as one undo step. Search-and-redact runs on a
worker thread; its matches arrive in `searchResults`, each with a tick
box, and redactChecked() turns the ticked ones into redaction boxes.

Info (metadata): the file's metadata is read on a worker thread the first
time the tool is shown (loadMeta). `metaSections` is what the panel
lists, with the user's changes applied (each row says whether it is
removed or edited); changes are part of the edit state, one undo step
each, and are written when the copy is saved.
"""

from __future__ import annotations

import threading
from pathlib import Path

from PyQt6.QtCore import QObject, QRectF, pyqtProperty, pyqtSignal, pyqtSlot

from .. import filetypes, outputs, platform_utils
from ..config import Config
from . import marks as mk, state as st
from .document import LOCK, OpenError

TOOLS = ("crop", "edit", "annotate", "redact", "metadata")
ANNOTATE_TOOLS = ("select", "pen", "highlight", "text", "arrow", "rect")
SWATCHES = ("#e5322d", "#ff8a00", "#ffd60a", "#2fa84f", "#1e5bd8", "#8e44ef", "#111111", "#ffffff")
# Stroke widths and text sizes in *screen* pixels; QML divides by the zoom
# when it creates a mark, so a stroke looks as thick as chosen.
WIDTHS = {"pen": (2, 4, 7, 12), "highlight": (12, 20, 30, 44), "arrow": (2, 4, 7, 12),
          "rect": (2, 4, 7, 12), "text": (14, 20, 28, 40)}
_LABELS = {"pen": "Pen", "highlight": "Highlight", "text": "Text", "arrow": "Arrow", "rect": "Rectangle"}


class EditorBridge(QObject):
    changed = pyqtSignal()
    pagesChanged = pyqtSignal()
    turned = pyqtSignal(str)
    saved = pyqtSignal(str)          # file name of the new file
    saveFailed = pyqtSignal(str)     # message
    marksChanged = pyqtSignal()      # marks / redactions of the page on screen
    selectionChanged = pyqtSignal()
    optionsChanged = pyqtSignal()    # annotate tool, color, width
    searchChanged = pyqtSignal()
    metaChanged = pyqtSignal()       # Info: loaded, or the sections changed
    _saveDone = pyqtSignal(str, str)  # (path, error) from the save thread
    _searchDone = pyqtSignal(int, list)  # (search number, results) from the search thread
    _metaDone = pyqtSignal(object, str)  # (metadata, error) from the reading thread

    def __init__(self, doc, tool: str, cfg: Config, software: bool, icon_paths, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._doc = doc
        self._cfg = cfg
        self._software = software
        self._icon = icon_paths
        self._tool = tool if tool in TOOLS else "crop"
        self._page = 0
        self._history = st.History(doc.initial_state())
        self._crop_all = True     # PDFs: a crop applies to every page
        self._rotate_all = False  # PDFs: rotate only the page on screen
        self._saving = False
        self._save_limit = 0  # bytes; 0 = no "Limit file size"
        self._last_note = ""
        self._save_snapshot: dict | None = None
        self._last_saved: Path | None = None
        self._saveDone.connect(self._on_save_done)
        # Annotate / Redact
        self._next_id = 1
        self._selected = -1
        self._annotate_tool = "pen"
        self._color = SWATCHES[0]
        self._width_index = 1
        self._redact_preview = False
        self._search_no = 0
        self._searching = False
        self._results: list[dict] = []
        self._search_term = ""
        self._searchDone.connect(self._on_search_done)
        # Info
        self._meta = None
        self._meta_state = "idle"  # idle | loading | ready | failed
        self._meta_error = ""
        self._metaDone.connect(self._on_meta_done)
        self.changed.connect(self._meta_follow_state)
        self._meta_seen = None
        self._sections, self._sections_for = [], None
        if self._tool == "metadata":
            self.loadMeta()

    # ----------------------------------------------------------- constants

    @pyqtProperty(str, constant=True)
    def themeName(self) -> str:
        return self._cfg.theme

    @pyqtProperty(bool, constant=True)
    def reduceAnimations(self) -> bool:
        return self._cfg.reduce_animations

    @pyqtProperty(bool, constant=True)
    def software(self) -> bool:
        """No shaders: color adjustments are previewed from Python."""
        return self._software

    @pyqtProperty(bool, constant=True)
    def isPdf(self) -> bool:
        return self._doc.kind == filetypes.PDF

    @pyqtProperty(str, constant=True)
    def fileName(self) -> str:
        return self._doc.path.name

    @pyqtProperty(str, constant=True)
    def folder(self) -> str:
        return str(self._doc.path.parent)

    @pyqtProperty(str, constant=True)
    def formatLabel(self) -> str:
        return filetypes.format_label(self._doc.path)

    @pyqtProperty(int, constant=True)
    def pageCount(self) -> int:
        return self._doc.page_count

    @pyqtProperty(int, constant=True)
    def previewWidth(self) -> int:
        """Images: width of the on-screen copy, in px."""
        return 0 if self.isPdf else self._doc.preview.width()

    @pyqtProperty(bool, constant=True)
    def hasAlpha(self) -> bool:
        return (not self.isPdf) and self._doc.has_alpha

    # --------------------------------------------------------------- state

    @property
    def _state(self) -> dict:
        return self._history.state

    def _current(self) -> dict:
        """The image state, or the state of the page on screen."""
        return self._state["pages"][self._page] if self.isPdf else self._state

    @pyqtProperty(str, notify=changed)
    def tool(self) -> str:
        return self._tool

    @pyqtProperty(int, notify=changed)
    def page(self) -> int:
        return self._page

    @pyqtProperty(float, notify=changed)
    def pageWidth(self) -> float:
        """Current page / image as displayed before the user's rotation
        (PDF points, or image pixels)."""
        return self._doc.page_size(self._page)[0]

    @pyqtProperty(float, notify=changed)
    def pageHeight(self) -> float:
        return self._doc.page_size(self._page)[1]

    @pyqtProperty(int, notify=changed)
    def rot(self) -> int:
        return self._current()["rot"]

    @pyqtProperty(bool, notify=changed)
    def mirror(self) -> bool:
        return (not self.isPdf) and self._state["mirror"]

    @pyqtProperty(bool, notify=changed)
    def hasCrop(self) -> bool:
        return self._current()["crop"] is not None

    @pyqtProperty(QRectF, notify=changed)
    def crop(self) -> QRectF:
        """Normalized in the displayed (rotated) page; the whole page when
        there is no crop."""
        c = self._current()["crop"]
        return QRectF(*c) if c else QRectF(0, 0, 1, 1)

    @pyqtProperty(float, notify=changed)
    def brightness(self) -> float:
        return 0.0 if self.isPdf else self._state["adjust"]["brightness"]

    @pyqtProperty(float, notify=changed)
    def contrast(self) -> float:
        return 0.0 if self.isPdf else self._state["adjust"]["contrast"]

    @pyqtProperty(float, notify=changed)
    def saturation(self) -> float:
        return 0.0 if self.isPdf else self._state["adjust"]["saturation"]

    @pyqtProperty(bool, notify=changed)
    def pageDeleted(self) -> bool:
        return self.isPdf and self._current()["deleted"]

    @pyqtProperty(int, notify=changed)
    def keptPages(self) -> int:
        if not self.isPdf:
            return 1
        return sum(1 for p in self._state["pages"] if not p["deleted"])

    @pyqtProperty("QVariantList", notify=pagesChanged)
    def pages(self) -> list:
        """For the page strip: [{rot, deleted, cropped}] per page."""
        if not self.isPdf:
            return []
        sizes = [self._doc.page_size(i) for i in range(self._doc.page_count)]
        return [{"rot": p["rot"], "deleted": p["deleted"], "cropped": p["crop"] is not None,
                 "w": sizes[i][0], "h": sizes[i][1]}
                for i, p in enumerate(self._state["pages"])]

    @pyqtProperty(bool, notify=changed)
    def cropAllPages(self) -> bool:
        return self._crop_all

    @pyqtProperty(bool, notify=changed)
    def rotateAllPages(self) -> bool:
        return self._rotate_all

    @pyqtProperty(bool, notify=changed)
    def canUndo(self) -> bool:
        return self._history.can_undo

    @pyqtProperty(bool, notify=changed)
    def canRedo(self) -> bool:
        return self._history.can_redo

    @pyqtProperty(str, notify=changed)
    def undoText(self) -> str:
        return self._history.undo_label

    @pyqtProperty(str, notify=changed)
    def redoText(self) -> str:
        return self._history.redo_label

    @pyqtProperty(bool, notify=changed)
    def modified(self) -> bool:
        return self._history.modified

    @pyqtProperty(bool, notify=changed)
    def saving(self) -> bool:
        return self._saving

    @pyqtProperty(str, notify=changed)
    def outputName(self) -> str:
        """The name the next save will get (free right now)."""
        suffix = self._doc.path.suffix
        if not self.isPdf and self._doc.format == b"gif":
            suffix = ".png"
        elif not self.isPdf and self._doc.format == b"heic":
            suffix = ".jpg"  # HEIC is only read
        tag = st.output_tag(self._state)
        if self._save_limit:
            from ..handlers.target import size_label
            from .document import _limited_tag

            tag = _limited_tag(self._state, size_label(self._save_limit))
            if not self.isPdf and self._doc.format not in (b"jpeg", b"jpg", b"webp"):
                suffix = ".jpg"
        desired = self._doc.path.with_name(f"{self._doc.path.stem} ({tag}){suffix}")
        return outputs.free_path(desired, is_dir=False).name

    # ---- Exact size (images) ----

    @pyqtProperty(int, notify=changed)
    def outputWidth(self) -> int:
        size = None if self.isPdf else self._state.get("size")
        return int(size[0]) if size else 0

    @pyqtProperty(int, notify=changed)
    def outputHeight(self) -> int:
        size = None if self.isPdf else self._state.get("size")
        return int(size[1]) if size else 0

    @pyqtSlot(int, int)
    def setOutputSize(self, width: int, height: int) -> None:
        """"Exact size": the saved picture is scaled to width x height px;
        0 x 0 clears it."""
        if self.isPdf:
            return
        size = [int(width), int(height)] if width > 0 and height > 0 else None
        if size and not (16 <= size[0] <= 20000 and 16 <= size[1] <= 20000):
            return
        new = {**self._state, "size": size}
        if size:  # the crop takes that shape (largest such rect inside it, same center)
            new["crop"] = st.fit_crop(self._state["crop"], size[0] / size[1], *self._displayed_size())
        self._push(new, "Exact size" if size else "Free size")

    def _displayed_size(self) -> tuple[float, float]:
        """Image size as shown, after the user's rotation."""
        w, h = self._doc.page_size(0)
        return (h, w) if self._state["rot"] % 180 else (w, h)

    # ---- Limit file size (save sheet) ----

    @pyqtProperty(int, notify=changed)
    def saveLimit(self) -> int:
        """Bytes, or 0 for no limit."""
        return self._save_limit

    @pyqtSlot(str, result=str)
    def setSaveLimit(self, text: str) -> str:
        """"50 KB" sets the limit, "" clears it. Returns an error to show."""
        from ..handlers.target import parse_target

        if not text.strip():
            self._save_limit = 0
            self.changed.emit()
            return ""
        size = parse_target(text)
        if size is None:
            return "1 KB to 100 MB"
        self._save_limit = size
        self.changed.emit()
        return ""

    @pyqtProperty(str, notify=changed)
    def lastSaveNote(self) -> str:
        """After a save with a size limit: "48 KB", or "smallest possible:
        ... over 50 KB"."""
        return self._last_note

    # ------------------------------------------------- annotate / redact ---

    @pyqtProperty("QVariantList", notify=marksChanged)
    def marks(self) -> list:
        return list(st.layer(self._state, self._page)["marks"])

    @pyqtProperty("QVariantList", notify=marksChanged)
    def redactions(self) -> list:
        return list(st.layer(self._state, self._page)["redactions"])

    @pyqtProperty(bool, notify=changed)
    def hasMarks(self) -> bool:
        return st.has_marks(self._state)

    @pyqtProperty(int, notify=changed)
    def redactionCount(self) -> int:
        return sum(len(l["redactions"]) for l in st.layers(self._state))

    @pyqtProperty(int, notify=selectionChanged)
    def selectedMark(self) -> int:
        return self._selected

    @pyqtProperty(str, notify=optionsChanged)
    def annotateTool(self) -> str:
        return self._annotate_tool

    @pyqtProperty(str, notify=optionsChanged)
    def markColor(self) -> str:
        return self._color

    @pyqtProperty(int, notify=optionsChanged)
    def widthIndex(self) -> int:
        return self._width_index

    @pyqtProperty("QVariantList", constant=True)
    def swatches(self) -> list:
        return list(SWATCHES)

    @pyqtProperty("QVariantMap", constant=True)
    def widthPresets(self) -> dict:
        return {k: list(v) for k, v in WIDTHS.items()}

    @pyqtProperty(bool, notify=optionsChanged)
    def redactPreview(self) -> bool:
        return self._redact_preview

    @pyqtProperty("QVariantList", notify=searchChanged)
    def searchResults(self) -> list:
        return self._results

    @pyqtProperty(bool, notify=searchChanged)
    def searching(self) -> bool:
        return self._searching

    @pyqtProperty(str, notify=searchChanged)
    def searchTerm(self) -> str:
        return self._search_term

    @pyqtProperty(int, notify=searchChanged)
    def checkedCount(self) -> int:
        return sum(1 for r in self._results if r["checked"])

    @pyqtSlot(str)
    def setAnnotateTool(self, tool: str) -> None:
        if tool in ANNOTATE_TOOLS and tool != self._annotate_tool:
            self._annotate_tool = tool
            if tool != "select":
                self.selectMark(-1)
            self.optionsChanged.emit()

    @pyqtSlot(str)
    def setMarkColor(self, color: str) -> None:
        self._color = color
        self.optionsChanged.emit()
        if self._selected >= 0:
            self.updateMark(self._selected, {"color": color})

    @pyqtSlot(int)
    def setWidthIndex(self, index: int) -> None:
        self._width_index = min(max(index, 0), 3)
        self.optionsChanged.emit()

    @pyqtSlot(bool)
    def setRedactPreview(self, on: bool) -> None:
        self._redact_preview = bool(on)
        self.optionsChanged.emit()

    @pyqtSlot("QVariantMap", result=int)
    def addMark(self, data: dict) -> int:
        mark = _clean_mark(data)
        if mark is None:
            return -1
        mark = mk.clamped(mark, *self._doc.page_size(self._page))
        mark["id"] = self._new_id()
        lay = st.layer(self._state, self._page)
        self._push(st.with_layer(self._state, self._page, marks=[*lay["marks"], mark]), _LABELS[mark["type"]])
        return mark["id"]

    @pyqtSlot(int, "QVariantMap")
    def updateMark(self, mark_id: int, changes: dict) -> None:
        lay = st.layer(self._state, self._page)
        allowed = {k: v for k, v in changes.items() if k in ("color", "text", "rect", "size")}
        new = []
        for m in lay["marks"]:
            if m["id"] == mark_id:
                m = _clean_mark({**m, **allowed})
                if m is None:  # e.g. text edited down to nothing: the mark goes
                    continue
                m = mk.clamped(m, *self._doc.page_size(self._page))
                m["id"] = mark_id
            new.append(m)
        label = "Edit text" if "text" in allowed else "Change color" if "color" in allowed else "Edit"
        self._push(st.with_layer(self._state, self._page, marks=new), label)

    @pyqtSlot(int, float, float)
    def moveMark(self, mark_id: int, dx: float, dy: float) -> None:
        lay = st.layer(self._state, self._page)
        size = self._doc.page_size(self._page)
        new = [mk.clamped(mk.moved(m, dx, dy), *size) if m["id"] == mark_id and m["type"] in ("text", "rect", "arrow")
               else mk.moved(m, dx, dy) if m["id"] == mark_id else m for m in lay["marks"]]
        self._push(st.with_layer(self._state, self._page, marks=new), "Move")

    @pyqtSlot(int)
    def deleteMark(self, mark_id: int) -> None:
        lay = st.layer(self._state, self._page)
        self._push(st.with_layer(self._state, self._page, marks=[m for m in lay["marks"] if m["id"] != mark_id]),
                   "Delete")
        self.selectMark(-1)

    @pyqtSlot(int)
    def selectMark(self, mark_id: int) -> None:
        if mark_id != self._selected:
            self._selected = mark_id
            self.selectionChanged.emit()

    @pyqtSlot(float, float, float, result=int)
    def markAt(self, x: float, y: float, tolerance: float) -> int:
        """Id of the topmost mark at (x, y), or -1."""
        for m in reversed(st.layer(self._state, self._page)["marks"]):
            if mk.hit(m, x, y, tolerance):
                return m["id"]
        return -1

    @pyqtSlot(float, float, float, float)
    def addRedaction(self, x: float, y: float, w: float, h: float) -> None:
        pw, ph = self._doc.page_size(self._page)
        x0, y0 = min(max(x, 0.0), pw), min(max(y, 0.0), ph)
        x1, y1 = min(max(x + w, 0.0), pw), min(max(y + h, 0.0), ph)
        if x1 - x0 <= 0 or y1 - y0 <= 0:
            return
        lay = st.layer(self._state, self._page)
        box = {"id": self._new_id(), "rect": [round(x0, 2), round(y0, 2), round(x1 - x0, 2), round(y1 - y0, 2)]}
        self._push(st.with_layer(self._state, self._page, redactions=[*lay["redactions"], box]), "Redact area")

    @pyqtSlot(float, float, result=int)
    def redactionAt(self, x: float, y: float) -> int:
        for box in reversed(st.layer(self._state, self._page)["redactions"]):
            bx, by, bw, bh = box["rect"]
            if bx <= x <= bx + bw and by <= y <= by + bh:
                return box["id"]
        return -1

    @pyqtSlot(int)
    def deleteRedaction(self, box_id: int) -> None:
        lay = st.layer(self._state, self._page)
        self._push(st.with_layer(self._state, self._page,
                                 redactions=[b for b in lay["redactions"] if b["id"] != box_id]), "Remove redaction")

    @pyqtSlot()
    def clearRedactions(self) -> None:
        new = self._state
        for i, lay in enumerate(st.layers(self._state)):
            if lay["redactions"]:
                new = st.with_layer(new, i, redactions=[])
        self._push(new, "Remove all redactions")

    # ---- search and redact (PDFs) ----

    @pyqtSlot(str, bool, bool)
    def search(self, term: str, match_case: bool, whole_word: bool) -> None:
        from . import search as finder

        self._search_no += 1
        number = self._search_no
        self._search_term = term.strip()
        if not self.isPdf or not self._search_term:
            self._results, self._searching = [], False
            self.searchChanged.emit()
            return
        self._searching = True
        self.searchChanged.emit()
        doc = self._doc._doc

        def work() -> None:
            results = []
            for index in range(len(doc)):
                if number != self._search_no:  # a newer search started: stop
                    return
                with LOCK:  # one page at a time, so page renders can go in between
                    found = finder.find_on_page(doc[index], term, match_case, whole_word)
                for hit in found:
                    results.append({**hit, "page": index, "checked": True})
                if len(results) >= finder.MAX_RESULTS:
                    break
            self._searchDone.emit(number, results)

        threading.Thread(target=work, name="search", daemon=True).start()

    @pyqtSlot(int, bool)
    def setResultChecked(self, index: int, on: bool) -> None:
        if 0 <= index < len(self._results):
            self._results = [{**r, "checked": bool(on)} if i == index else r for i, r in enumerate(self._results)]
            self.searchChanged.emit()

    @pyqtSlot(bool)
    def setAllResultsChecked(self, on: bool) -> None:
        self._results = [{**r, "checked": bool(on)} for r in self._results]
        self.searchChanged.emit()

    @pyqtSlot()
    def redactChecked(self) -> None:
        """Every ticked match becomes redaction boxes (one undo step)."""
        chosen = [r for r in self._results if r["checked"]]
        if not chosen:
            return
        new = self._state
        for r in chosen:
            lay = st.layer(new, r["page"])
            boxes = [{"id": self._new_id(), "rect": rect} for rect in r["rects"]]
            new = st.with_layer(new, r["page"], redactions=[*lay["redactions"], *boxes])
        n = len(chosen)
        self._push(new, f"Redact {n} match{'es' if n != 1 else ''}")
        self._results = [r for r in self._results if not r["checked"]]
        self.searchChanged.emit()

    @pyqtSlot()
    def clearSearch(self) -> None:
        self._search_no += 1
        self._results, self._searching, self._search_term = [], False, ""
        self.searchChanged.emit()

    def _on_search_done(self, number: int, results: list) -> None:
        if number != self._search_no:
            return
        self._results, self._searching = results, False
        self.searchChanged.emit()

    def _new_id(self) -> int:
        self._next_id += 1
        return self._next_id

    # ---------------------------------------------------------------- Info

    @pyqtProperty(str, notify=metaChanged)
    def metaStatus(self) -> str:
        """idle, loading, ready or failed."""
        return self._meta_state

    @pyqtProperty(str, notify=metaChanged)
    def metaError(self) -> str:
        return self._meta_error

    @pyqtProperty("QVariantList", notify=metaChanged)
    def metaSections(self) -> list:
        if self._meta is None:
            return []
        current = st.meta(self._state)
        if self._sections_for is not current:  # QML reads it once per row: work it out once
            self._sections, self._sections_for = self._meta.sections(current), current
        return self._sections

    @pyqtProperty(bool, notify=metaChanged)
    def metaEditable(self) -> bool:
        """Single entries can be edited and removed (not TIFF / GIF / BMP)."""
        return self._meta is not None and (self.isPdf or self._meta.editable)

    @pyqtProperty(bool, notify=metaChanged)
    def metaAny(self) -> bool:
        """The file has metadata that can be removed."""
        return self._meta is not None and bool(self._meta.keys())

    @pyqtProperty(bool, notify=metaChanged)
    def metaClean(self) -> bool:
        """With the changes so far, nothing is left."""
        return self._meta is not None and bool(self._meta.keys()) and not self._meta.remaining(st.meta(self._state))

    @pyqtProperty(int, notify=metaChanged)
    def metaChangeCount(self) -> int:
        m = st.meta(self._state)
        return len(m["set"]) + len(m["drop"])

    @pyqtProperty(bool, notify=metaChanged)
    def metaHasThumbnail(self) -> bool:
        return self._meta is not None and self._meta.thumbnail() is not None

    @pyqtProperty(str, notify=metaChanged)
    def metaNote(self) -> str:
        """Why entries can't be edited one by one, if they can't."""
        if self._meta is None or self.isPdf or self._meta.editable:
            return ""
        if self._meta.kind == "heic":
            return ("Spindle can't write HEIC, so a saved copy is a JPG. Remove all makes a clean JPG; "
                    "edited copies keep these details (without the location, unless you keep it).")
        if self._meta.kind == "tiff":
            return ("TIFF keeps its metadata inside the image itself. Spindle can remove all of it "
                    "(the copy is re-saved without loss), but can't change single entries.")
        return f"{self.formatLabel} files carry no metadata Spindle can change."

    @pyqtProperty(bool, notify=changed)
    def locationChoice(self) -> bool:
        """Offer "Keep location" in the save sheet: the picture was edited
        (so the copy is a new image, which leaves the location out by
        default), the original has a GPS position, and Info hasn't already
        decided (removed it, or set a new one). Not for redacted copies,
        which carry no metadata at all."""
        if self.isPdf or self._meta is None or self._save_limit:
            return False  # (a size-limited copy carries no metadata at all)
        if not self._meta.editable and self._meta.kind != "heic":
            return False
        if st.pixels_unchanged(self._state) or st.has_redactions(self._state):
            return False
        m = st.meta(self._state)
        has_location = self._meta.location() is not None or "gps" in self._meta.keys()
        return has_location and "gps" not in m["drop"] and "gps" not in m["set"] and "all" not in m["drop"]

    @pyqtSlot()
    def loadMeta(self) -> None:
        if self._meta_state in ("loading", "ready"):
            return
        self._meta_state = "loading"
        self.metaChanged.emit()
        doc = self._doc

        def work() -> None:
            try:
                meta, error = doc.metadata(), ""
            except Exception as exc:  # unreadable: say so in the panel
                import traceback

                traceback.print_exc()
                meta, error = None, f"Couldn't read the metadata ({type(exc).__name__})"
            self._metaDone.emit(meta, error)

        threading.Thread(target=work, name="metadata", daemon=True).start()

    def _on_meta_done(self, meta, error: str) -> None:
        self._meta, self._meta_error = meta, error
        self._meta_state = "failed" if meta is None else "ready"
        self.metaChanged.emit()
        self.changed.emit()  # locationChoice

    def _meta_follow_state(self) -> None:
        """Undo / redo of a metadata change: refresh the panel."""
        current = st.meta(self._state)
        if current is not self._meta_seen:
            self._meta_seen = current
            if self._meta is not None:
                self.metaChanged.emit()

    @pyqtSlot(str, "QVariant", result=str)
    def setMeta(self, key: str, value) -> str:
        """Change a field; returns an error message, or "" when done."""
        from .metadata import MetaError

        if self._meta is None or not self.metaEditable:
            return ""
        try:
            value = self._meta.check(key, value)
        except MetaError as exc:
            return str(exc)
        m = st.meta(self._state)
        original = self._original_value(key)
        sets = {k: v for k, v in m["set"].items() if k != key}
        drop = [k for k in m["drop"] if k != key]
        if value != original and not (value == "" and not original):
            if value == "" and key != "gps":
                drop.append(key)
            else:
                sets[key] = value
        self._push_meta(sets, drop, f"Edit {self._meta_label(key)}")
        return ""

    @pyqtSlot(str)
    def removeMeta(self, key: str) -> None:
        if self._meta is None:
            return
        m = st.meta(self._state)
        sets = {k: v for k, v in m["set"].items() if k != key}
        drop = list(m["drop"]) if key in m["drop"] else [*m["drop"], key]
        if key not in self._meta.keys():
            drop = [k for k in drop if k != key]  # a value only added in this session
        self._push_meta(sets, drop, f"Remove {self._meta_label(key)}")

    @pyqtSlot(str)
    def restoreMeta(self, key: str) -> None:
        m = st.meta(self._state)
        sets = {k: v for k, v in m["set"].items() if k != key}
        drop = [k for k in m["drop"] if k != key]
        self._push_meta(sets, drop, f"Restore {self._meta_label(key)}")

    @pyqtSlot()
    def removeAllMeta(self) -> None:
        if self._meta is None or not self._meta.keys():
            return
        self._push_meta({}, sorted(self._meta.keys()), "Remove all metadata")

    @pyqtSlot(result=str)
    def metaXmp(self) -> str:
        return self._meta.xmp_text() if self._meta is not None else ""

    def _push_meta(self, sets: dict, drop: list, label: str) -> None:
        meta = {"set": sets, "drop": sorted(set(drop)), "clean": False}
        meta["clean"] = bool(self._meta.keys()) and not self._meta.remaining(meta)
        self._push({**self._state, "meta": meta}, label)

    def _original_value(self, key: str):
        if self.isPdf:
            from .metadata import PDF_DATES, _pdf_date

            name = key.split(":", 1)[1]
            value = self._meta.found["info"].get(name, "")
            if name in PDF_DATES and value:
                value = _pdf_date(value)
                if len(value) == 16:
                    value += ":00"
            return value
        if key == "gps":
            loc = self._meta.location()
            return [round(v, 7) for v in loc] if loc else None
        name = key.split(":", 1)[1]
        value = self._meta.field(name)
        if name == "datetaken" and len(value) == 16:
            value += ":00"
        return value

    def _meta_label(self, key: str) -> str:
        for section in self._meta.sections(st.meta(self._state)) if self._meta else []:
            for item in section["items"]:
                if item["key"] == key:
                    label = item["label"]
                    return label if label.split()[0].isupper() else label[:1].lower() + label[1:]
        return "metadata"

    # --------------------------------------------------------- QML helpers

    @pyqtSlot(str, result=str)
    def icon(self, name: str) -> str:
        return self._icon(name)

    # ------------------------------------------------------------- actions

    @pyqtSlot(str)
    def setTool(self, tool: str) -> None:
        if tool in TOOLS and tool != self._tool:
            self._tool = tool
            self.changed.emit()
            if tool == "metadata":
                self.loadMeta()

    @pyqtSlot(int)
    def goToPage(self, index: int) -> None:
        index = min(max(index, 0), self._doc.page_count - 1)
        if index != self._page:
            self._page = index
            self.selectMark(-1)
            self.changed.emit()
            self.marksChanged.emit()

    @pyqtSlot(int)
    def rotate(self, direction: int) -> None:
        op = "cw" if direction > 0 else "ccw"
        label = "Rotate right" if direction > 0 else "Rotate left"
        if self.isPdf:
            new = self._state
            targets = self._live_pages() if self._rotate_all else [self._page]
            for i in targets:
                new = st.turn_page(new, i, op)
            self._push(new, label, op)
        else:
            self._push(st.turn_image(self._state, op), label, op)

    @pyqtSlot(str)
    def flip(self, axis: str) -> None:
        if self.isPdf or axis not in ("h", "v"):
            return
        label = "Flip horizontally" if axis == "h" else "Flip vertically"
        self._push(st.turn_image(self._state, axis), label, axis)

    @pyqtSlot(float, float, float, float)
    def setCrop(self, x: float, y: float, w: float, h: float) -> None:
        self._apply_crop(st.clean_rect([x, y, w, h]), "Crop")

    @pyqtSlot()
    def clearCrop(self) -> None:
        self._apply_crop(None, "Reset crop")

    def _apply_crop(self, rect, label: str) -> None:
        if self.isPdf:
            new = self._state
            for i in (range(len(self._state["pages"])) if self._crop_all else [self._page]):
                new = st.set_page(new, i, crop=rect)
            self._push(new, label)
        else:
            self._push({**self._state, "crop": rect}, label)

    @pyqtSlot(str, float)
    def setAdjust(self, name: str, value: float) -> None:
        if self.isPdf or name not in st.ADJUST_KEYS:
            return
        value = round(min(max(value, -1.0), 1.0), 4)
        adjust = {**self._state["adjust"], name: value}
        self._push({**self._state, "adjust": adjust}, name.capitalize())

    @pyqtSlot()
    def resetAdjust(self) -> None:
        if not self.isPdf:
            self._push({**self._state, "adjust": dict(st.NO_ADJUST)}, "Reset colors")

    @pyqtSlot(bool)
    def setCropAllPages(self, on: bool) -> None:
        self._crop_all = bool(on)
        self.changed.emit()

    @pyqtSlot(bool)
    def setRotateAllPages(self, on: bool) -> None:
        self._rotate_all = bool(on)
        self.changed.emit()

    @pyqtSlot()
    def deletePage(self) -> None:
        if self.isPdf and not self.pageDeleted and self.keptPages > 1:
            self._push(st.set_page(self._state, self._page, deleted=True), "Delete page")

    @pyqtSlot()
    def restorePage(self) -> None:
        if self.isPdf and self.pageDeleted:
            self._push(st.set_page(self._state, self._page, deleted=False), "Restore page")

    @pyqtSlot()
    def undo(self) -> None:
        before = self._current()
        if self._history.undo():
            self._after_jump(before)

    @pyqtSlot()
    def redo(self) -> None:
        before = self._current()
        if self._history.redo():
            self._after_jump(before)

    @pyqtSlot()
    @pyqtSlot(bool)
    @pyqtSlot(bool, bool)
    def save(self, flatten: bool = False, keep_location: bool = False) -> None:
        if self._saving:
            return
        self._saving = True
        self.changed.emit()
        snapshot = self._state
        options = {"flatten": bool(flatten), "keep_location": bool(keep_location), "limit": self._save_limit}

        def work() -> None:
            try:
                path, error = str(self._doc.save(snapshot, options)), ""
            except OpenError as exc:
                path, error = "", str(exc)
            except Exception as exc:  # unexpected: keep the editor alive, say what happened
                import traceback

                traceback.print_exc()
                path, error = "", f"{type(exc).__name__}: {exc}"
            self._saveDone.emit(path, error)

        self._save_snapshot = snapshot
        threading.Thread(target=work, name="save", daemon=True).start()

    @pyqtSlot()
    def showInFolder(self) -> None:
        if self._last_saved is not None:
            platform_utils.reveal_in_file_manager(self._last_saved)

    # ------------------------------------------------------------- helpers

    def _live_pages(self) -> list[int]:
        return [i for i, p in enumerate(self._state["pages"]) if not p["deleted"]]

    def _push(self, new: dict, label: str, op: str = "") -> None:
        pages_before = self._state.get("pages")
        if not self._history.push(new, label):
            return
        if op:
            self.turned.emit(op)  # first: QML starts the turn before the new geometry lands
        self.changed.emit()
        self.marksChanged.emit()
        if self.isPdf and self._state["pages"] != pages_before:
            self.pagesChanged.emit()

    def _after_jump(self, before: dict) -> None:
        """After undo / redo: refresh, and animate a turn of the page on
        screen if that is what changed."""
        op = _turn_between(before, self._current())
        if op:
            self.turned.emit(op)
        self.changed.emit()
        self.marksChanged.emit()
        if self._selected >= 0 and all(m["id"] != self._selected for m in st.layer(self._state, self._page)["marks"]):
            self.selectMark(-1)
        if self.isPdf:
            self.pagesChanged.emit()

    def _on_save_done(self, path: str, error: str) -> None:
        self._saving = False
        if error:
            self.changed.emit()
            self.saveFailed.emit(error)
            return
        self._last_saved = Path(path)
        self._last_note = getattr(self._doc, "last_note", "") if self._save_limit else ""
        if self._history.state == self._save_snapshot:
            self._history.mark_saved()
        self.changed.emit()
        self.saved.emit(Path(path).name)


def _turn_between(before: dict, after: dict) -> str:
    r0, r1 = before["rot"], after["rot"]
    m0, m1 = before.get("mirror", False), after.get("mirror", False)
    if m0 == m1:
        return {90: "cw", 270: "ccw"}.get((r1 - r0) % 360, "")
    if r1 == (-r0) % 360:
        return "h"
    if r1 == (180 - r0) % 360:
        return "v"
    return ""


def _clean_mark(data: dict) -> dict | None:
    """A mark from QML, checked and rounded, or None if it's not usable."""
    kind = data.get("type")
    if kind not in mk.TYPES:
        return None

    def point(p):
        return [round(float(p[0]), 2), round(float(p[1]), 2)]

    mark = {"type": kind, "color": str(data.get("color") or SWATCHES[0])}
    try:
        if kind in ("pen", "highlight"):
            pts = [point(p) for p in data.get("points") or []]
            if not pts:
                return None
            mark.update(width=round(float(data["width"]), 3), points=pts)
        elif kind == "arrow":
            mark.update(width=round(float(data["width"]), 3), p1=point(data["p1"]), p2=point(data["p2"]))
        elif kind == "rect":
            x, y, w, h = (float(v) for v in data["rect"])
            if w <= 0 or h <= 0:
                return None
            mark.update(width=round(float(data["width"]), 3), rect=[round(x, 2), round(y, 2), round(w, 2), round(h, 2)])
        else:  # text
            text = str(data.get("text") or "").rstrip()
            if not text.strip():
                return None
            x, y, w, h = (float(v) for v in data["rect"])
            mark.update(size=max(1, round(float(data["size"]))), text=text,
                        rect=[round(x, 2), round(y, 2), round(w, 2), round(h, 2)])
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    return mark
