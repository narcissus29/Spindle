import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))); os.chdir(sys.path[0])
sys.excepthook = lambda *e: __import__("traceback").print_exception(*e)
from PyQt6.QtCore import QCoreApplication, QTimer, QPoint, Qt, QObject
from PyQt6.QtGui import QGuiApplication, QRasterWindow, QPainter, QColor
from PyQt6.QtDBus import QDBusConnection, QDBusInterface, QDBusMessage
from app import config
from app.window import configure_graphics, resolve_renderer
from app import platform_utils
platform_utils.drag_in_progress = lambda: True  # open as a popup (these suites are about pinning)
QCoreApplication.setApplicationName("spindle-test")
cfg = config.load(); r = resolve_renderer("auto"); configure_graphics(r)
app = QGuiApplication(sys.argv)
from app.bridge import Bridge
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
m = 8
steps = [
 (100, under.showMaximized),
 (1200, start_session),
 (300, lambda: (home(), move_global(400, 400))), (400, calib),
 (0, lambda: move_local(QPoint(700, 300))), (400, verify),
 (0, w.show_wheel),
 (800, guard),
 # a) real click on the pin button
 (0, lambda: (log.__setitem__("c0", wc()), move_local(on_wheel(45, R)))), (300, press),
 (500, lambda: check("real click on the pin button pins", b.pinned)),
 # b) real drag by the rim, to the right
 (0, lambda: move_local(on_wheel(225, R + 4))), (300, lambda: button(True)),
 (100, lambda: [move_global(pos[0] + 25, pos[1] - 2) for _ in range(24)]),
 (150, lambda: check("wheel followed the real pointer drag", wc().x() > log["c0"].x() + 300, f"center {wc().x()},{wc().y()}")),
 (0, lambda: button(False)),
 (600, lambda: check("released: snapped to the right edge", abs(wc().x() - (v.width() - c - m)) <= 1, f"center x {wc().x()}, expected {v.width() - c - m:.0f}")),
 (0, lambda: check("input region followed", v.mask().boundingRect().getRect() == (wc().x() - round(c), wc().y() - round(c), side, side), str(v.mask().boundingRect().getRect()))),
 (0, lambda: check("the drag's clicks never reached the window underneath", under.presses == [])),
 # c) real click on × at the new spot
 (0, lambda: move_local(on_wheel(59, R))), (300, press),
 (600, lambda: check("real click on × at the new spot closes it", b.is_hidden and under.presses == [])),
 # d) reopen: centered + unpinned; real click pin -> glides to the saved spot
 (0, w.show_wheel),
 (700, lambda: check("reopens centered", abs(wc().x() - v.width() / 2) <= 1 and not b.pinned, f"center {wc().x()}")),
 (0, lambda: move_local(on_wheel(45, R))), (300, press),
 (700, lambda: check("pinning again glides to the saved spot", abs(wc().x() - (v.width() - c - m)) <= 1, f"center x {wc().x()}")),
 # e) real click where the wheel used to be (screen center): passes through now
 (0, lambda: move_local(QPoint(v.width() // 2, v.height() // 2))), (300, press),
 (600, lambda: check("real click at the old (center) spot passes through to the window underneath", under.presses[-1:] == [QPoint(v.width() // 2, v.height() // 2)] and b.is_shown,
                     f"underlay presses {[(p.x(), p.y()) for p in under.presses]}")),
 (0, lambda: (call(sess, "Stop"), w.hide_wheel())),
 (400, lambda: (print("FAILED:" if fails else "ALL PASSED", fails), app.quit())),
]
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
