"""The wheel window: a frameless, transparent QQuickView.

The QML scene is loaded once at startup and the window is only hidden
between uses, so showing it never pays for QML compilation. While hidden
the window is unmapped: no rendering, no animation ticks.

In overlay mode (Wayland) the transparent window covers the screen and
takes all input while shown as a popup, so a click anywhere outside the
wheel lands on us and closes it instead of reaching the app underneath.
When pinned or opened as a drop zone, the input region shrinks to the
wheel circle so clicks outside pass through to the desktop and other apps;
it follows the wheel when a pinned wheel is dragged to a new spot (QML
moves the drawn wheel). The region is recomputed on every state change
and applied only when it differs. GNOME ignores a new input region on a
window that is already on screen until the window's size changes, so each
change is followed by a one-pixel size nudge (platform_utils).

Which mode the shortcut opens: a popup when a drag is under way (the
mouse button is down), a drop zone otherwise. Wayland doesn't tell apps
whether a button is down, so there the wheel opens as a popup and turns
into a drop zone if no drag reaches it within PROBE_MS.

In small-window mode (Windows, X11) dragging a pinned wheel moves the real
window, and on release it eases to the nearest screen edge.
"""

from __future__ import annotations

import math

from PyQt6.QtCore import QEasingCurve, QObject, QPoint, QRect, Qt, QTimer, QUrl, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QColor, QGuiApplication, QRegion
from PyQt6.QtQuick import QQuickView, QQuickWindow, QSGRendererInterface

from . import QML_DIR, platform_utils
from .bridge import Bridge
from .config import Config, cache_dir

try:  # Qt >= 6.5
    from PyQt6.QtQuick import QQuickGraphicsConfiguration
except ImportError:  # pragma: no cover
    QQuickGraphicsConfiguration = None

_SNAP_MARGIN = 8  # px between the snapped window and the screen edge
_SNAP_MS = 280
PROBE_MS = 400   # Wayland: no drag by then -> drop zone

_APIS = {
    "software": QSGRendererInterface.GraphicsApi.Software,
    "opengl": QSGRendererInterface.GraphicsApi.OpenGL,
    "d3d11": QSGRendererInterface.GraphicsApi.Direct3D11,
    "vulkan": QSGRendererInterface.GraphicsApi.Vulkan,
}


def resolve_renderer(configured: str) -> str:
    """Turn "auto" into "software" when there is no usable GPU."""
    if configured == "auto" and not platform_utils.has_gpu():
        return "software"
    return configured


def configure_graphics(renderer: str) -> None:
    """Must run before any QQuickWindow exists."""
    QQuickWindow.setDefaultAlphaBuffer(True)
    api = _APIS.get(renderer)
    if api is not None:
        QQuickWindow.setGraphicsApi(api)


class WheelWindow(QObject):
    graphicsFailed = pyqtSignal(str)

    def __init__(self, bridge: Bridge, cfg: Config, renderer: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._bridge = bridge
        self._cfg = cfg
        self._strategy = platform_utils.window_strategy()
        bridge.set_overlay(self._strategy == "overlay")

        # Small-window mode: eased glide of the real window (snap / restore).
        self._move_start: QPoint | None = None
        self._glide = QVariantAnimation(self)
        self._glide.setDuration(_SNAP_MS)
        self._glide.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._glide.valueChanged.connect(lambda p: self._view.setPosition(p))

        # Input region (overlay mode): what was last applied, and the
        # one-pixel nudge that makes GNOME take a change into account.
        self._region: QRegion | None = None
        self._nudging = False
        self._region_dirty = False
        # Wayland: one-shot after opening, decides popup vs drop zone.
        self._probe = QTimer(self)
        self._probe.setSingleShot(True)
        self._probe.setInterval(PROBE_MS)
        self._probe.timeout.connect(self._end_probe)

        view = QQuickView()
        from . import offline

        offline.protect(view.engine())
        self._view = view
        view.setTitle("Spindle")
        view.setColor(QColor(0, 0, 0, 0))
        view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)

        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        if self._strategy == "at_cursor":
            # Tool: no taskbar button on Windows / X11.
            flags |= Qt.WindowType.Tool
        view.setFlags(flags)

        if cfg.low_memory_mode:
            view.setPersistentGraphics(False)
            view.setPersistentSceneGraph(False)

        if QQuickGraphicsConfiguration is not None and renderer != "software":
            # Cache compiled GPU pipelines across runs so the first open
            # after a restart doesn't stall on shader compilation.
            cache = cache_dir()
            cache.mkdir(parents=True, exist_ok=True)
            pipeline = cache / "pipeline.cache"
            gc = QQuickGraphicsConfiguration()
            if pipeline.is_file():
                gc.setPipelineCacheLoadFile(str(pipeline))
            gc.setPipelineCacheSaveFile(str(pipeline))
            view.setGraphicsConfiguration(gc)

        view.sceneGraphError.connect(self._on_scene_graph_error)
        view.activeChanged.connect(lambda: bridge.window_active_changed(view.isActive()))
        if self._strategy == "overlay":
            view.widthChanged.connect(self._update_input_region)
            view.heightChanged.connect(self._update_input_region)

        view.rootContext().setContextProperty("bridge", bridge)
        view.setSource(QUrl.fromLocalFile(str(QML_DIR / "Main.qml")))
        if view.status() == QQuickView.Status.Error:
            for err in view.errors():
                print(f"[qml] {err.toString()}")
            raise RuntimeError("failed to load qml/Main.qml")

        side = self._window_side()
        view.resize(side, side)
        bridge.hidden.connect(self._on_hidden)
        bridge.parkedChanged.connect(self._on_parked_changed)
        bridge.pinnedChanged.connect(self._on_pinned_changed)
        bridge.wheelCenterChanged.connect(self._update_input_region)
        bridge.stateChanged.connect(self._update_input_region)
        bridge.moveRequested.connect(self._on_move_requested)

    @property
    def view(self) -> QQuickView:
        return self._view

    # ------------------------------------------------------------------ API

    def show_wheel(self) -> None:
        view = self._view
        if self._bridge.is_hidden:
            drag = platform_utils.drag_in_progress()  # None: can't tell (Wayland)
            self._bridge.open(drop_zone=drag is False)
            self._probe.stop()
            if drag is None:
                self._probe.start()
            # Before mapping: a region set while hidden needs no nudge.
            self._update_input_region()
            if self._strategy == "overlay":
                view.showMaximized()
            else:
                self._place_at_cursor()
                view.show()
        else:
            self._bridge.open()
        view.raise_()
        view.requestActivate()

    def hide_wheel(self) -> None:
        self._bridge.dismiss()

    def toggle(self) -> None:
        if self._bridge.is_shown:
            self.hide_wheel()
        else:
            self.show_wheel()

    def shutdown(self) -> None:
        """Destroy the QML scene while the bridge still exists, so no
        binding sees a null `bridge` during teardown."""
        self._view.hide()
        self._view.setSource(QUrl())

    # -------------------------------------------------------------- helpers

    def _window_side(self) -> int:
        # The wheel's outer radius is 86% of half this, which leaves room
        # for the shadow, the 1.04 hover scale and the OutBack overshoot.
        return int(self._cfg.wheel_size)

    def _place_at_cursor(self) -> None:
        side = self._window_side()
        pos = platform_utils.cursor_position()
        screen = QGuiApplication.screenAt(pos) if pos is not None else None
        screen = screen or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        if pos is None:
            pos = area.center()
        x = min(max(pos.x() - side // 2, area.left()), area.right() - side + 1)
        y = min(max(pos.y() - side // 2, area.top()), area.bottom() - side + 1)
        self._view.setPosition(QPoint(x, y))

    def _update_input_region(self) -> None:
        """Overlay mode: pinned or drop zone -> only the wheel circle takes
        input (clicks elsewhere pass through); popup -> the whole window
        does. Called on every state change; cheap when nothing changed."""
        if self._strategy != "overlay":
            return
        if self._nudging:
            self._region_dirty = True  # the size is mid-nudge: redo after
            return
        region = self._wanted_region()
        if region == self._region:
            return
        self._region = region
        view = self._view
        view.setMask(region)
        if view.isVisible() and platform_utils.input_region_needs_nudge():
            self._nudging = True
            self._region_dirty = False
            platform_utils.nudge_window_size(view, self._nudge_done)

    def _wanted_region(self) -> QRegion:
        if not self._bridge.wheel_only:
            return QRegion()
        view = self._view
        side = self._window_side()
        cx, cy = self._bridge.wheel_center or (view.width() / 2, view.height() / 2)
        # Round half up like QML's Math.round, which placed the wheel
        # (Python's round() would put the region 1 px off on .5).
        rect = QRect(math.floor(cx - side / 2 + 0.5), math.floor(cy - side / 2 + 0.5), side, side)
        return QRegion(rect, QRegion.RegionType.Ellipse)

    def _nudge_done(self) -> None:
        self._nudging = False
        if self._region_dirty:
            self._region_dirty = False
            self._update_input_region()

    def _end_probe(self) -> None:
        """Wayland: no drag reached the wheel since it opened, so this was
        the shortcut pressed with nothing in hand: become a drop zone."""
        b = self._bridge
        if b.is_shown and not b.drag_seen and not b.is_parked:
            b.set_drop_zone(True)

    # ---- small-window mode: moving the real window ----

    def _on_pinned_changed(self, pinned: bool) -> None:
        if self._strategy == "overlay":
            self._update_input_region()  # QML glides the wheel and reports back
            return
        nx, ny = self._cfg.pinned_x, self._cfg.pinned_y
        if pinned and nx >= 0 and ny >= 0:
            area = self._area()
            side = self._window_side()
            target = QPoint(round(area.left() + nx * area.width() - side / 2),
                            round(area.top() + ny * area.height() - side / 2))
            self._glide_to(self._clamp(target))

    def _on_move_requested(self, phase: str, dx: float, dy: float) -> None:
        if self._strategy == "overlay":
            return
        if phase == "start":
            self._glide.stop()
            self._move_start = self._view.position()
        elif phase == "move" and self._move_start is not None:
            self._view.setPosition(self._move_start + QPoint(round(dx), round(dy)))
        elif phase == "end" and self._move_start is not None:
            self._move_start = None
            target = self._snap(self._view.position())
            self._glide_to(target)
            area, half = self._area(), self._window_side() / 2
            self._bridge.remember_pinned_spot((target.x() + half - area.left()) / area.width(),
                                              (target.y() + half - area.top()) / area.height())

    def _glide_to(self, target: QPoint) -> None:
        self._glide.stop()
        self._glide.setStartValue(self._view.position())
        self._glide.setEndValue(target)
        self._glide.start()

    def _area(self) -> QRect:
        screen = self._view.screen() or QGuiApplication.primaryScreen()
        return screen.availableGeometry()

    def _clamp(self, pos: QPoint) -> QPoint:
        area, side, m = self._area(), self._window_side(), _SNAP_MARGIN
        x = min(max(pos.x(), area.left() + m), area.right() + 1 - side - m)
        y = min(max(pos.y(), area.top() + m), area.bottom() + 1 - side - m)
        return QPoint(x, y)

    def _snap(self, pos: QPoint) -> QPoint:
        """Clamp onto the screen, then push to the nearest edge."""
        area, side, m = self._area(), self._window_side(), _SNAP_MARGIN
        p = self._clamp(pos)
        left, right = area.left() + m, area.right() + 1 - side - m
        top, bottom = area.top() + m, area.bottom() + 1 - side - m
        gaps = {"l": p.x() - left, "r": right - p.x(), "t": p.y() - top, "b": bottom - p.y()}
        edge = min(gaps, key=gaps.get)
        if edge == "l":
            p.setX(left)
        elif edge == "r":
            p.setX(right)
        elif edge == "t":
            p.setY(top)
        else:
            p.setY(bottom)
        return p

    def _on_parked_changed(self, parked: bool) -> None:
        # The overlay already takes all input. A small window has to be
        # focused for Esc and click-outside (focus loss) to work after a
        # drop, which leaves focus with the file manager.
        if parked and self._strategy != "overlay":
            # Deferred: on Windows the drop is delivered from inside the file
            # manager's drag loop; activate once that has returned.
            QTimer.singleShot(0, lambda: platform_utils.bring_to_front(self._view))

    def _on_hidden(self) -> None:
        self._probe.stop()
        self._glide.stop()
        self._move_start = None
        self._view.hide()
        if self._cfg.low_memory_mode:
            self._view.releaseResources()
        platform_utils.release_memory()

    def _on_scene_graph_error(self, _error, message: str) -> None:
        print(f"[render] scene graph error: {message}")
        self.graphicsFailed.emit(message)
