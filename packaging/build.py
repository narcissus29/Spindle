"""Build Spindle for the platform this runs on.

    python packaging/build.py            -> dist/Spindle-x86_64.AppImage (Linux)
                                            dist/Spindle-Setup.exe       (Windows)
    python packaging/build.py --folder   only the PyInstaller folder (build/dist/...)

Steps: app icons from assets/brand (pixel art), PyInstaller (one folder, see
spindle.spec), then the AppImage (appimagetool with the static runtime: no
libfuse2 needed) or the Inno Setup installer (per-user, no admin rights).
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
DIST = ROOT / "dist"
ICONS = BUILD / "icons"
WINDOWS = sys.platform == "win32"
APPIMAGETOOL_URL = "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"

sys.path.insert(0, str(ROOT))
from app import APP_NAME, __version__  # noqa: E402


def run(*cmd, **kw) -> None:
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def icons() -> None:
    """The app icon from the pixel-art PNGs in assets/brand (one exact image
    per size, never resampled), the Windows .ico with each of them, and the
    installer's pictures."""
    from app import BRAND_DIR, ICON_SIZES

    ICONS.mkdir(parents=True, exist_ok=True)
    for size in ICON_SIZES:
        shutil.copy(BRAND_DIR / f"icon-{size}.png", ICONS / f"spindle-{size}.png")
    if WINDOWS:
        from PIL import Image

        frames = [Image.open(ICONS / f"spindle-{s}.png").convert("RGBA") for s in (256, 128, 64, 48, 32, 24, 16)]
        # every size as drawn: Pillow would otherwise shrink the 256 px one (blur)
        frames[0].save(ICONS / "spindle.ico", sizes=[f.size for f in frames], append_images=frames[1:])
    sys.path.insert(0, str(BRAND_DIR))
    import make_brand

    make_brand.installer_images(ICONS)


def version_info() -> None:
    """File details Windows shows for Spindle.exe."""
    parts = (__version__.split(".") + ["0", "0", "0"])[:4]
    tup = ", ".join(str(int(p)) for p in parts)
    (BUILD / "version_info.txt").write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({tup}), prodvers=({tup})),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', '{APP_NAME}'),
    StringStruct('FileDescription', '{APP_NAME}'),
    StringStruct('FileVersion', '{__version__}'),
    StringStruct('ProductName', '{APP_NAME}'),
    StringStruct('ProductVersion', '{__version__}'),
    StringStruct('LegalCopyright', 'AGPL-3.0')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])])
""", encoding="utf-8")


def pyinstaller() -> Path:
    BUILD.mkdir(exist_ok=True)
    if WINDOWS:
        version_info()
    out = BUILD / "dist"
    shutil.rmtree(out, ignore_errors=True)
    run(sys.executable, "-m", "PyInstaller", ROOT / "packaging" / "spindle.spec", "--noconfirm",
        "--distpath", out, "--workpath", BUILD / "work", cwd=ROOT)
    return out / ("Spindle" if WINDOWS else "spindle")


def folder_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file() and not f.is_symlink())


def appimage(folder: Path) -> Path:
    appdir = BUILD / "AppDir"
    shutil.rmtree(appdir, ignore_errors=True)
    shutil.copytree(folder, appdir / "usr" / "lib" / "spindle", symlinks=True)
    (appdir / "AppRun").write_text(
        '#!/bin/sh\n'
        '# Spindle: start the app inside this AppImage.\n'
        'HERE="$(dirname "$(readlink -f "$0")")"\n'
        'exec "$HERE/usr/lib/spindle/spindle" "$@"\n')
    (appdir / "AppRun").chmod(0o755)
    shutil.copy(ROOT / "packaging" / "linux" / "spindle.desktop", appdir / "spindle.desktop")
    shutil.copy(ICONS / "spindle-256.png", appdir / "spindle.png")
    shutil.copy(ICONS / "spindle-256.png", appdir / ".DirIcon")
    tool = Path.home() / ".cache" / "spindle-build" / "appimagetool-x86_64.AppImage"
    if not tool.exists():
        tool.parent.mkdir(parents=True, exist_ok=True)
        print(f"downloading {APPIMAGETOOL_URL}")
        urllib.request.urlretrieve(APPIMAGETOOL_URL, tool)
        tool.chmod(tool.stat().st_mode | stat.S_IEXEC)
    DIST.mkdir(exist_ok=True)
    out = DIST / "Spindle-x86_64.AppImage"
    env = {**os.environ, "ARCH": "x86_64", "APPIMAGE_EXTRACT_AND_RUN": "1", "VERSION": __version__}
    # zstd: fast to unpack (every start of the wheel, helper and editor reads
    # from the image). appimagetool's mksquashfs offers no xz anyway.
    run(tool, "--comp", "zstd", "--mksquashfs-opt", "-Xcompression-level", "--mksquashfs-opt", "19",
        "--no-appstream", appdir, out, env=env)
    return out


def installer(folder: Path) -> Path:
    iscc = shutil.which("ISCC") or r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    DIST.mkdir(exist_ok=True)
    run(iscc, f"/DAppVersion={__version__}", f"/DSourceDir={folder}", f"/DIconFile={ICONS / 'spindle.ico'}", f"/DPictures={ICONS}",
        f"/DOutputDir={DIST}", ROOT / "packaging" / "windows" / "spindle.iss")
    return DIST / "Spindle-Setup.exe"


def main() -> int:
    icons()
    folder = pyinstaller()
    print(f"folder: {folder} ({folder_size(folder) / 1e6:.0f} MB)")
    if "--folder" in sys.argv:
        return 0
    out = installer(folder) if WINDOWS else appimage(folder)
    print(f"built: {out} ({out.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
