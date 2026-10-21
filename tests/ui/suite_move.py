import sys, os, math, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))); os.chdir(sys.path[0])
sys.excepthook = lambda *e: __import__("traceback").print_exception(*e)
from PyQt6.QtCore import QCoreApplication, QTimer, QObject, QMetaObject, Q_ARG, QVariant, QPoint, Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtTest import QTest
from app import config
from app.window import configure_graphics, resolve_renderer
from app import platform_utils
platform_utils.drag_in_progress = lambda: True  # open as a popup (these suites are about pinning)
QCoreApplication.setApplicationName("spindle-test")
off = os.environ.get("QT_QPA_PLATFORM") == "offscreen"
cfg = config.load(); r = "software" if off else resolve_renderer("auto"); configure_graphics(r)
app = QGuiApplication(sys.argv)
from app.bridge import Bridge
from app.window import WheelWindow
b = Bridge(cfg); w = WheelWindow(b, cfg, r); v = w.view
root = v.rootObject(); wheel = root.findChild(QObject, "wheel")
overlay = b.overlay
side = cfg.wheel_size; c = side / 2; R = c * 0.86
fails = []
def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""), flush=True)
    if not cond: fails.append(name)
def wc():   # wheel center in window coords
    return (wheel.property("x") + side / 2, wheel.property("y") + side / 2)
def at_wheel(x, y):
    cx, cy = wc(); return QPoint(round(cx - c + x), round(cy - c + y))
def rim_pt(deg, rr=R + 4): a = math.radians(deg); return at_wheel(c + rr * math.sin(a), c - rr * math.cos(a))
def click(p): QTest.mouseClick(v, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p, 600)
drag_state = {}
def drag_start(p):
    drag_state.update(start=p, cur=p, win0=v.position())
    QTest.mousePress(v, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p, 600)
def drag_step(dx, dy):
    # pointer at (start + delta) in global terms; in small-window mode the
    # window itself has moved, so subtract that from the local position
    p = drag_state["start"] + QPoint(dx, dy) - (v.position() - drag_state["win0"])
    drag_state["cur"] = p
    QTest.mouseMove(v, p, 20)
def drag_end(): QTest.mouseRelease(v, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, drag_state["cur"], 20)
def mask(): return None if v.mask().isEmpty() else v.mask().boundingRect().getRect()
def area():
    return v.screen().availableGeometry()
def saved(): return json.load(open(config.config_path()))
m = 8
log = {}
def right_edge_ok():
    if overlay:
        cx, cy = wc(); return abs(cx - (v.width() - c - m)) <= 1, f"center x {cx:.0f}, expected {v.width() - c - m:.0f}"
    a = area(); exp = a.right() + 1 - side - m
    return abs(v.x() - exp) <= 1, f"window x {v.x()}, expected {exp}"
steps = [
 (200, w.show_wheel),
 (500, lambda: (log.__setitem__("c0", wc()), log.__setitem__("pos0", v.position()), click(rim_pt(45, R)))),   # pin button
 (400, lambda: check("pinned", b.pinned)),
 (0, lambda: check("input region = wheel circle at its spot" if overlay else "(small window: no input region needed)",
                   (mask() == (round(wc()[0] - c), round(wc()[1] - c), side, side)) if overlay else True, str(mask()))),
 # drag by the rim towards the right edge
 (0, lambda: drag_start(rim_pt(200))),
 *[(16, (lambda i=i: drag_step(60 * (i + 1), -5 * (i + 1)))) for i in range(10)],
 (100, lambda: check("wheel follows the pointer while dragging", (wc()[0] > log["c0"][0] + 100) if overlay else (v.x() > log["pos0"].x() + 100),
                     f"center {wc()}" if overlay else f"window {v.x()},{v.y()}")),
 (0, drag_end),
 (500, lambda: check("released: snapped to the nearest (right) edge with margin", *right_edge_ok())),
 (0, lambda: check("input region followed the wheel" if overlay else "(small window moved itself)",
                   (mask() == (round(wc()[0] - c), round(wc()[1] - c), side, side)) if overlay else True, str(mask()))),
 (0, lambda: check("position remembered in config", saved()["pinned_x"] > 0.6, f"pinned_x={saved()['pinned_x']:.3f} pinned_y={saved()['pinned_y']:.3f}")),
 (0, lambda: check("drag did not unpin, close or run anything", b.pinned and b.is_shown)),
 # press + release on the rim without moving: nothing happens
 (0, lambda: (log.__setitem__("c1", wc() if overlay else v.position()), click(rim_pt(200)))),
 (400, lambda: check("click on the rim (no drag) does nothing", b.pinned and b.is_shown and (wc() if overlay else v.position()) == log["c1"])),
 # dragging on a wedge (not the rim) doesn't move it
 (0, lambda: drag_start(at_wheel(c - 100, c + 30))),
 *[(16, (lambda i=i: drag_step(-30 * (i + 1), 0))) for i in range(5)],
 (0, drag_end),
 (400, lambda: check("dragging a wedge doesn't move the wheel", (wc() if overlay else v.position()) == log["c1"])),
 # unpin, close, reopen: centered (overlay) / at the cursor (small window)
 (0, lambda: click(rim_pt(45, R))),
 (300, lambda: check("unpinned: wheel stays where it is", not b.pinned and (wc() if overlay else v.position()) == log["c1"])),
 (0, lambda: QTest.keyClick(v, Qt.Key.Key_Escape)),
 (400, w.show_wheel),
 (500, lambda: check("reopens unpinned and centered" if overlay else "reopens unpinned at the cursor/center",
                     not b.pinned and (abs(wc()[0] - v.width() / 2) < 1 and abs(wc()[1] - v.height() / 2) < 1 if overlay else v.position() != log["c1"]),
                     f"center {wc()}" if overlay else f"window {v.x()},{v.y()}")),
 (0, lambda: click(rim_pt(45, R))),
 (500, lambda: check("pinning again glides to the remembered spot", *right_edge_ok())),
 (0, lambda: check("...and the input region is there too" if overlay else "(small window)", (mask() == (round(wc()[0] - c), round(wc()[1] - c), side, side)) if overlay else True, str(mask()))),
 (0, lambda: (QTest.keyClick(v, Qt.Key.Key_Escape))),
 (400, lambda: (print("mode:", "overlay" if overlay else "small window", f"{v.width()}x{v.height()}"), print("FAILED:" if fails else "ALL PASSED", fails), app.quit())),
]
def run(i=0):
    if i < len(steps):
        d, f = steps[i]; QTimer.singleShot(d, lambda: (f(), run(i + 1)))
run(); app.exec(); w.shutdown()
