"""Failures are never silent: the log file (every process), rotation, the
helper failing to start or dying, and the pill saying so."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from app import logs
from app import platform_utils as pu
from app.jobs import Job, JobItem
from app.jobs import process as jp
from tests.conftest import make_pdf
from tests.test_process_worker import Recorder, wait_until

ROOT = Path(__file__).resolve().parents[1]


def log_env(tmp_path):
    env = {**os.environ, "SPINDLE_INSTANCE": f"pytest{os.getpid()}", "QT_QPA_PLATFORM": "offscreen"}
    if pu.IS_WINDOWS:
        env["LOCALAPPDATA"] = str(tmp_path / "local")
    else:
        env["XDG_STATE_HOME"] = str(tmp_path / "state")
    return env


def logged(tmp_path) -> str:
    name = f"spindle-pytest{os.getpid()}"
    folder = (tmp_path / "local" / name) if pu.IS_WINDOWS else (tmp_path / "state" / name)
    return (folder / "spindle.log").read_text(encoding="utf-8")


def test_log_folder_per_platform(monkeypatch, tmp_path):
    if pu.IS_WINDOWS:
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        assert pu.log_dir("spindle") == tmp_path / "spindle"
    elif pu.IS_LINUX:
        monkeypatch.delenv("XDG_STATE_HOME", raising=False)
        assert pu.log_dir("spindle") == Path.home() / ".local" / "state" / "spindle"
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        assert pu.log_dir("spindle") == tmp_path / "spindle"


def test_prints_and_tracebacks_reach_the_log(tmp_path):
    code = ("import sys; sys.path.insert(0, %r)\n"
            "from app import logs\n"
            "logs.setup('wheel')\n"
            "print('[job] hello')\n"
            "raise ValueError('boom')\n") % str(ROOT)
    out = subprocess.run([sys.executable, "-c", code], env=log_env(tmp_path), capture_output=True, text=True)
    assert out.returncode == 1 and "boom" in out.stderr  # the console still gets it
    text = logged(tmp_path)
    assert "wheel    --- wheel started" in text and "wheel    [job] hello" in text
    assert "ValueError: boom" in text and "Traceback" in text


def test_without_a_console_it_still_logs(tmp_path):
    """The Windows app: sys.stdout / sys.stderr are None."""
    code = ("import sys; sys.path.insert(0, %r)\n"
            "sys.stdout = sys.stderr = None\n"
            "from app import logs\n"
            "logs.setup('editor')\n"
            "print('[editor] opened')\n"
            "import traceback\n"
            "try:\n    1/0\nexcept ZeroDivisionError as e:\n    traceback.print_exception(e)\n") % str(ROOT)
    out = subprocess.run([sys.executable, "-c", code], env=log_env(tmp_path), capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    text = logged(tmp_path)
    assert "editor   [editor] opened" in text and "ZeroDivisionError" in text


def test_rotation(tmp_path, monkeypatch):
    path = tmp_path / "spindle.log"
    monkeypatch.setattr(logs, "_path", path)
    monkeypatch.setattr(logs, "MAX_BYTES", 2000)
    for i in range(400):
        logs.write("wheel", f"line {i} " + "x" * 40)
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["spindle.log", "spindle.log.1", "spindle.log.2", "spindle.log.3"]
    assert path.stat().st_size <= 2000 + 200
    assert "line 399" in path.read_text()


def _job(paths):
    return Job("convert", "TXT", tuple(JobItem(p, "pdf", "app.handlers.pdf:to_txt") for p in paths))


def test_helper_that_cant_start_fails_the_files(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(jp, "helper_command", lambda: (str(tmp_path / "no-such-program"), []))
    w = jp.ProcessWorker(idle_ms=60_000)
    rec = Recorder(w)
    srcs = [make_pdf(tmp_path / f"d{i}.pdf", pages=1) for i in range(2)]
    w.submit(_job(srcs))
    wait_until(qapp, lambda: rec.finished, timeout=10)
    assert [d[1] for d in rec.done] == [jp.NOT_STARTED, jp.NOT_STARTED]
    assert not w.running


def test_helper_dying_while_starting_is_not_restarted_forever(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(jp, "helper_command", lambda: (sys.executable, ["-c", "import sys; print('no module', file=sys.stderr); sys.exit(3)"]))
    forwarded = []
    monkeypatch.setattr(jp.logs, "forward", lambda tag, text: forwarded.append((tag, text)))
    w = jp.ProcessWorker(idle_ms=60_000)
    rec = Recorder(w)
    srcs = [make_pdf(tmp_path / f"d{i}.pdf", pages=1) for i in range(3)]
    w.submit(_job(srcs))
    wait_until(qapp, lambda: rec.finished, timeout=15)
    assert [d[1] for d in rec.done] == [jp.NOT_STARTED] * 3
    assert ("helper", "no module") in forwarded  # what it said is in the log


def test_helper_that_never_answers_times_out(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(jp, "HELLO_TIMEOUT_MS", 800)
    monkeypatch.setattr(jp, "helper_command", lambda: (sys.executable, ["-c", "import time; time.sleep(30)"]))
    w = jp.ProcessWorker(idle_ms=60_000)
    rec = Recorder(w)
    w.submit(_job([make_pdf(tmp_path / "d.pdf", pages=1)]))
    wait_until(qapp, lambda: rec.finished, timeout=10)
    assert rec.done[0][1] == jp.NOT_STARTED and not w.running


def test_pill_says_why_a_file_failed(qapp):
    from PyQt6.QtCore import QUrl

    from app.bridge import Bridge
    from app.config import Config

    b = Bridge(Config())
    jobs = []
    b.jobRequested.connect(jobs.append)
    b.open()
    assert b.dragEnter([QUrl.fromLocalFile("/tmp/a.pdf")])
    assert b.drop([o["name"] for o in b.options].index("TXT"))
    b.file_done(jobs[0], 0, "The helper didn't start", [], {})
    assert b.statusText == "The helper didn't start" and b.statusWarn
    b._result_timer.timeout.emit()
    b.closeFinished()
    b.open()
    assert b.dragEnter([QUrl.fromLocalFile(f"/tmp/{n}.pdf") for n in "abc"])
    assert b.drop([o["name"] for o in b.options].index("TXT"))
    for i, err in enumerate(("Password-protected PDF", "", "Can't open PDF (code=7: broken)")):
        b.file_done(jobs[1], i, err, [], {})
    assert b.statusText == "2 failed" and b.statusWarn


def test_helper_output_goes_to_the_log(qapp, tmp_path, monkeypatch):
    forwarded = []
    monkeypatch.setattr(jp.logs, "forward", lambda tag, text: forwarded.append((tag, text)))
    w = jp.ProcessWorker(idle_ms=60_000)
    rec = Recorder(w)
    src = make_pdf(tmp_path / "a.pdf", pages=1)
    w.submit(Job("convert", "TXT", (JobItem(src, "pdf", "app.handlers.nope:missing"),)))
    wait_until(qapp, lambda: rec.finished, timeout=30)
    w.shutdown()
    assert rec.done[0][1].startswith("ModuleNotFoundError")
    assert any(tag == "helper" and "Traceback" in text for tag, text in forwarded)
