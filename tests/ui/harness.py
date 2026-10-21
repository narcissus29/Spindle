"""Shared setup for the UI suites: the real wheel + the real helper process.

Run a suite from the project root, e.g.
    .venv/bin/python tests/ui/suite_wheel.py
(QT_QPA_PLATFORM=offscreen runs it without a display.) Output files go to a
fresh temporary folder, or to $S if set.
"""
import sys, os, time, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
sys.excepthook = lambda *e: __import__("traceback").print_exception(*e)
S = os.environ.get("S")
if not S:
    import atexit, shutil
    S = tempfile.mkdtemp(prefix="spindle-ui-")
    atexit.register(shutil.rmtree, S, True)
os.environ["PYTHONPATH"] = HERE + os.pathsep + os.environ.get("PYTHONPATH", "")   # helper can import uihelpers
LOG = os.path.join(S, "ui_calls.log")
os.environ["SPINDLE_UI_LOG"] = LOG
from PyQt6.QtCore import QCoreApplication, QTimer, QObject, QMetaObject, Q_ARG, QVariant, QPoint, QPointF, Qt
from PyQt6.QtGui import QGuiApplication, QWheelEvent
from PyQt6.QtTest import QTest
from app import config, handlers, platform_utils
from app.window import configure_graphics, resolve_renderer
QCoreApplication.setApplicationName("spindle-test")
OFF = os.environ.get("QT_QPA_PLATFORM") == "offscreen"
cfg = config.Config()
R = "software" if OFF else resolve_renderer("auto")
configure_graphics(R)
app = QGuiApplication(sys.argv)

# Is a drag under way when the wheel opens? The suites test the popup (drag
# under way) unless they say otherwise; None = can't tell (Wayland probe).
DRAG = {"v": True}
platform_utils.drag_in_progress = lambda: DRAG["v"]
def set_drag(v):
    DRAG["v"] = v
from app.bridge import Bridge
from app.window import WheelWindow
from app.jobs.process import ProcessWorker

def use_test_handlers(delays=None, keep_real=()):
    """Route every option to uihelpers:record, except (kind, option) pairs in keep_real."""
    for k, v in (delays or {}).items():
        os.environ["SPINDLE_UI_DELAY_" + k.replace(" ", "_")] = str(v)
    for kind, wheels in handlers.REGISTRY.items():
        for opts in wheels.values():
            for name in opts:
                if (kind, name) not in keep_real:
                    opts[name] = f"uihelpers:record_{kind}"
    open(LOG, "w").close()

def calls():
    return [line.strip().split("|") for line in open(LOG) if line.strip()]

b = Bridge(cfg); w = WheelWindow(b, cfg, R); v = w.view
wk = ProcessWorker({"pdf_image_dpi": 72, "jpeg_quality": 85}, idle_ms=30_000)
notes = []
b.jobRequested.connect(wk.submit); b.cancelRequested.connect(wk.cancel)
wk.fileDone.connect(b.file_done); wk.fileProgress.connect(b.file_progress)
wk.thumbnailReady.connect(b.thumbnail_ready)
b.thumbnailRequested.connect(lambda p: wk.request_thumbnail(__import__("pathlib").Path(p), 128, __import__("pathlib").Path(S) / "thumbs"))
b.notify.connect(lambda t, body: notes.append((t, body)))
wheel = v.rootObject().findChild(QObject, "wheel")
c = cfg.wheel_size / 2
fails = []
def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""), flush=True)
    if not cond: fails.append(name)
def org(): return QPoint((v.width() - cfg.wheel_size) // 2, (v.height() - cfg.wheel_size) // 2)
def at(x, y): return org() + QPoint(int(x), int(y))
def click(p): QTest.mouseClick(v, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p, 600)
def click_out(): click(QPoint(3, 3))
def track(x, y): QMetaObject.invokeMethod(wheel, "track", Q_ARG(QVariant, x), Q_ARG(QVariant, y))
def drag(urls, x=None, y=None):
    ok = b.dragEnter(urls)
    if ok:
        wheel.setProperty("dragging", True); track(c if x is None else x, c if y is None else y)
    return ok
def drop():
    QMetaObject.invokeMethod(wheel, "settle")
    on_center = wheel.property("overCenter"); idx = wheel.property("hoveredIndex")
    QMetaObject.invokeMethod(wheel, "endDrag")
    return b.park() if on_center else b.drop(idx)
def scroll():
    pos = QPointF(at(c + 100, c))
    QGuiApplication.sendEvent(v, QWheelEvent(pos, QPointF(v.mapToGlobal(pos.toPoint())), QPoint(), QPoint(0, 120), Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False))
def names(): return [o["name"] for o in b.options]
def wedge(name, urls=None):
    """Wheel coordinates of the middle of the wedge called `name` (the
    wedges for `urls`, if given, are looked up by entering that drag)."""
    import math
    if urls is not None:
        b.dragEnter(urls)
    i = names().index(name)
    step = 360 / len(names())
    r = (wheel.property("innerR") + wheel.property("outerR")) / 2
    a = math.radians(i * step)
    return c + r * math.sin(a), c - r * math.cos(a)
hidden = lambda: b.is_hidden and not v.isVisible()
seen = {}

def until(cond, label, timeout=15.0):
    """A step that polls `cond` (fails the check `label` on timeout)."""
    return ("until", cond, label, timeout)

def run(steps):
    def go(i=0):
        if i >= len(steps):
            print("FAILED:" if fails else "ALL PASSED", fails, flush=True)
            app.quit(); return
        step = steps[i]
        if step[0] == "until":
            _, cond, label, timeout = step
            deadline = time.monotonic() + timeout
            def poll():
                try: ok = cond()
                except Exception as exc: ok = False; print("  (poll error)", exc)
                if ok: check(label, True); go(i + 1)
                elif time.monotonic() > deadline: check(label, False, "timed out"); go(i + 1)
                else: QTimer.singleShot(40, poll)
            QTimer.singleShot(0, poll)
        else:
            d, f = step
            QTimer.singleShot(d, lambda: (f(), go(i + 1)))
    go(); app.exec(); wk.shutdown(); w.shutdown()

if os.environ.get("DEBUG_FOCUS"):
    _t0 = time.monotonic()
    _log = lambda m: print(f"   [{time.monotonic()-_t0:6.2f}] {m}", flush=True)
    v.activeChanged.connect(lambda: _log(f"active={v.isActive()} visible={v.isVisible()} state={b._shown}"))
    b.closeRequested.connect(lambda: _log(f"closeRequested busy={b.busy} status={b.statusText!r}"))
    b.jobRequested.connect(lambda j: _log(f"job {j.option} x{len(j.items)}"))
