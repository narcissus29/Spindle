"""Image provider "doc": everything the editor canvas draws comes from here.

    image://doc/page/<index>/<width>       a page (PDF) or the preview (image)
    image://doc/thumb/<index>              page strip thumbnail
    image://doc/adjusted/<width>/<b>/<c>/<s>
                                           software renderer only: the image
                                           preview with color adjustments
    image://doc/checker                    tile shown behind transparent images
    image://doc/exifthumb                  Info: the thumbnail inside the EXIF

QML loads these with `asynchronous: true` and the provider is flagged
ForceAsynchronousImageLoading, so rendering never runs on the UI thread.
The ids are pure functions of their parts, so Qt's own pixmap cache can
reuse them.
"""

from __future__ import annotations

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QImage
from PyQt6.QtQml import QQmlImageProviderBase
from PyQt6.QtQuick import QQuickImageProvider


class DocImageProvider(QQuickImageProvider):
    def __init__(self, doc) -> None:
        super().__init__(QQmlImageProviderBase.ImageType.Image,
                         QQmlImageProviderBase.Flag.ForceAsynchronousImageLoading)
        self._doc = doc

    def requestImage(self, id: str, requestedSize: QSize):  # noqa: N802 (Qt API)
        try:
            image = self._image(id.split("/"))
        except Exception as exc:  # a bad id or a render failure: draw nothing
            print(f"[editor] can't render {id}: {exc}", flush=True)
            image = QImage(1, 1, QImage.Format.Format_ARGB32)
            image.fill(0)
        return image, image.size()

    def _image(self, parts: list[str]) -> QImage:
        what = parts[0]
        if what == "page":
            return self._doc.render_page(int(parts[1]), int(parts[2]))
        if what == "thumb":
            return self._doc.thumbnail(int(parts[1]))
        if what == "checker":
            return _checker()
        if what == "exifthumb":
            data = self._doc.metadata().thumbnail() if hasattr(self._doc, "metadata") else None
            image = QImage.fromData(data or b"")
            if image.isNull():
                raise ValueError("no thumbnail")
            return image
        if what == "adjusted":
            width, b, c, s = int(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
            return self._doc.adjusted_preview(width, {"brightness": b, "contrast": c, "saturation": s})
        raise ValueError(f"unknown image {what!r}")


def _checker() -> QImage:
    from PyQt6.QtGui import QColor

    tile = QImage(16, 16, QImage.Format.Format_RGB32)
    tile.fill(QColor("#ffffff"))
    for y in range(16):
        for x in range(16):
            if (x // 8 + y // 8) % 2:
                tile.setPixelColor(x, y, QColor("#e6ebf2"))
    return tile
