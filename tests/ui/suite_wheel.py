"""Earlier suites (close rules, park, batch, pin) on the step-2 architecture."""
from harness import *
import shutil, pathlib, math
from tests.conftest import make_image
D = pathlib.Path(S) / "regress"; shutil.rmtree(D, ignore_errors=True); D.mkdir()
use_test_handlers({"DOCX": 0.4, "Crop": 0.2})
pdfs = []
for i in range(3):
    (D / f"doc{i}.pdf").write_bytes(b"%PDF-1.4\n"); pdfs.append("file://" + str(D / f"doc{i}.pdf"))
pngs = ["file://" + str(make_image(D / f"img{i}.png", "PNG")) for i in range(3)]
DOCX = (c + 5, c - 110)
CROP = (c - 110, c + 40)
def focus_lost(): b.window_active_changed(True); b.window_active_changed(False)
def btn(angle):
    R = c * 0.86; a = math.radians(angle)
    return at(c + R * math.sin(a), c - R * math.cos(a))
n = lambda: len(calls())
run([
 # ---- close rules (idle wheel)
 (100, w.show_wheel), (300, click_out), until(hidden, "idle: click outside hides"),
 (0, w.show_wheel), (300, focus_lost), until(hidden, "idle: focus loss hides"),
 (0, w.show_wheel), (300, lambda: click(at(c, c))), (400, lambda: check("idle: click on the hub keeps it open", b.is_shown)),
 (0, lambda: QTest.keyClick(v, Qt.Key.Key_Escape)), until(hidden, "idle: Esc hides"),
 (0, w.show_wheel), (300, w.toggle), until(hidden, "idle: shortcut again hides"),
 (0, lambda: (w.show_wheel(), b.window_active_changed(False))),  # stale deactivation from the last close
 (300, lambda: check("reopen: a stale 'deactivated' event doesn't close the new wheel", b.is_shown)),
 (0, lambda: QTest.keyClick(v, Qt.Key.Key_Escape)), until(hidden, "closed"),
 # ---- drag-first flow
 (0, w.show_wheel), (300, lambda: (drag([pdfs[0]]), focus_lost())),
 (300, lambda: check("drag over the wheel: focus loss keeps it open", b.is_shown)),
 (0, lambda: (track(2, 2), drop())), until(hidden, "drop outside the ring cancels"),
 (0, lambda: check("...and runs nothing", n() == 0)),
 (0, w.show_wheel), (300, lambda: (drag([pdfs[0]]), QMetaObject.invokeMethod(wheel, "endDrag"), b.dragLeave())),
 (300, lambda: check("drag left: stays open", b.is_shown)), (0, focus_lost), until(hidden, "drag left, then focus loss hides"),
 (0, w.show_wheel), (300, lambda: check("PDF + TXT refused as 'Mixed files'", not b.dragEnter([pdfs[0], "file:///tmp/x.txt"]) and b.refusedText == "Mixed files")),
 until(lambda: not b.refused, "refusal clears itself", 3), (0, focus_lost), until(hidden, "closed"),
 # ---- park
 (0, w.show_wheel), (300, lambda: check("park 3 PNGs: stack of 3 with first thumbnail", drag(pngs) and drop() and b.parked and b.fileCount == 3 and b.parkedThumb.endswith("img0.png"))),
 (2000, lambda: check("parked: still open 2 s later", b.is_shown and b.parked)),
 (0, scroll), until(lambda: b.wheelName == "convert" and "PNG" not in names(), "parked: scroll switches to Convert (no PNG target)"),
 (0, lambda: (QTest.mouseMove(v, at(*DOCX)), click(at(*DOCX)))),
 until(hidden, "parked: click a wedge runs it on all 3, then closes"),
 (0, lambda: check("...3 image files ran", sorted(x[1] for x in calls()) == ["img0.png", "img1.png", "img2.png"] and all(x[0].startswith("image:") for x in calls()), str(calls()))),
 (0, lambda: (open(LOG, "w").close(), w.show_wheel())), (300, lambda: (drag(pngs[:1]), drop())), (100, click_out), until(hidden, "parked: click outside cancels"),
 (0, w.show_wheel), (300, lambda: (drag(pngs[:1]), drop(), focus_lost())), until(hidden, "parked: focus loss cancels"),
 (0, w.show_wheel), (300, lambda: (drag(pngs[:1]), drop(), QTest.keyClick(v, Qt.Key.Key_Escape))), until(hidden, "parked: Esc cancels"),
 (0, lambda: check("...none of those ran anything", n() == 0)),
 # ---- batch + mixed
 (0, w.show_wheel), (300, lambda: (drag([pdfs[0], pngs[0]]), check("PDF + PNG: shared options only", b.formatLabel == "2 files" and b.wheelName == "actions" and b._wheels == ["convert", "actions"]))),
 (0, lambda: (track(*CROP), drop())), until(hidden, "mixed batch ran and closed"),
 (0, lambda: check("...each file through its own type's handler", sorted(x[0] for x in calls()) == ["image:Crop", "pdf:Crop"], str(calls()))),
 # ---- pin
 (0, lambda: (open(LOG, "w").close(), w.show_wheel())), (300, lambda: click(btn(45))), (300, lambda: check("pin button pins", b.pinned)),
 (0, focus_lost), (300, lambda: check("pinned: focus loss keeps it open", b.is_shown)),
 (0, click_out), (400, lambda: check("pinned: click outside keeps it open", b.is_shown)),
 (0, lambda: (drag([pdfs[0]], *DOCX), drop())), until(lambda: b.statusText == "Done", "pinned: single drop runs, shows 'Done'"),
 (0, lambda: check("pinned: still open and ready for the next drop", b.is_shown and b.idle)),
 until(lambda: b.statusText == "", "pinned: 'Done' clears"),
 (0, lambda: (drag(pdfs, *DOCX), drop())), (150, lambda: (seen.__setitem__("p1", b.statusText), drag([pdfs[0]], *DOCX), drop(), seen.__setitem__("p2", b.statusText))),
 until(lambda: b.statusText == "Done", "pinned: queued drops finish"),
 (0, lambda: check(f"pinned: queue grows the total ({seen['p1']!r} -> {seen['p2']!r})", seen["p1"].endswith("/3") and seen["p2"].endswith("/4") and n() == 5)),
 (0, lambda: (drag([pdfs[0]], 2, 2), drop())), (300, lambda: check("pinned: drop outside refused, stays open", b.is_shown and n() == 5)),
 (0, lambda: (QTest.mouseMove(v, btn(45)), track(btn(45).x() - org().x(), btn(45).y() - org().y()))),
 (200, lambda: check("hovering the pin highlights no wedge", wheel.property("hoveredIndex") == -1)),
 (0, lambda: click(btn(59))), until(hidden, "× closes the pinned wheel"),
 (0, w.show_wheel), (300, lambda: check("reopens unpinned", not b.pinned)),
 (0, lambda: click(btn(45))), (300, lambda: QTest.keyClick(v, Qt.Key.Key_Escape)), until(hidden, "pinned: Esc closes"),
 (0, w.show_wheel), (300, lambda: (click(btn(45)), w.toggle())), until(hidden, "pinned: shortcut closes"),
])
