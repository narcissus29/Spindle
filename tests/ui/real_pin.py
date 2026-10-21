import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))); os.chdir(sys.path[0])
sys.excepthook = lambda *e: __import__("traceback").print_exception(*e)
from PyQt6.QtCore import QCoreApplication, QTimer, QPoint, Qt, QObject
from PyQt6.QtGui import QGuiApplication, QRasterWindow, QPainter, QColor
from PyQt6.QtDBus import QDBusConnection, QDBusInterface, QDBusMessage
from app import config
from app.window import configure_graphics, resolve_renderer
QCoreApplication.setApplicationName("spindle-test")
cfg = config.Config(); r = resolve_renderer("auto"); configure_graphics(r)
app = QGuiApplication(sys.argv)
from app.bridge import Bridge
from app import platform_utils
DRAG = {"v": True}
platform_utils.drag_in_progress = lambda: DRAG["v"]   # True: open as popup (a drag is under way)
from app.window import WheelWindow

class Underlay(QRasterWindow):
    def __init__(self):
        super().__init__(); self.presses = []; self.hover = None
    def paintEvent(self, e):
        p = QPainter(self); p.fillRect(0, 0, self.width(), self.height(), QColor("#d8dde6")); p.end()
    def mousePressEvent(self, e): self.presses.append(e.position().toPoint())
    def mouseMoveEvent(self, e): self.hover = e.position().toPoint()
under = Underlay(); under.setFlags(Qt.WindowType.FramelessWindowHint)
b = Bridge(cfg); w = WheelWindow(b, cfg, r); v = w.view
wheel = v.rootObject().findChild(QObject, "wheel")
bus = QDBusConnection.sessionBus()
def call(iface, method, *args):
    reply = iface.call(method, *args)
    if reply.type() == QDBusMessage.MessageType.ErrorMessage: raise RuntimeError(f"{method}: {reply.errorMessage()}")
    return reply.arguments()
rd = QDBusInterface("org.gnome.Mutter.RemoteDesktop", "/org/gnome/Mutter/RemoteDesktop", "org.gnome.Mutter.RemoteDesktop", bus)
sess = None
def start_session():
    global sess
    sess = QDBusInterface("org.gnome.Mutter.RemoteDesktop", call(rd, "CreateSession")[0], "org.gnome.Mutter.RemoteDesktop.Session", bus)
    call(sess, "Start")
pos = [0.0, 0.0]; off = [0, 0]
def home(): call(sess, "NotifyPointerMotionRelative", -10000.0, -10000.0); pos[:] = [0, 0]
def move_global(x, y):
    dx, dy = x - pos[0], y - pos[1]; n = max(1, int(max(abs(dx), abs(dy)) // 20))
    for _ in range(n): call(sess, "NotifyPointerMotionRelative", dx / n, dy / n)
    pos[:] = [x, y]
def move_local(p): move_global(p.x() + off[0], p.y() + off[1])
def button(state): call(sess, "NotifyPointerButton", 272, state)
def press(): button(True); button(False)
side = cfg.wheel_size; c = side / 2; R = c * 0.86
def wc(): return QPoint(round(wheel.property("x") + c), round(wheel.property("y") + c))
def on_wheel(deg, rr): a = math.radians(deg); return wc() + QPoint(round(rr * math.sin(a)), round(rr * math.cos(a) * -1))
fails = []; log = {}
def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""), flush=True)
    if not cond: fails.append(name)
def calib():
    h = under.hover
    if h is None: raise RuntimeError("underlay saw no pointer: abort")
    off[:] = [400 - h.x(), 400 - h.y()]
def verify():
    h = under.hover
    if h is None or abs(h.x() - 700) > 2 or abs(h.y() - 300) > 2: raise RuntimeError(f"pointer not 1:1 ({h}): abort")
def guard():
    if not (under.isVisible() and under.width() == v.width() and under.height() == v.height()):
        raise RuntimeError("underlay doesn't line up with the overlay: abort")

OUT = QPoint(160, 160)
def click_out_check(name):
    st = {}
    def go():
        st["n"] = len(under.presses); move_local(OUT); press()
    def verify():
        n = st["n"]
        check(name, len(under.presses) == n + 1 and under.presses[-1] == OUT and b.is_shown,
              f"underlay presses +{len(under.presses) - n}, shown={b.is_shown}, mask={v.mask().boundingRect().getRect()}")
    return [(0, go), (500, verify)]
def real_pin_click():
    return [(0, lambda: move_local(on_wheel(45, R))), (250, press), (500, lambda: None)]
def spot(x, y):
    def f(): cfg.pinned_x, cfg.pinned_y = x, y
    return f
steps = [
 (100, under.showMaximized),
 (1200, start_session),
 (300, lambda: (home(), move_global(400, 400))), (400, calib),
 (0, lambda: move_local(QPoint(700, 300))), (400, verify),
]
def mode(v):
    def f(): DRAG["v"] = v
    return f
def click_out_closes(name):
    def go(): move_local(OUT); press()
    return [(0, go), (600, lambda: check(name, b.is_hidden))]
def fresh(drag, sx=-1, sy=-1):
    # a new map puts the overlay back on top (GNOME raises a window that was clicked through to)
    return [(0, w.hide_wheel), (500, mode(drag)), (0, spot(sx, sy)), (0, w.show_wheel), (800, guard)]
# ---- bug 1: popup, pin with a real click without moving, click outside
for label, sx, sy in [("no saved spot", -1, -1), ("saved spot = center", 0.5, 0.5), ("saved spot = right edge", 0.9, 0.5)]:
    for rep in range(2):
        steps += fresh(True, sx, sy) + real_pin_click() + [(0, lambda: check("pinned", b.pinned))]
        steps += click_out_check(f"{label} #{rep+1}: pin (real click), click outside passes through")
# pin, unpin (real clicks), then the outside blocks again: a click there closes the popup
steps += fresh(True) + real_pin_click() + real_pin_click() + [(0, lambda: check("unpinned", not b.pinned))]
steps += click_out_closes("pin + unpin: click outside closes the popup again")
# pin right after opening (before the window has its full size)
steps += [(500, mode(True)), (0, spot(-1, -1)), (0, lambda: (w.show_wheel(), b.togglePin())), (900, guard)]
steps += click_out_check("pinned right at open: click outside passes through")
# ---- bug 2: drop zone
steps += fresh(False) + [(0, lambda: check("shortcut, no drag: drop zone", b.dropZone and not b.pinned))]
steps += [(0, lambda: (b.window_active_changed(True), b.window_active_changed(False))), (300, lambda: check("drop zone: focus loss keeps it open", b.is_shown))]
steps += [(0, lambda: move_local(on_wheel(59, R))), (300, press), (600, lambda: check("drop zone: real click on × closes it", b.is_hidden))]
steps += fresh(False) + click_out_check("drop zone: click outside passes through, wheel stays")
steps += [(0, w.hide_wheel), (500, mode(None)), (0, w.show_wheel), (150, lambda: check("Wayland: popup while probing", b.is_shown and not b.dropZone)),
          (700, lambda: check("Wayland: no drag came -> drop zone", b.dropZone))]
steps += click_out_check("Wayland probe -> drop zone: click outside passes through") + [(0, w.hide_wheel), (500, lambda: None)]
steps += [(0, lambda: call(sess, "Stop")), (300, lambda: (print("FAILED:" if fails else "ALL PASSED", fails), app.quit()))]
def run(i=0):
    if i < len(steps):
        d, f = steps[i]
        def step():
            try: f()
            except Exception as exc:
                print("ABORT:", exc, flush=True)
                try: button(False); call(sess, "Stop")
                except Exception: pass
                app.quit(); return
            run(i + 1)
        QTimer.singleShot(d, step)
run(); app.exec(); w.shutdown()
