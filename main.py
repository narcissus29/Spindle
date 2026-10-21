"""Spindle entry point.

    python main.py            start the resident app (hidden), or show the wheel
                              if it is already running
    python main.py --show     show the wheel (starts the app if needed)
    python main.py --toggle   show, or hide if already shown (bind your shortcut to this)
    python main.py --hide     hide the wheel
    python main.py --quit     stop the running instance
    python main.py --background
                              start hidden (start at login): never shows the
                              wheel; if Spindle is already running, does nothing
    python main.py --stats    also log RAM / CPU / FPS every few seconds

    python main.py --job-runner   (internal) the helper process that runs
                                  conversions; started by the app itself
    python main.py --editor <tool> <file>
                                  (internal) the editor window for one file;
                                  started by the wheel (Crop / Edit / ...)
    python main.py --settings     the settings window
    python main.py --welcome      the first-run welcome (opened by the app)
"""

from __future__ import annotations

import sys
import time

_STARTED = time.monotonic()  # Python is up: the startup log says how long the rest took

# Output can go to a file or pipe with a legacy code page (Windows: cp1252),
# which can't show "✓": never let a log line crash a process.
for _stream in (sys.stdout, sys.stderr):
    if _stream is not None and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass

# The helper process must not load the GUI stack: branch off before any
# Qt GUI import so it only pays for what its handlers import.
if __name__ == "__main__" and "--job-runner" in sys.argv[1:]:
    from app.jobs.runner import main as run_helper

    sys.exit(run_helper())

# The editor is its own process too (its own window, PyMuPDF, numpy), so the
# resident wheel never loads any of that.
if __name__ == "__main__" and "--editor" in sys.argv[1:]:
    from app.editor.app import main as run_editor

    sys.exit(run_editor(sys.argv[1:]))

# The welcome / settings windows are a process of their own as well.
if __name__ == "__main__" and ("--settings" in sys.argv[1:] or "--welcome" in sys.argv[1:]):
    from app.setup.app import main as run_setup

    sys.exit(run_setup(sys.argv[1:]))

import argparse
import dataclasses
import os
import signal
import traceback
from pathlib import Path

from PyQt6.QtCore import QCoreApplication, QProcess, QTimer
from PyQt6.QtGui import QGuiApplication

from app import APP_ID, APP_NAME, __version__, app_name, config, platform_utils
from app.single_instance import SingleInstance

THUMB_SIZE = 128  # px; the hub shows it at ~40 logical px, sharp up to 3x DPI


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="spindle", description=f"{APP_NAME} {__version__}")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--show", action="store_true", help="show the wheel")
    g.add_argument("--toggle", action="store_true", help="show the wheel, or hide it if shown")
    g.add_argument("--hide", action="store_true", help="hide the wheel")
    g.add_argument("--quit", action="store_true", help="stop the running instance")
    g.add_argument("--background", action="store_true",
                   help="start hidden (used at login); does nothing if already running")
    p.add_argument("--remove-autostart", action="store_true", help=argparse.SUPPRESS)  # the uninstaller
    p.add_argument("--stats", action="store_true", help="log RAM / CPU / FPS every 5 s")
    p.add_argument("--software", action="store_true", help="use the software renderer for this run")
    p.add_argument("--installed", action="store_true", help=argparse.SUPPRESS)  # just copied to ~/Applications
    p.add_argument("--selftest", action="store_true", help="check and measure this build, then exit")
    return p.parse_known_args()[0]


def start_detached(*args: str) -> None:
    """Start Spindle itself (another process of it) with `args`."""
    argv = platform_utils.app_command(*args)
    QProcess.startDetached(argv[0], argv[1:])


def main() -> int:
    args = parse_args()
    command = next((c for c in ("show", "toggle", "hide", "quit") if getattr(args, c)), "")
    if args.remove_autostart:  # Windows uninstaller: the logon task / Run value go too
        platform_utils.set_autostart(False)
        return 0

    if args.selftest:  # its own socket and config: a running Spindle is never touched
        os.environ["SPINDLE_INSTANCE"] = "selftest"

    # Linux AppImage: the first run copies it to ~/Applications and runs
    # that copy (also after an update), so the app-menu entry, autostart
    # and shortcut always point at one stable file.
    installed = None if args.selftest else platform_utils.self_install_appimage()
    if installed is not None:
        os.execv(str(installed), [str(installed), *sys.argv[1:], "--installed"])

    # Everything printed from here on also goes to the log file (the
    # Windows app has no console).
    from app import logs

    if args.selftest:  # it checks what this run logs
        logs.log_path().unlink(missing_ok=True)
    logs.setup("wheel")

    # PyQt6 aborts the process on an unhandled exception in a slot unless a
    # custom excepthook is set. A resident app should log and keep running.
    sys.excepthook = lambda *exc: traceback.print_exception(*exc)

    # Ctrl+C in the terminal ends the app immediately. (The usual PyQt trick
    # of a QTimer that wakes Python up would cost idle CPU.)
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    QCoreApplication.setApplicationName(app_name())
    QCoreApplication.setOrganizationName("")
    QCoreApplication.setApplicationVersion(__version__)

    from app.window import configure_graphics, resolve_renderer

    # Satsuma is this app's old name: its settings come along (once).
    from app import legacy

    if not args.selftest and legacy.copy_settings(config.config_dir()):
        print(f"[migrate] settings copied from {legacy.old_folder(config.config_dir())}")
    cfg = config.load()
    renderer = resolve_renderer("software" if args.software else cfg.renderer)
    configure_graphics(renderer)

    from PyQt6.QtWidgets import QApplication  # the tray icon's menu needs Qt Widgets

    app = QApplication(sys.argv)
    app.setApplicationDisplayName(APP_NAME)
    app.setDesktopFileName(APP_ID)
    from app.icons import app_icon

    app.setWindowIcon(app_icon())
    app.setQuitOnLastWindowClosed(False)

    instance = SingleInstance()
    platform_utils.allow_foreground_handoff()
    # Opening Spindle again shows the wheel; the login start never does.
    handoff = "noop" if args.background else (command or "show")
    if args.installed and instance.send_to_running("quit"):
        # An older copy is running: it stops, this one takes over.
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and instance.send_to_running("noop", timeout_ms=200):
            time.sleep(0.1)
    elif instance.send_to_running(handoff):
        if args.background:
            print(f"[startup] {APP_NAME} is already running; nothing to do")
        return 0
    if command in ("hide", "quit"):
        print(f"{APP_NAME} is not running.")
        return 1
    if not instance.acquire(timeout_ms=5000 if args.installed else 0):
        # Another copy is starting up right now: it becomes the resident
        # one, this one just passes the command on.
        if instance.wait_for_running(handoff):
            return 0
        print(f"[instance] another {APP_NAME} holds the lock but doesn't answer")
        return 1
    if not instance.listen():
        return 1
    if not args.selftest:
        if legacy.stop_old_instance():
            print("[migrate] the old Satsuma was running: it was asked to quit")
        if not cfg.satsuma_cleaned:
            for line in legacy.clean_up(config.config_dir(), config.cache_dir(), logs.log_dir()):
                print(f"[migrate] {line}")
            cfg.satsuma_cleaned = True
            config.save(cfg)

    # Imported only in the resident process.
    from app.bridge import Bridge
    from app.jobs.process import ProcessWorker
    from app.window import WheelWindow

    bridge = Bridge(cfg)
    try:
        window = WheelWindow(bridge, cfg, renderer)
    except RuntimeError as exc:
        print(f"[startup] {exc}")
        return 1
    worker = ProcessWorker({
        "pdf_image_dpi": cfg.pdf_image_dpi,
        "jpeg_quality": cfg.jpeg_quality,
        "compress_preset": cfg.compress_preset,
        "background_color": cfg.background_color,
    })
    thumbs = config.cache_dir() / "thumbs"

    def on_file_done(job, index: int, error: str, outputs: list, info: dict) -> None:
        name = job.items[index].path.name
        if error:
            print(f"[job] {job.option} on {name}: {error}", flush=True)
        elif info.get("skipped"):
            print(f"[job] {job.option} on {name}: skipped ({info.get('note')})", flush=True)
        else:
            note = f" ({info['note']})" if info.get("note") else ""
            print(f"[job] {job.option} on {name} -> {', '.join(Path(p).name for p in outputs) or 'no output'}{note}", flush=True)
        bridge.file_done(job, index, error, outputs, info)

    from app.editor import launcher

    def open_editor(tool: str, path: str) -> None:
        if not launcher.launch(tool, Path(path), software=(renderer == "software")):
            bridge.editor_failed("Can't start the editor")

    bridge.editorRequested.connect(open_editor)
    bridge.jobRequested.connect(worker.submit)
    bridge.cancelRequested.connect(worker.cancel)
    bridge.thumbnailRequested.connect(lambda path: worker.request_thumbnail(Path(path), THUMB_SIZE, thumbs))
    bridge.notify.connect(platform_utils.notify)
    worker.fileProgress.connect(bridge.file_progress)
    worker.fileDone.connect(on_file_done)
    worker.thumbnailReady.connect(bridge.thumbnail_ready)

    hotkey = platform_utils.GlobalHotkey(window.toggle)

    def quit_app() -> None:
        hotkey.unregister()
        worker.shutdown()
        instance.close()
        app.quit()

    def open_settings() -> None:
        start_detached("--settings")

    def show_pinned() -> None:
        window.show_wheel()
        if not bridge.is_pinned:
            bridge.togglePin()

    # ---- tray icon ----
    from app.tray import Tray

    tray = None

    def update_tray() -> None:
        nonlocal tray
        if cfg.tray_icon and tray is None and Tray.available():
            tray = Tray(app_icon(), window.show_wheel, show_pinned, open_settings,
                        logs.show, quit_app)
            platform_utils.set_notifier(tray.notify)
        if tray is not None:
            tray.set_visible(cfg.tray_icon)
            platform_utils.set_notifier(tray.notify if cfg.tray_icon else None)

    if not args.selftest:
        update_tray()

    def worker_settings() -> dict:
        return {"pdf_image_dpi": cfg.pdf_image_dpi, "jpeg_quality": cfg.jpeg_quality,
                "compress_preset": cfg.compress_preset, "background_color": cfg.background_color}

    def reload_config() -> None:
        """The settings window saved the config: use it."""
        fresh = config.load()
        old_hotkey = cfg.hotkey
        for field in dataclasses.fields(fresh):
            setattr(cfg, field.name, getattr(fresh, field.name))
        worker.update_settings(worker_settings())
        if hotkey.supported() and cfg.hotkey != old_hotkey:
            hotkey.unregister()
            hotkey.register(cfg.hotkey)
        update_tray()
        bridge.stateChanged.emit()  # theme, reduce motion

    def restart() -> None:
        quit_app()
        start_detached()

    def answer(question: str) -> str:
        """Questions from the settings window (one-line answers)."""
        if question == "hotkey-pause":
            hotkey.unregister()
            return "ok"
        if question == "hotkey-resume":
            if hotkey.supported():
                hotkey.unregister()
                hotkey.register(cfg.hotkey)
            return "ok"
        if question == "wheel-state":
            return "shown" if bridge.is_shown else "hidden"
        if question == "hotkey-state":
            works = hotkey.registered or not hotkey.supported()
            return f"{'ok' if works else 'off'} {cfg.hotkey}"
        if question.startswith("hotkey "):
            # Only tries it: the settings window saves it to the config
            # (one writer), then sends reload-config.
            text = question[len("hotkey "):].strip()
            if not hotkey.supported():
                return "ok"
            hotkey.unregister()
            if hotkey.register(text):
                cfg.hotkey = text
                print(f"[hotkey] {text} toggles the wheel", flush=True)
                return "ok"
            hotkey.register(cfg.hotkey)  # keep the old one
            return "taken"
        return ""

    instance.responder = answer
    dbus_service = None if args.selftest else platform_utils.register_dbus_toggle(window.toggle, open_settings)

    def on_command(cmd: str) -> None:
        if cmd == "show":
            window.show_wheel()
        elif cmd == "toggle":
            window.toggle()
        elif cmd == "hide":
            window.hide_wheel()
        elif cmd == "quit":
            quit_app()
        elif cmd == "editor-ready":
            bridge.editor_ready()
            if args.selftest:
                selftest_editor_ready()
        elif cmd.startswith("editor-failed "):
            bridge.editor_failed(cmd.split(" ", 1)[1])
        elif cmd == "reload-config":
            reload_config()
        elif cmd == "restart":
            restart()
        elif cmd == "settings":
            open_settings()

    instance.commandReceived.connect(on_command)

    def on_graphics_failed(message: str) -> None:
        if renderer == "software":
            print("[render] the software renderer failed too; giving up")
            quit_app()
            return
        print("[render] switching to the software renderer and restarting")
        cfg.renderer = "software"
        config.save(cfg)
        quit_app()
        start_detached("--show")

    window.graphicsFailed.connect(on_graphics_failed)

    if hotkey.supported():
        if hotkey.register(cfg.hotkey):
            print(f"[hotkey] {cfg.hotkey} toggles the wheel")
    elif platform_utils.IS_LINUX and not platform_utils.gnome_shortcut():
        print(f"[hotkey] no global hotkey on Linux; bind a desktop shortcut to: {platform_utils.shortcut_command()}")
    selftest_editor_ready = lambda: None  # noqa: E731
    if args.selftest:
        from app import selftest

        def start_editor(photo: Path) -> int:
            program, cmd = launcher.editor_command("crop", photo, renderer == "software")
            ok, pid = QProcess.startDetached(program, cmd)
            return int(pid) if ok else 0

        def finish(code: int) -> None:
            quit_app()
            app.exit(code)

        selftest.run(app, bridge, window, worker, start_editor, finish)
        selftest_editor_ready = lambda: selftest.run.editor_ready()  # noqa: E731
    else:
        from app import BRAND_DIR, ICON_SIZES

        platform_utils.write_linux_entries({s: BRAND_DIR / f"icon-{s}.png" for s in ICON_SIZES})

    if not cfg.setup_done and not args.selftest and not args.background:  # first run: the welcome window
        QTimer.singleShot(400, lambda: start_detached("--welcome", *(["--installed"] if args.installed else [])))

    stats = None
    if args.stats or cfg.log_stats:
        from app.stats import StatsLogger

        stats = StatsLogger(window.view)

    print(f"[{APP_ID}] running ({platform_utils.window_strategy()} mode, renderer {renderer}, "
          f"platform {QGuiApplication.platformName()}, config {config.config_path()})", flush=True)
    if command in ("show", "toggle"):
        window.show_wheel()

    def log_ready() -> None:
        t = platform_utils.startup_times()
        fmt = lambda v: f"{v:.1f} s" if v is not None else "?"  # noqa: E731
        print(f"[startup] ready {fmt(time.monotonic() - _STARTED)} after Python started, "
              f"{fmt(t['process'])} after the process was created"
              + (f"; signed in {fmt(t['session'])} ago" if t["session"] is not None else "")
              + f"; booted {fmt(t['boot'])} ago ({'login start' if args.background else 'opened'}, "
              f"autostart: {platform_utils.autostart_method() or 'off'})", flush=True)

    QTimer.singleShot(0, log_ready)
    code = app.exec()
    stats = None
    dbus_service = None
    worker.shutdown()
    window.shutdown()
    return code


if __name__ == "__main__":
    sys.exit(main())
