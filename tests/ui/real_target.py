"""Real pointer + real keyboard (GNOME, Mutter RemoteDesktop): Compress >
Custom must get the keys typed on the actual keyboard, in each wheel mode
(popup, drop zone, pinned). Files are parked through the bridge (a real
file drag can't be injected); everything after that is real input.

    .venv/bin/python tests/ui/real_target.py
"""
import os, sys, math, tempfile, pathlib
HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "real_pin.py")).read()
exec(src.split("\nsteps = [")[0])  # the shared setup: underlay, session, pointer helpers
from PyQt6.QtCore import QUrl
from app import handlers
sys.path.insert(0, os.path.dirname(HERE))
from tests.conftest import make_photo

D = pathlib.Path(tempfile.mkdtemp(prefix="spindle-real-target-"))
photo = make_photo(D / "photo.jpg", size=(800, 600))
jobs = []
b.jobRequested.connect(jobs.append)
MID = (wheel.property("innerR") + wheel.property("outerR")) / 2

def key(keysym):
    from PyQt6.QtCore import QMetaType
    from PyQt6.QtDBus import QDBusArgument

    for down in (True, False):
        call(sess, "NotifyKeyboardKeysym", QDBusArgument(keysym, QMetaType.Type.UInt.value), down)
def type_digits(text):
    for ch in text:
        key(ord(ch))
def names(): return [o["name"] for o in b.options]
def click_wedge(name):
    i = names().index(name)
    move_local(on_wheel(i * 360 / len(names()), MID)); press()
def mode(v):
    def f(): DRAG["v"] = v
    return f
def park():
    b.dragEnter([QUrl.fromLocalFile(str(photo))]); b.park()

steps = [
 (100, under.showMaximized),
 (1200, start_session),
 (300, lambda: (home(), move_global(400, 400))), (400, calib),
 (0, lambda: move_local(QPoint(700, 300))), (400, verify),
]
for label, drag, pin in [("popup", True, False), ("drop zone", False, False), ("pinned", True, True)]:
    steps += [(0, w.hide_wheel), (500, mode(drag)), (0, spot(-1, -1)), (0, w.show_wheel), (800, guard)]
    if pin:
        steps += real_pin_click()
    steps += [(0, park), (400, lambda: click_wedge("Compress")),
              (600, lambda label=label: check(f"{label}: target ring", b.subRing == "Compress")),
              (0, lambda: click_wedge("Custom")),
              (500, lambda label=label: check(f"{label}: asks for a size", b.customEntry)),
              (0, lambda: jobs.clear()),
              (0, lambda: type_digits("60")), (200, lambda: key(0xff0d)),  # Return
              (600, lambda label=label: check(f"{label}: real typing runs 60 KB",
                                              [j.option for j in jobs] == ["60 KB"], str([j.option for j in jobs])))]
    # Esc on the real keyboard: back out of the ring, wheel stays
    steps += [(1500, lambda: (park() if not b.parked else None)), (300, lambda: click_wedge("Compress")),
              (500, lambda: key(0xff1b)),
              (500, lambda label=label: check(f"{label}: real Esc goes back, wheel stays",
                                              b.subRing == "" and b.is_shown))]
steps += [(0, w.hide_wheel), (300, lambda: call(sess, "Stop")),
          (300, lambda: (print("FAILED:" if fails else "ALL PASSED", fails), app.quit()))]


def run(i=0):
    if i < len(steps):
        d, f = steps[i]

        def step():
            try:
                f()
            except Exception as exc:
                print("ABORT:", exc, flush=True)
                try:
                    button(False); call(sess, "Stop")
                except Exception:
                    pass
                app.quit(); return
            run(i + 1)
        QTimer.singleShot(d, step)


run(); app.exec(); w.shutdown()
