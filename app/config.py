"""User configuration stored as JSON in the per-user config directory.

Linux:   ~/.config/spindle/config.json
Windows: %LOCALAPPDATA%\\spindle\\config.json

The file is created with defaults on first run so it is easy to find and edit.
Unknown keys are ignored; keys with a wrong type fall back to the default.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from PyQt6.QtCore import QStandardPaths

RENDERERS = ("auto", "software", "opengl", "d3d11", "vulkan")
THEMES = ("blue", "orange")
COMPRESS_PRESETS = ("light", "balanced", "strong")


@dataclass
class Config:
    # Color theme: "blue" (macOS selection blue) or "orange" (warm peach).
    theme: str = "blue"
    # Turn off almost all motion (instant open/close, no stagger, no glide).
    reduce_animations: bool = False
    # Qt Quick backend: auto | software | opengl | d3d11 | vulkan.
    # "auto" lets Qt pick (D3D11 on Windows, OpenGL on Linux). If the GPU
    # backend fails, the app switches this to "software" and restarts once.
    renderer: str = "auto"
    # Wheel diameter in logical pixels (scaled by the OS DPI setting).
    wheel_size: int = 380
    # The shortcut that toggles the wheel. Windows: Spindle registers it
    # (default Win+Alt+S). Linux: Spindle sets it in GNOME (default
    # Ctrl+Alt+Space; other desktops: set it yourself).
    hotkey: str = field(default_factory=lambda: _default_hotkey())
    # The first-run welcome was completed.
    setup_done: bool = False
    # Icon in the system tray / panel (Open, Pin, Settings, Quit).
    tray_icon: bool = True
    # Free the GPU context and scene graph while hidden. Saves RAM, but the
    # first frame after showing is slower, which can clip the open animation.
    low_memory_mode: bool = False
    # What the old Satsuma (this app's earlier name) left behind was removed.
    satsuma_cleaned: bool = False
    # Same as the --stats flag: log RAM / CPU / FPS to the console.
    log_stats: bool = False
    # PDF -> JPG / PNG resolution, and quality for JPG / WEBP output.
    pdf_image_dpi: int = 150
    jpeg_quality: int = 90
    # Compress: "light" (lossless only), "balanced", "strong" (smallest).
    compress_preset: str = "balanced"
    # Compress to a size: the last custom size typed ("75 KB").
    compress_custom: str = ""
    # Add BG: the color put behind transparent areas.
    background_color: str = "#ffffff"
    # Where a pinned wheel goes: its center as a fraction (0..1) of the
    # screen's usable area. Set by dragging a pinned wheel; -1 = not set.
    pinned_x: float = -1.0
    pinned_y: float = -1.0


def _default_hotkey() -> str:
    from .platform_utils import default_hotkey

    return default_hotkey()


def config_dir() -> Path:
    return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation))


def cache_dir() -> Path:
    return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation))


def config_path() -> Path:
    return config_dir() / "config.json"


def load() -> Config:
    path = config_path()
    raw: dict = {}
    readable = True
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("top level must be an object")
        except (OSError, ValueError) as exc:
            print(f"[config] could not read {path}: {exc}; using defaults")
            raw, readable = {}, False

    cfg = Config()
    for f in fields(Config):
        if f.name not in raw:
            continue
        value, default = raw[f.name], getattr(cfg, f.name)
        if type(default) is float and type(value) is int:
            value = float(value)  # JSON writes 1.0 as 1
        # bool is a subclass of int, so check it explicitly
        if type(value) is not type(default):
            print(f"[config] {f.name}: expected {type(default).__name__}, got {value!r}; using default")
            continue
        setattr(cfg, f.name, value)

    if cfg.renderer not in RENDERERS:
        print(f"[config] renderer must be one of {RENDERERS}; using 'auto'")
        cfg.renderer = "auto"
    if cfg.theme not in THEMES:
        print(f"[config] theme must be one of {THEMES}; using 'blue'")
        cfg.theme = "blue"
    cfg.wheel_size = max(240, min(cfg.wheel_size, 900))
    cfg.pdf_image_dpi = max(36, min(cfg.pdf_image_dpi, 600))
    if cfg.compress_preset not in COMPRESS_PRESETS:
        print(f"[config] compress_preset must be one of {COMPRESS_PRESETS}; using 'balanced'")
        cfg.compress_preset = "balanced"
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", cfg.background_color):
        print("[config] background_color must look like #rrggbb; using #ffffff")
        cfg.background_color = "#ffffff"
    cfg.jpeg_quality = max(1, min(cfg.jpeg_quality, 100))
    if not (0.0 <= cfg.pinned_x <= 1.0 and 0.0 <= cfg.pinned_y <= 1.0):
        cfg.pinned_x = cfg.pinned_y = -1.0

    # Write back so new keys show up for the user to edit. (Never over a
    # file that couldn't be read: that would replace the user's settings
    # with the defaults.)
    if readable and raw.keys() != {f.name for f in fields(Config)}:
        save(cfg)
    return cfg


def save(cfg: Config) -> None:
    """Atomic: written to a temporary file that then replaces the config,
    so another Spindle process reading it never sees half a file."""
    path = config_path()
    text = json.dumps(asdict(cfg), indent=2) + "\n"
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(text, encoding="utf-8")
        for attempt in range(10):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:  # Windows: another process has it open for a moment
                if attempt == 9:
                    raise
                time.sleep(0.05)
    except OSError as exc:
        print(f"[config] could not write {path}: {exc}")
        tmp.unlink(missing_ok=True)
