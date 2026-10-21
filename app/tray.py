"""Tray / top-bar icon: Open, Pin, Settings, Open log folder, Quit.
Clicking it opens the wheel. On Windows it also shows the notifications
(finished conversions).

Uses QSystemTrayIcon, which needs QApplication (Qt Widgets). On GNOME the
icon shows only with the AppIndicator extension (on by default on Ubuntu);
without it Spindle is reachable from the app grid.
"""

from __future__ import annotations

from typing import Callable

from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon


class Tray:
    def __init__(self, icon: QIcon, on_open: Callable[[], None], on_pin: Callable[[], None],
                 on_settings: Callable[[], None], on_logs: Callable[[], None],
                 on_quit: Callable[[], None]) -> None:
        self._icon = QSystemTrayIcon(icon)
        self._icon.setToolTip("Spindle")
        menu = QMenu()
        for label, slot in (("Open the wheel", on_open), ("Open and pin the wheel", on_pin),
                            ("Settings…", on_settings), ("Open log folder", on_logs), (None, None),
                            ("Quit Spindle", on_quit)):
            if label is None:
                menu.addSeparator()
                continue
            action = QAction(label, menu)
            action.triggered.connect(slot)
            menu.addAction(action)
        self._menu = menu  # kept alive with the icon
        self._icon.setContextMenu(menu)
        self._icon.activated.connect(
            lambda reason: on_open() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)

    @staticmethod
    def available() -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    def set_visible(self, on: bool) -> None:
        self._icon.setVisible(on)

    def notify(self, title: str, body: str) -> None:
        self._icon.showMessage(title, body, QSystemTrayIcon.MessageIcon.Information, 6000)
