"""Icons for QML: SVG path data from assets/icons/<name>.svg.

QML draws them with PathSvg, so they stay crisp at any scale and can take
any color. The files are 24x24 stroke icons made of <path> elements only.
"""

from __future__ import annotations

import re
from functools import lru_cache

from . import BRAND_DIR, ICON_DIR, ICON_SIZES

_PATH_D = re.compile(r'<path\b[^>]*?\sd="([^"]+)"', re.S)


@lru_cache(maxsize=None)
def icon_path(name: str) -> str:
    """All <path d> of an icon joined, or "" if there is no such icon."""
    if not name:
        return ""
    try:
        text = (ICON_DIR / f"{name}.svg").read_text(encoding="utf-8")
    except OSError as exc:
        print(f"[icons] {exc}")
        return ""
    return " ".join(_PATH_D.findall(text))


def app_icon():
    """Spindle's own icon (window, tray): pixel art, one exact image per
    size so Qt never blurs it by scaling."""
    from PyQt6.QtCore import QSize
    from PyQt6.QtGui import QIcon

    icon = QIcon()
    for size in ICON_SIZES:
        icon.addFile(str(BRAND_DIR / f"icon-{size}.png"), QSize(size, size))
    return icon
