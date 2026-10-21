"""Starting the resident wheel: one copy only, also when two start at the
same moment (autostart while the user opens Spindle)."""

import time

from tests import wheel_process
from tests.test_shortcut_recorder import isolated  # noqa: F401 (fixture)


def test_two_copies_starting_together_leave_one(qapp, isolated):  # noqa: F811
    a = wheel_process.start()
    b = wheel_process.start()
    try:
        deadline = time.monotonic() + 30
        while wheel_process.ask("hotkey-state", 300) is None:  # one of them is up
            assert time.monotonic() < deadline and (a.poll() is None or b.poll() is None)
            time.sleep(0.2)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and a.poll() is None and b.poll() is None:
            time.sleep(0.2)
        exited = [p for p in (a, b) if p.poll() is not None]
        assert len(exited) == 1 and exited[0].returncode == 0  # it handed over and left
        assert wheel_process.ask("hotkey-state") is not None
    finally:
        out = wheel_process.stop(a) + wheel_process.stop(b)
        print(out)


def _log(isolated_dir) -> str:
    from app import logs

    try:
        return logs.log_path().read_text(encoding="utf-8")
    except OSError:
        return ""


def test_background_start_never_shows_the_wheel(qapp, isolated):  # noqa: F811
    import subprocess

    from app import config

    cfg = config.load()
    cfg.setup_done = False  # even on a first run: no welcome at login
    config.save(cfg)
    wheel = wheel_process.start("--background")
    try:
        wheel_process.wait_until_up(wheel)
        assert wheel_process.ask("wheel-state") == "hidden"
        # Started again at login while running (the rc1 bug): silent, nothing shown.
        again = wheel_process.start("--background")
        assert again.wait(30) == 0
        assert "already running" in again.stdout.read()
        assert wheel_process.ask("wheel-state") == "hidden"
        time.sleep(1.5)
        text = _log(isolated)
        assert "[startup] ready" in text and "login start" in text
        assert "--- welcome started" not in text
        # Opening it by hand still shows the wheel.
        opened = wheel_process.start()
        assert opened.wait(30) == 0
        deadline = time.monotonic() + 5
        while wheel_process.ask("wheel-state") != "shown" and time.monotonic() < deadline:
            time.sleep(0.1)
        assert wheel_process.ask("wheel-state") == "shown"
    finally:
        print(wheel_process.stop(wheel))


def test_startup_times_are_plausible():
    from app import platform_utils as pu

    t = pu.startup_times()
    assert t["boot"] is None or t["boot"] > 0
    assert t["process"] is None or 0 <= t["process"] < 3600 * 24 * 30
    if pu.IS_LINUX:
        assert t["boot"] and t["process"] is not None


import pytest  # noqa: E402

from app import platform_utils as _pu  # noqa: E402


@pytest.mark.skipif(not _pu.IS_WINDOWS, reason="Task Scheduler")
def test_windows_logon_task(isolated):  # noqa: F811
    import subprocess

    pu = _pu
    assert not pu.autostart_enabled()
    pu.set_autostart(True)
    try:
        assert pu.autostart_method() == "task"
        xml = pu._schtasks("/Query", "/TN", pu._task_name(), "/XML").stdout
        assert "<LogonTrigger>" in xml and "--background" in xml
        assert "<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>" in xml
        assert "<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>" in xml
        assert pu._windows_run_value() is None
        # The uninstaller's cleanup.
        out = wheel_process.start("--remove-autostart")
        assert out.wait(60) == 0
        assert not pu.autostart_enabled()
    finally:
        pu.set_autostart(False)


@pytest.mark.skipif(not _pu.IS_LINUX, reason="Linux runtime folder")
def test_socket_and_lock_are_private_on_linux():
    import stat

    from app import single_instance as si

    folder = _pu.runtime_dir()
    if folder is None:
        pytest.skip("no private runtime folder here")
    assert si._server_name().startswith(str(folder) + "/") and si._lock_path().startswith(str(folder) + "/")
    assert not stat.S_IMODE(folder.stat().st_mode) & 0o077


def test_desktop_exec_quoting():
    line = _pu._exec_line(["/home/u/100% sure/Spindle.AppImage", "--background"])
    assert line == '"/home/u/100%% sure/Spindle.AppImage" "--background"'
    assert _pu._exec_line(['/a/"b"$c'], desktop=False) == '"/a/\\"b\\"\\$c"'
