# PyInstaller spec: one folder ("onedir"), so the app starts fast (a
# one-file build would unpack itself on every start). Built by build.py.
#
# Only what Spindle uses is kept: Qt Core / Gui / Widgets (tray menu) /
# Network (single instance) / DBus (Linux) / Svg (icons) / Qml / Quick with
# its Shapes, Effects and Window modules. Everything else Qt ships (3D,
# Multimedia + FFmpeg, WebEngine, Pdf, Controls, Positioning, ...) and all
# Qt translations are left out.

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
WINDOWS = sys.platform == "win32"
NAME = "Spindle" if WINDOWS else "spindle"

hidden = collect_submodules("app") + ["PyQt6.QtSvg", "PyQt6.QtWidgets", "pi_heif", "pdf2docx", "docx",
                                      "fontTools.subset", "numpy", "cv2", "PIL.Image"]
if not WINDOWS:
    hidden.append("PyQt6.QtDBus")
else:
    hidden += ["comtypes", "comtypes.client", "comtypes.client.dynamic"]  # Office -> PDF (late bound)

excludes = ["tkinter", "_tkinter", "pytest", "_pytest", "pillow_heif", "pygments", "setuptools", "pip",
            "IPython", "matplotlib", "pydoc_data",
            "PyQt6.QtWebEngineCore", "PyQt6.QtWebEngineWidgets", "PyQt6.QtWebEngineQuick", "PyQt6.QtWebChannel",
            "PyQt6.QtWebSockets", "PyQt6.Qt3DCore", "PyQt6.Qt3DRender", "PyQt6.Qt3DInput", "PyQt6.Qt3DLogic",
            "PyQt6.Qt3DAnimation", "PyQt6.Qt3DExtras", "PyQt6.QtMultimedia", "PyQt6.QtMultimediaWidgets",
            "PyQt6.QtSpatialAudio", "PyQt6.QtBluetooth", "PyQt6.QtNfc", "PyQt6.QtPositioning",
            "PyQt6.QtSensors", "PyQt6.QtSerialPort", "PyQt6.QtCharts", "PyQt6.QtDataVisualization",
            "PyQt6.QtDesigner", "PyQt6.QtHelp", "PyQt6.QtPdf", "PyQt6.QtPdfWidgets", "PyQt6.QtSql",
            "PyQt6.QtTest", "PyQt6.QtXml", "PyQt6.QtQuick3D", "PyQt6.QtQuickWidgets", "PyQt6.QtRemoteObjects",
            "PyQt6.QtTextToSpeech", "PyQt6.QtPrintSupport", "PyQt6.QtOpenGLWidgets", "PyQt6.QtStateMachine",
            "PyQt6.QtHttpServer", "PyQt6.uic"]

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    hiddenimports=hidden,
    # PyMuPDF's own data files (e.g. its text-layout model settings, which
    # some wheels need at run time), not its C headers.
    datas=[(str(ROOT / "qml"), "qml"), (str(ROOT / "assets"), "assets")]
          + collect_data_files("pymupdf", excludes=["mupdf-devel/**", "**/*.h"]),
    excludes=excludes,
    noarchive=False,
)

# ---- trim Qt ----
DROP_LIBS = ("Qt6Quick3D", "Qt6Multimedia", "Qt6SpatialAudio", "libavcodec", "libavformat", "libavutil", "libswscale", "libswresample", "avcodec", "avformat",
             "avutil", "swscale", "swresample", "Qt6Pdf", "Qt6Designer", "Qt6QuickControls2",
             "Qt6QuickDialogs2", "Qt6QuickTemplates2", "Qt6QuickLayouts", "Qt6LabsPlatform", "Qt6ShaderTools",
             "Qt6Sensors", "Qt6Bluetooth", "Qt6Nfc", "Qt6Positioning", "Qt6Location", "Qt6WebSockets",
             "Qt6WebChannel", "Qt6WebView", "Qt6Charts", "Qt6Graphs", "Qt6DataVisualization", "Qt6Test",
             "Qt6QuickTest", "Qt6Help", "Qt6Sql", "Qt6RemoteObjects", "Qt6Scxml", "Qt6StateMachine",
             "Qt6TextToSpeech", "Qt6SerialPort", "Qt6QuickParticles", "Qt6QuickTimeline", "Qt6Lottie",
             "Qt6VirtualKeyboard", "Qt6QuickVectorImage", "Qt6PrintSupport", "Qt63D", "Qt6Concurrent",
             "Qt6QmlLS", "Qt6LanguageServer", "Qt6QuickControlsTestUtils", "Qt6QmlCompiler", "Qt6Xml",
             "Qt6OpenGLWidgets", "Qt6QuickWidgets", "Qt6HttpServer")
DROP_QML_IN_QTQUICK = ("Controls", "Dialogs", "Layouts", "LocalStorage", "Particles", "Pdf", "Scene2D",
                       "Scene3D", "Templates", "Timeline", "VectorImage", "tooling", "NativeStyle")
DROP_PLUGINS = ("assetimporters", "geometryloaders", "help", "multimedia", "networkinformation", "position",
                "printsupport", "qmllint", "qmlls", "renderers", "renderplugins", "sceneparsers",
                "scxmldatamodel", "sensors", "sqldrivers", "texttospeech", "tls", "webview", "designer",
                "qmltooling", "imageformats/libqpdf", "imageformats/qpdf", "platforminputcontexts",
                "platformthemes/libqgtk3")  # GTK theme: would bundle the whole GTK stack


def _norm(path: str) -> str:
    return path.replace("\\", "/")


def keep(dest: str, src: str = "") -> bool:
    d = _norm(dest)
    name = d.rsplit("/", 1)[-1]
    if "/translations/" in d or d.endswith("/translations"):
        return False
    # Only Qt's own copies: OpenCV and Pillow bring FFmpeg / AVIF libraries
    # of their own, which they need.
    from_qt = "PyQt6" in _norm(src) or "PyQt6" in d
    if from_qt and any(lib in name for lib in DROP_LIBS):
        return False
    if "/Qt6/plugins/" in d or "/plugins/" in d:
        sub = d.split("/plugins/", 1)[1]
        if any(sub.startswith(p) for p in DROP_PLUGINS):
            return False
    if "/Qt6/qml/" in d:
        sub = d.split("/Qt6/qml/", 1)[1]
        if sub.startswith("QtQuick/"):
            rest = sub[len("QtQuick/"):]
            return not any(rest.startswith(x + "/") for x in DROP_QML_IN_QTQUICK)
        return sub.startswith(("QtQml/", "QtQuick/")) or "/" not in sub
    return True


a.binaries = [b for b in a.binaries if keep(b[0], b[1])]
a.datas = [d for d in a.datas if keep(d[0], d[1])]


def _prune_orphans(binaries):
    """Linux: drop bundled system libraries (top level of the folder) that
    nothing left in the build needs any more, e.g. GTK, which only Qt's GTK
    theme plugin (dropped above) used. Repeats until nothing changes."""
    import re
    import subprocess

    needed_by = {}
    for dest, src, _kind in binaries:
        try:
            out = subprocess.run(["readelf", "-d", src], capture_output=True, text=True).stdout
        except OSError:
            return binaries
        needed_by[dest] = set(re.findall(r"\(NEEDED\)\s+Shared library: \[([^\]]+)\]", out))
    while True:
        names = {_norm(d).rsplit("/", 1)[-1] for d, _s, _k in binaries}
        wanted = set()
        for dest, _src, _kind in binaries:
            wanted |= needed_by.get(dest, set())
        orphans = [b for b in binaries if "/" not in _norm(b[0]) and b[0].startswith("lib")
                   and _norm(b[0]) not in wanted and not b[0].startswith("libpython")]
        if not orphans:
            return binaries
        print("pruned (unused):", ", ".join(sorted(o[0] for o in orphans)))
        binaries = [b for b in binaries if b not in orphans]


if not WINDOWS:
    a.binaries = _prune_orphans(a.binaries)

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=NAME,
    console=False,
    icon=str(ROOT / "build" / "icons" / "spindle.ico") if WINDOWS else None,
    strip=False,  # stripping breaks NumPy's OpenBLAS with older binutils (Ubuntu 22.04)
    upx=False,
    version=str(ROOT / "build" / "version_info.txt") if WINDOWS else None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=NAME)
