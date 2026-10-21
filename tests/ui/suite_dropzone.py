"""Shortcut-first drop zone, popup vs drop zone, and combined PDFs."""
from harness import *
import shutil, pathlib
from tests.conftest import make_pdf, make_image, make_photo
from app.window import PROBE_MS
D = pathlib.Path(S) / "dropzone"; shutil.rmtree(D, ignore_errors=True); D.mkdir()
use_test_handlers({"TXT": 0.4})
u = lambda p: "file://" + str(p)
pdfs = [make_pdf(D / f"{n}.pdf", pages=k) for n, k in (("zeta", 2), ("alpha", 3))]
imgs = [make_image(D / "c-wide.png", "PNG", size=(300, 100)), make_photo(D / "a-tall.jpg", size=(150, 400)),
        make_image(D / "b.bmp", "BMP", size=(96, 96))]
fake = D / "doc.pdf"; fake.write_bytes(b"%PDF-1.4\n")
def focus_lost(): b.window_active_changed(True); b.window_active_changed(False)
texts = []
b.stateChanged.connect(lambda: texts.append(b.statusText))
def pages(p):
    import pymupdf
    with pymupdf.open(p) as doc: return [(pg.rect.width, pg.rect.height) for pg in doc]
def near(got, want): return len(got) == len(want) and all(abs(a - x) < 0.6 and abs(b_ - y) < 0.6 for (a, b_), (x, y) in zip(got, want))
def drop_on(urls, name):
    drag(urls, *wedge(name, urls)); return drop()
def park_and_run(urls, name, switch=False):
    drag(urls); drop()                       # center: parks
    if switch: b.switchWheel()
    b.activate(names().index(name))
run([
 # ---- drop zone: shortcut with nothing in hand
 (0, lambda: set_drag(False)),
 (100, w.show_wheel),
 (300, lambda: check("opens as a drop zone with ×", b.dropZone and not b.pinned)),
 (0, click_out), (300, lambda: check("click outside keeps it open", b.is_shown)),
 (0, focus_lost), (300, lambda: check("focus loss keeps it open", b.is_shown)),
 (0, lambda: QTest.keyClick(v, Qt.Key.Key_Escape)), until(hidden, "Esc closes it"),
 (0, w.show_wheel), (300, w.toggle), until(hidden, "the shortcut again closes it"),
 # one completed action closes it
 (0, w.show_wheel), (300, lambda: drop_on([u(fake)], "TXT")),
 (100, lambda: check("running: still open", b.is_shown and b.busy)),
 until(hidden, "closes after one completed action"),
 (0, lambda: check("the action ran", [x[1] for x in calls()] == ["doc.pdf"], str(calls()))),
 # parked, then a wedge click: runs and closes
 (0, w.show_wheel), (300, lambda: park_and_run([u(fake)], "TXT")),
 until(hidden, "park + click a wedge: runs, then closes"),
 # pin on top of a drop zone: stays after an action; unpinned it is a drop zone again
 (0, w.show_wheel), (300, b.togglePin), (100, lambda: drop_on([u(fake)], "TXT")),
 until(lambda: not b.busy, "pinned drop zone: action done"),
 (900, lambda: check("pinned: stays open", b.is_shown)),
 (0, b.togglePin), (100, lambda: check("unpinned: a drop zone again", b.dropZone and b.is_shown)),
 (0, focus_lost), (300, lambda: check("...so focus loss still doesn't close it", b.is_shown)),
 (0, lambda: QTest.keyClick(v, Qt.Key.Key_Escape)), until(hidden, "closed"),
 # ---- popup: a drag is under way when the shortcut is pressed
 (0, lambda: set_drag(True)), (0, w.show_wheel),
 (300, lambda: check("mid-drag: opens as a popup", not b.dropZone)),
 (0, focus_lost), until(hidden, "popup: focus loss closes it"),
 (0, w.show_wheel), (300, click_out), until(hidden, "popup: click outside closes it"),
 # ---- can't tell (Wayland): popup first, drop zone if no drag comes
 (0, lambda: set_drag(None)), (0, w.show_wheel),
 (100, lambda: check("probing: popup", not b.dropZone)),
 (PROBE_MS + 200, lambda: check("no drag came: drop zone", b.dropZone)),
 (0, w.toggle), until(hidden, "closed"),
 (0, w.show_wheel), (100, lambda: drag([u(fake)])),
 (PROBE_MS + 200, lambda: check("a drag came: stays a popup", not b.dropZone)),
 (0, lambda: (track(2, 2), drop())), until(hidden, "popup: drop outside the ring cancels"),
 # ---- combined PDFs (real handlers in the helper)
 (0, lambda: set_drag(True)), (0, w.show_wheel),
 (300, lambda: (texts.clear(), park_and_run([u(p) for p in imgs], "PDF", switch=True))),  # images open on Actions
 until(hidden, "3 images -> PDF: done, closes"),
 (0, lambda: check("one combined PDF named after the first file, pages in drop order, each its own size",
                   near(pages(D / "c-wide (combined).pdf"), [(225, 75), (112.5, 300), (72, 72)]),
                   str(sorted(p.name for p in D.iterdir())))),
 (0, lambda: check("...and no per-image PDFs", not (D / "a-tall.pdf").exists() and not (D / "b.pdf").exists())),
 (0, lambda: check("pill showed progress as one file, then 'Combined'", "Combined" in texts and not any("/3" in t for t in texts), str(texts[-6:]))),
 (0, w.show_wheel), (300, lambda: (texts.clear(), drop_on([u(p) for p in pdfs], "Merge"))),
 until(hidden, "2 PDFs -> Merge: done, closes"),
 (0, lambda: check("merged PDF: zeta's 2 pages then alpha's 3", len(pages(D / "zeta (combined).pdf")) == 5)),
 (0, w.show_wheel), (300, lambda: (texts.clear(), park_and_run([u(imgs[1]), u(pdfs[1]), u(imgs[0])], "Merge", switch=True))),
 until(hidden, "image + PDF + image -> Merge: done, closes"),
 (0, lambda: check("mixed: one PDF named after the first file, 1 + 3 + 1 pages", len(pages(D / "a-tall (combined).pdf")) == 5,
                   str(sorted(p.name for p in D.iterdir())))),
 (0, w.show_wheel), (300, lambda: drag([u(pdfs[0])])),
 (0, lambda: check("a single PDF has no Merge", "Merge" not in names(), str(names()))),
 (0, lambda: QTest.keyClick(v, Qt.Key.Key_Escape)), until(hidden, "closed"),
])
