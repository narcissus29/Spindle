from harness import *
import shutil, pathlib
from tests.conftest import make_pdf, make_image
D = pathlib.Path(S) / "step2"; shutil.rmtree(D, ignore_errors=True); D.mkdir()
use_test_handlers({"DOCX": 1.2, "Crop": 0.3}, keep_real={("pdf", "TXT"), ("image", "WEBP"), ("image", "JPG")})
pill = v.rootObject().findChild(QObject, "centerPill")
real_pdfs = [make_pdf(D / f"real{i}.pdf", pages=2) for i in range(3)]
fake = []
for n in ("a.pdf", "b.pdf", "c.pdf", "d-crash.pdf", "e.pdf"):
    (D / n).write_bytes(b"%PDF-1.4\n"); fake.append(D / n)
img = make_image(D / "photo.png", "PNG", size=(120, 80))
u = lambda p: "file://" + str(p)
TXT = (c + 110, c)          # PDF Convert: DOCX top, TXT right, JPG bottom, PNG left
DOCX = (c + 5, c - 110)
texts = []
def watch_text(): texts.append(pill.property("text"))
pill.textChanged.connect(watch_text) if hasattr(pill, "textChanged") else None
run([
 # 1. unpinned single file, REAL handler: stays open, progress, Done, closes
 (200, w.show_wheel),
 (300, lambda: (texts.clear(), drag([u(real_pdfs[0])], *TXT), drop())),
 (0, lambda: check("single drop: wheel stays open while it runs", b.is_shown and b.busy)),
 until(lambda: "Done" in texts, "pill showed 'Done'"),
 until(hidden, "...then the wheel closed"),
 (0, lambda: check("real output next to the source (TXT, even dropped mid-switch)", (D / "real0.txt").exists() and not (D / "real0.jpg").exists())),
 # 2. batch of 3 real PDFs -> progress n/3
 (0, w.show_wheel),
 (300, lambda: (texts.clear(), drag([u(p) for p in real_pdfs], *TXT), drop())),
 until(hidden, "batch of 3 finished and closed"),
 (0, lambda: check("pill counted files (x/3)", any(t.endswith("/3") for t in texts), str(texts))),
 (0, lambda: check("3 outputs, 2nd run of real0 got a new name", (D / "real0 (1).txt").exists() and (D / "real1.txt").exists())),
 # 3. Esc mid-run hides, job continues, notification afterwards
 (0, lambda: (notes.clear(), w.show_wheel())),
 (300, lambda: (drag([u(fake[0])], *DOCX), drop())),
 until(lambda: b.statusText.endswith("%"), "single slow file shows a percentage"),
 (0, lambda: QTest.keyClick(v, Qt.Key.Key_Escape)),
 until(hidden, "Esc hides the wheel mid-run"),
 (0, lambda: check("...the job is still running", b.busy)),
 until(lambda: notes, "desktop notification when it finishes"),
 (0, lambda: check("notification text", notes[-1] == ("Convert to DOCX: done", "a.pdf"), str(notes[-1]))),
 # 4. cancel by clicking the center pill while busy
 (0, lambda: (notes.clear(), open(LOG, "w").close(), w.show_wheel())),
 (300, lambda: (drag([u(p) for p in fake[:3]], *DOCX), drop())),
 until(lambda: b.busy and b.statusText == "0/3", "batch of 3 slow files running"),
 (0, lambda: QTest.mouseMove(v, at(c, c))),
 (200, lambda: check("hovering the busy pill shows red 'Cancel'", pill.property("text") == "Cancel" and pill.property("danger"))),
 (0, lambda: click(at(c, c))),
 until(lambda: "Cancelled" in (pill.property("text"), b.statusText), "pill says 'Cancelled'"),
 until(hidden, "...then closes"),
 (0, lambda: check("cancelled files never finished, no notification", calls() == [] and notes == [], f"calls={calls()} notes={notes}")),
 (0, lambda: check("no half-written temp files left", not [p for p in D.iterdir() if p.name.startswith(".~")])),
 # 5. crash in the helper: that file fails, the batch continues
 (0, lambda: (open(LOG, "w").close(), w.show_wheel())),
 (300, lambda: (texts.clear(), drag([u(fake[2]), u(fake[3]), u(fake[4])], *wedge("PNG", [u(fake[2]), u(fake[3]), u(fake[4])])), drop())),
 until(lambda: "1 failed" in texts, "crash: pill says '1 failed'"),
 (0, lambda: check("the other two files still ran", sorted(x[1] for x in calls()) == ["c.pdf", "e.pdf"], str(calls()))),
 until(hidden, "...then closes"),
 # 6. park a PDF: thumbnail rendered by the helper, crossfades in
 (0, w.show_wheel),
 (300, lambda: (drag([u(real_pdfs[1])]), drop())),
 until(lambda: b.parkedThumb.endswith(".png"), "parked PDF gets a rendered page thumbnail"),
 (0, lambda: QTest.keyClick(v, Qt.Key.Key_Escape)),
 until(hidden, "closed"),
 # 7. real image conversion: PNG -> WEBP through the wheel (parked, scroll to Convert, click)
 (0, w.show_wheel),
 (300, lambda: (drag([u(img)]), drop(), scroll())),
 (500, lambda: (log := names(), seen.__setitem__("webp", at(*[(c + 110, c), (c + 85, c + 70)][0])))),
 (0, lambda: None),
 until(lambda: b.wheelName == "convert", "scrolled to Convert"),
 (0, lambda: seen.__setitem__("i", names().index("WEBP"))),
 (0, lambda: seen.__setitem__("pos", __import__("math").radians(seen["i"] * 360 / len(names())))),
 (0, lambda: click(at(c + 110 * __import__("math").sin(seen["pos"]), c - 110 * __import__("math").cos(seen["pos"])))),
 until(hidden, "WEBP wedge ran and the wheel closed"),
 (0, lambda: check("photo.webp written", (D / "photo.webp").exists() and (D / "photo.webp").read_bytes()[8:12] == b"WEBP")),
 # 8. pinned: stays open, Done, clears
 (0, w.show_wheel),
 (300, lambda: b.togglePin()),
 (100, lambda: (texts.clear(), drag([u(fake[1])], c - 100, c + 30), drop())),
 until(lambda: "Done" in texts, "pinned: 'Done'"),
 (0, lambda: check("pinned: still open", b.is_shown)),
 (0, w.toggle),
 until(hidden, "closed"),
])
