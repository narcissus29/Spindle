"""Spindle: drag a file onto a radial wheel to convert or edit it."""

from pathlib import Path

APP_NAME = "Spindle"
APP_ID = "spindle"            # also the .desktop file and icon name on Linux
__version__ = "0.1.0"
import os as _os

# Tests and --selftest: SPINDLE_INSTANCE keeps a separate copy apart from a
# running one: its own socket, D-Bus name, config and log folder.
INSTANCE = _os.environ.get("SPINDLE_INSTANCE", "")


def app_name() -> str:
    """The Qt application name: "spindle", or "spindle-<instance>". It
    picks the config, cache and log folders."""
    return APP_ID + (f"-{_os.environ['SPINDLE_INSTANCE']}" if _os.environ.get("SPINDLE_INSTANCE") else "")


# Linux: the shortcut calls Toggle here.
DBUS_INTERFACE = "io.github.narcissus29.Spindle"
DBUS_NAME = DBUS_INTERFACE + (f".Test{INSTANCE}" if INSTANCE else "")
DBUS_PATH = "/io/github/narcissus29/Spindle"

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent
QML_DIR = PROJECT_DIR / "qml"
ICON_DIR = PROJECT_DIR / "assets" / "icons"
BRAND_DIR = PROJECT_DIR / "assets" / "brand"  # the logo and app icons (pixel art)
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256, 512)
