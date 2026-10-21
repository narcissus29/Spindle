"""Optional RAM / CPU / FPS logger, enabled with --stats or log_stats.

Its timer is the one deliberate exception to "no timers": it wakes every
few seconds so you can watch idle usage. Without the flag none of this exists.

Log line fields:
  rss      resident memory (Linux) / working set (Windows); includes shared
           library pages, so it overstates the real cost
  private  memory only this app uses: PSS on Linux, private bytes on Windows.
           This is the number to compare against the 100 MB target.
  cpu      process CPU use over the last interval (all threads, 100% = one core)
  frames   frames rendered in the interval (0 while hidden = nothing is drawing)
  fps      average rate during animation bursts
  worst    longest gap between two frames inside a burst (16.7 ms = 60 fps)
"""

from __future__ import annotations

import time

from PyQt6.QtCore import QObject, Qt, QTimer
from PyQt6.QtQuick import QQuickWindow

from . import platform_utils

_BURST_GAP_S = 0.25  # frames further apart than this belong to different bursts


def _mb(value: int | None) -> str:
    return f"{value / 1_048_576:.1f}MB" if value is not None else "n/a"


class StatsLogger(QObject):
    def __init__(self, window: QQuickWindow, interval_s: float = 5.0, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._window = window
        self._last_wall = time.monotonic()
        self._last_cpu = time.process_time()
        self._reset_frames()

        window.frameSwapped.connect(self._on_frame, Qt.ConnectionType.QueuedConnection)
        self._timer = QTimer(self)
        self._timer.setInterval(int(interval_s * 1000))
        self._timer.timeout.connect(self._log)
        self._timer.start()
        self._api_reported = False
        print(f"[stats] logging every {interval_s:.0f}s")

    def _reset_frames(self) -> None:
        self._frames = 0
        self._burst_time = 0.0
        self._burst_frames = 0
        self._worst_gap = 0.0
        self._last_frame = 0.0

    def _on_frame(self) -> None:
        if not self._api_reported:
            self._api_reported = True
            api = self._window.rendererInterface().graphicsApi()
            print(f"[stats] scene graph backend: {api.name}", flush=True)
        now = time.perf_counter()
        gap = now - self._last_frame
        if self._last_frame and gap < _BURST_GAP_S:
            self._burst_time += gap
            self._burst_frames += 1
            self._worst_gap = max(self._worst_gap, gap)
        self._last_frame = now
        self._frames += 1

    def _log(self) -> None:
        wall, cpu = time.monotonic(), time.process_time()
        cpu_pct = 100.0 * (cpu - self._last_cpu) / max(wall - self._last_wall, 1e-6)
        self._last_wall, self._last_cpu = wall, cpu

        rss, private = platform_utils.memory_info()
        line = (f"[stats] visible={self._window.isVisible()!s:5} rss={_mb(rss)} private={_mb(private)} "
                f"cpu={cpu_pct:.1f}% frames={self._frames}")
        if self._burst_frames:
            fps = self._burst_frames / self._burst_time
            line += f" fps={fps:.0f} worst={self._worst_gap * 1000:.1f}ms"
        print(line, flush=True)
        self._reset_frames()
