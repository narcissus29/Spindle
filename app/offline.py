"""Spindle never goes online, and its UI can't be made to.

Qt Quick can load from the network: rich text with <img src="https://...">,
an Image with a web address. A file name or a metadata field is text from
someone else, so every QML engine (wheel, editor, settings) gets a network
access manager that only lets local files and Qt resources through.
Anything else fails at once, without a connection, and is logged.

(Texts are also set to plain text in QML: this is the second line.)
"""

from __future__ import annotations

from PyQt6.QtCore import QUrl
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PyQt6.QtQml import QQmlEngine, QQmlNetworkAccessManagerFactory

_ALLOWED = ("file", "qrc", "data")
_factories: list = []  # an engine doesn't own its factory: keep them alive


class _LocalOnly(QNetworkAccessManager):
    def createRequest(self, op, request, outgoing=None):  # noqa: N802 (Qt override)
        scheme = request.url().scheme().lower()
        if scheme not in _ALLOWED:
            print(f"[offline] blocked a {scheme or 'relative'} request from the UI", flush=True)
            request = QNetworkRequest(QUrl("blocked:"))  # unknown scheme: an error reply, no connection
        return super().createRequest(op, request, outgoing)


_managers: set = set()  # their Python side must live as long as Qt uses them


class _Factory(QQmlNetworkAccessManagerFactory):
    def create(self, parent):  # noqa: D401 (Qt override; may run on a loader thread)
        manager = _LocalOnly(parent)
        _managers.add(manager)
        manager.destroyed.connect(lambda *_: _managers.discard(manager))
        return manager


def protect(engine: QQmlEngine) -> None:
    """Call before loading any QML into `engine`."""
    factory = _Factory()
    _factories.append(factory)
    engine.setNetworkAccessManagerFactory(factory)
