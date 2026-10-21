"""Compress to a target size: the sub-ring on parked files, Custom typing,
going back, batches and misses. Real helper, real compression."""
from harness import *
import shutil, pathlib
from PyQt6.QtCore import QEvent
from PyQt6.QtGui import QKeyEvent
from tests.conftest import make_pdf, make_photo
D = pathlib.Path(S) / "target"; shutil.rmtree(D, ignore_errors=True); D.mkdir()
u = lambda p: "file://" + str(p)
photo = make_photo(D / "photo.jpg", size=(2400, 1800))
photo2 = make_photo(D / "second.png", size=(1200, 900), fmt="PNG")
vector = make_pdf(D / "letter.pdf", pages=30)
SHOTS = os.environ.get("SHOTS")

def park(urls):
    drag(urls); drop()
def wedge_click(name):
    click(at(*wedge(name)))
def type_text(text):
    for ch in text:
        for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            QGuiApplication.sendEvent(v, QKeyEvent(kind, Qt.Key.Key_unknown, Qt.KeyboardModifier.NoModifier, ch))
def key(k): QTest.keyClick(v, k)
def shot(name):
    if SHOTS:
        v.grabWindow().save(os.path.join(SHOTS, f"target-{name}.png"))
def out(name): return D / name
import re
done = lambda: not b.busy and b.statusText not in ("", "Working…") and not re.fullmatch(r"\d+%", b.statusText)

run([
 (0, w.show_wheel), (300, b.togglePin),
 # ---- the sub-ring opens on parked files, and goes back
 (300, lambda: park([u(photo)])),
 (300, lambda: wedge_click("Compress")),
 (500, lambda: check("Compress opens the target ring", names() == list(handlers.COMPRESS_TARGETS) and b.subRing == "Compress", str(names()))),
 (0, lambda: check("the pill says what it's for", b.subRingTitle == "Compress to…")),
 (0, lambda: shot("ring")),
 (0, lambda: click(at(c, c))),
 (500, lambda: check("clicking the center goes back", b.subRing == "" and "Compress" in names() and b.parked)),
 (0, lambda: wedge_click("Compress")), (500, lambda: key(Qt.Key.Key_Escape)),
 (400, lambda: check("Esc goes back, the wheel stays", b.subRing == "" and b.is_shown and b.parked)),
 (0, lambda: wedge_click("Compress")), (500, scroll),
 (400, lambda: check("scrolling goes back", b.subRing == "")),
 (0, lambda: wedge_click("Compress")),
 (500, lambda: QTest.mouseClick(v, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, at(c + 120, c), 600)),
 (400, lambda: check("right-click goes back", b.subRing == "")),
 # ---- a size: one click
 (0, lambda: wedge_click("Compress")), (500, lambda: wedge_click("50 KB")),
 until(done, "50 KB runs"),
 (0, lambda: check("pill: under the target with a tick", b.statusText.endswith("✓") and not b.statusWarn, b.statusText)),
 (0, lambda: check("photo (50 KB).jpg under 50,000 bytes", out("photo (50 KB).jpg").exists()
                   and 40_000 <= out("photo (50 KB).jpg").stat().st_size <= 50_000,
                   str(out("photo (50 KB).jpg").stat().st_size) if out("photo (50 KB).jpg").exists() else "missing")),
 (0, lambda: check("back on the Actions wheel", b.subRing == "" and "Compress" in names())),
 # ---- Custom: type a number
 (1600, lambda: park([u(photo)])),
 (300, lambda: wedge_click("Compress")), (500, lambda: wedge_click("Custom")),
 (400, lambda: check("Custom asks for a size", b.customEntry)),
 (0, lambda: shot("custom")),
 (0, lambda: type_text("abc")),  # not a number: refused by the field
 (0, lambda: type_text("75")), (0, lambda: key(Qt.Key.Key_Return)),
 until(done, "the typed size runs"),
 (0, lambda: check("photo (75 KB).jpg", out("photo (75 KB).jpg").exists() and out("photo (75 KB).jpg").stat().st_size <= 75_000)),
 (0, lambda: check("remembered for next time", cfg.compress_custom == "75 KB", cfg.compress_custom)),
 (1600, lambda: park([u(photo)])),
 (300, lambda: wedge_click("Compress")), (500, lambda: wedge_click("Custom")),
 (400, lambda: key(Qt.Key.Key_Escape)),
 (300, lambda: check("Esc in the field: back to the target ring", not b.customEntry and b.subRing == "Compress")),
 (0, lambda: key(Qt.Key.Key_Escape)),
 (300, lambda: check("Esc again: back to the wheel", b.subRing == "" and b.is_shown)),
 # ---- batch
 (0, lambda: park([u(photo), u(photo2)])),
 (300, lambda: wedge_click("Compress")), (500, lambda: wedge_click("20 KB")),
 until(done, "a batch runs"),
 (0, lambda: check("batch pill", b.statusText == "2 of 2 under 20 KB ✓", b.statusText)),
 (0, lambda: check("each file under the target", all(p.stat().st_size <= 20_000 for p in
                   (out("photo (20 KB).jpg"), out("second (20 KB).jpg"))))),
 # ---- a miss
 (1600, lambda: park([u(vector)])),
 (300, b.switchWheel),  # PDFs open on Convert
 (500, lambda: wedge_click("Compress")), (500, lambda: wedge_click("Custom")),
 (300, lambda: type_text("2")), (0, lambda: key(Qt.Key.Key_Return)),
 until(done, "an unreachable size runs"),
 (0, lambda: check("never claims success", b.statusText.startswith("Smallest:") and b.statusWarn, b.statusText)),
 (1000, lambda: shot("miss")),
 (0, lambda: check("the smallest copy is kept", out("letter (2 KB).pdf").exists())),
 # ---- dropping on Compress is still one click (the preset)
 (1600, lambda: (drag([u(photo)], *wedge("Compress", [u(photo)])), drop())),
 until(done, "dropping on Compress runs the preset"),
 (0, lambda: check("preset output", out("photo (compressed).jpg").exists())),
])
print("FAILS:", fails)
