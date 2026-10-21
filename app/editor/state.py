"""Edit state and undo history. Pure Python, no Qt: easy to test.

The state is a plain dict that is never mutated in place: every change
makes a new one, and the history keeps the list of states. Undo / redo
just move along that list. Each state is small (a few numbers per page),
so even long sessions on big PDFs cost next to nothing.

Image state:
    {"rot": 0|90|180|270,          clockwise, applied after `mirror`
     "mirror": bool,               the source flipped left-right first
     "crop": [x, y, w, h] | None,  normalized 0..1, in the displayed
                                   (rotated) image
     "adjust": {"brightness": b, "contrast": c, "saturation": s},  -1..1
     "size": [w, h] | None,        "Exact size": the saved picture is
                                   scaled to exactly w x h px (the crop
                                   keeps that shape)
     "marks": [...], "redactions": [...]}

PDF state:
    {"pages": [{"rot": 0|90|180|270, "deleted": bool,
                "crop": [x, y, w, h] | None,
                "marks": [...], "redactions": [...]}, ...]}
    `rot` is added to the page's own rotation; `crop` is normalized in the
    page as displayed with that rotation.

Both also have "meta": the changes made in the Info tool, see
metadata.py ({"set": {...}, "drop": [...], "clean": bool}).

Marks (annotations) and redactions are kept in content units of the page
before the user's rotation, mirror and crop: image pixels (EXIF
orientation applied), or PDF points of the page as displayed with its own
rotation (y down). They belong to the content, so turning or cropping the
page never has to touch them. See marks.py for their fields.

Keeping the crop in displayed coordinates means it has to turn with the
picture: rotating or flipping also moves the crop rectangle (see
_turn_rect), so the same part of the picture stays selected.
"""

from __future__ import annotations

ADJUST_KEYS = ("brightness", "contrast", "saturation")
NO_ADJUST = {k: 0.0 for k in ADJUST_KEYS}
NO_META = {"set": {}, "drop": [], "clean": False}


def new_image_state() -> dict:
    return {"rot": 0, "mirror": False, "crop": None, "adjust": dict(NO_ADJUST), "size": None, "marks": [],
            "redactions": [], "meta": NO_META}


def new_pdf_state(pages: int) -> dict:
    return {"pages": [{"rot": 0, "deleted": False, "crop": None, "marks": [], "redactions": []}
                      for _ in range(pages)], "meta": NO_META}


def meta(state: dict) -> dict:
    return state.get("meta") or NO_META


def meta_changed(state: dict) -> bool:
    m = meta(state)
    return bool(m["set"] or m["drop"])


def layer(state: dict, index: int = 0) -> dict:
    """The part of the state that holds marks / redactions for a page."""
    return state["pages"][index] if "pages" in state else state


def with_layer(state: dict, index: int, **changes) -> dict:
    """A new state with `marks` / `redactions` of page `index` replaced."""
    if "pages" in state:
        return set_page(state, index, **changes)
    return {**state, **changes}


def layers(state: dict) -> list[dict]:
    return state["pages"] if "pages" in state else [state]


def has_marks(state: dict) -> bool:
    return any(l["marks"] for l in layers(state))


def has_redactions(state: dict) -> bool:
    return any(l["redactions"] for l in layers(state))


# ------------------------------------------------------------- geometry ---

def _turn_rect(rect: list | None, op: str) -> list | None:
    """Move a normalized rect along with the picture: "cw" / "ccw" rotate
    the displayed picture a quarter turn, "h" / "v" flip it."""
    if rect is None:
        return None
    x, y, w, h = rect
    if op == "cw":
        turned = [1 - y - h, x, h, w]
    elif op == "ccw":
        turned = [y, 1 - x - w, h, w]
    elif op == "h":
        turned = [1 - x - w, y, w, h]
    elif op == "v":
        turned = [x, 1 - y - h, w, h]
    else:
        raise ValueError(op)
    # Rounded so turning back and forth gives back the exact same state
    # (otherwise float noise would make an unchanged file look modified).
    return [round(v, 9) for v in turned]


def clean_rect(rect) -> list | None:
    """Clamp a crop to the picture; a crop covering (almost) all of it is
    no crop at all."""
    if rect is None:
        return None
    x, y, w, h = (float(v) for v in rect)
    x0, y0 = min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0)
    x1, y1 = min(max(x + w, 0.0), 1.0), min(max(y + h, 0.0), 1.0)
    if x1 - x0 < 1e-4 or y1 - y0 < 1e-4:
        return None
    if x0 < 1e-4 and y0 < 1e-4 and x1 > 1 - 1e-4 and y1 > 1 - 1e-4:
        return None
    return [round(v, 9) for v in (x0, y0, x1 - x0, y1 - y0)]


def fit_crop(crop: list | None, ratio: float, width: float, height: float) -> list | None:
    """The largest rect with width / height `ratio` (in pixels of a width x
    height picture) inside `crop` (normalized; None = everything), centered
    on it."""
    x, y, w, h = crop or [0.0, 0.0, 1.0, 1.0]
    norm = ratio * height / width  # the same ratio for normalized rects
    if w / h > norm:
        nw, nh = h * norm, h
    else:
        nw, nh = w, w / norm
    nx = min(max(x + (w - nw) / 2, 0.0), 1.0 - nw)
    ny = min(max(y + (h - nh) / 2, 0.0), 1.0 - nh)
    return clean_rect([nx, ny, nw, nh]) if (nw, nh) != (1.0, 1.0) else None


def turn_image(state: dict, op: str) -> dict:
    """Rotate ("cw" / "ccw") or flip ("h" / "v") the displayed image.

    Orientation is kept as (mirror the source, then rotate clockwise by
    rot). Flipping what is on screen after a rotation becomes a different
    (rot, mirror) pair: a horizontal flip turns rot into -rot, a vertical
    flip into 180 - rot, and both toggle mirror."""
    rot, mirror = state["rot"], state["mirror"]
    if op == "cw":
        rot = (rot + 90) % 360
    elif op == "ccw":
        rot = (rot - 90) % 360
    elif op == "h":
        rot, mirror = (-rot) % 360, not mirror
    elif op == "v":
        rot, mirror = (180 - rot) % 360, not mirror
    else:
        raise ValueError(op)
    size = state.get("size")
    if size and op in ("cw", "ccw"):
        size = [size[1], size[0]]  # the selection turned with the picture
    return {**state, "rot": rot, "mirror": mirror, "crop": _turn_rect(state["crop"], op), "size": size}


def turn_page(state: dict, index: int, op: str) -> dict:
    """Rotate one PDF page a quarter turn ("cw" / "ccw")."""
    if op not in ("cw", "ccw"):
        raise ValueError(op)
    pages = list(state["pages"])
    page = pages[index]
    step = 90 if op == "cw" else -90
    pages[index] = {**page, "rot": (page["rot"] + step) % 360, "crop": _turn_rect(page["crop"], op)}
    return {**state, "pages": pages}


def set_page(state: dict, index: int, **changes) -> dict:
    pages = list(state["pages"])
    pages[index] = {**pages[index], **changes}
    return {**state, "pages": pages}


def pixels_unchanged(state: dict) -> bool:
    """Nothing but metadata changed: the picture / pages stay as they are."""
    if has_marks(state) or has_redactions(state):
        return False
    if "pages" in state:
        return all(p["rot"] == 0 and not p["deleted"] and p["crop"] is None for p in state["pages"])
    return (state["rot"] == 0 and not state["mirror"] and state["crop"] is None and not state.get("size")
            and all(abs(v) < 1e-6 for v in state["adjust"].values()))


def is_identity(state: dict) -> bool:
    return pixels_unchanged(state) and not meta_changed(state)


def output_tag(state: dict) -> str:
    """Name tag for the saved file. "redacted" whenever anything was
    redacted (so it's obvious which copy is safe to share); otherwise
    "annotated" or "cropped" when that is all that changed, "clean" when
    all metadata was removed and nothing else changed, else "edited"."""
    if has_redactions(state):
        return "redacted"
    if meta_changed(state):
        if pixels_unchanged(state) and meta(state)["clean"]:
            return "clean"
        return "edited"
    if "pages" in state:
        turned = any(p["rot"] or p["deleted"] for p in state["pages"])
        cropped = any(p["crop"] is not None for p in state["pages"])
    else:
        turned = (state["rot"] != 0 or state["mirror"]
                  or any(abs(v) >= 1e-6 for v in state["adjust"].values()))
        cropped = state["crop"] is not None
    marked = has_marks(state)
    size = state.get("size")
    if size and not turned and not marked:
        return f"{size[0]}x{size[1]}"
    if marked and not turned and not cropped and not size:
        return "annotated"
    if not turned and not marked:
        return "cropped"
    return "edited"


# -------------------------------------------------------------- history ---

class History:
    """A list of states with a cursor. `push` drops anything that was
    undone; `modified` compares against the state that was last saved."""

    def __init__(self, initial: dict) -> None:
        self._states: list[dict] = [initial]
        self._labels: list[str] = [""]
        self._index = 0
        self._saved = initial

    @property
    def state(self) -> dict:
        return self._states[self._index]

    @property
    def can_undo(self) -> bool:
        return self._index > 0

    @property
    def can_redo(self) -> bool:
        return self._index < len(self._states) - 1

    @property
    def undo_label(self) -> str:
        return self._labels[self._index] if self.can_undo else ""

    @property
    def redo_label(self) -> str:
        return self._labels[self._index + 1] if self.can_redo else ""

    @property
    def modified(self) -> bool:
        return self.state != self._saved

    def push(self, state: dict, label: str) -> bool:
        """Record a new state. Returns False (and records nothing) if it
        equals the current one, so a click that changes nothing doesn't
        fill the undo list."""
        if state == self.state:
            return False
        del self._states[self._index + 1:]
        del self._labels[self._index + 1:]
        self._states.append(state)
        self._labels.append(label)
        self._index += 1
        return True

    def undo(self) -> bool:
        if not self.can_undo:
            return False
        self._index -= 1
        return True

    def redo(self) -> bool:
        if not self.can_redo:
            return False
        self._index += 1
        return True

    def mark_saved(self) -> None:
        self._saved = self.state
