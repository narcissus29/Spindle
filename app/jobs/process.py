"""ProcessWorker: runs jobs in the helper process (UI side).

- The helper starts with the first request and exits after `idle_ms` with
  nothing to do (stdin is closed; it ends by itself), so idle RAM goes back
  to the UI's own baseline. Its idle timer exists only while it runs.
- Everything is driven by QProcess signals in the UI event loop: no thread,
  no polling. The helper's stderr is forwarded to ours.
- cancel() kills the helper: the remaining files of every queued job are
  reported as "Cancelled", and half-written temporaries are deleted.
- If the helper crashes, the request it was on fails ("The helper
  stopped unexpectedly") and the rest are sent to a fresh helper. If it
  can't be started at all, or doesn't say hello within HELLO_TIMEOUT_MS,
  everything queued fails with that reason: the pill says so instead of
  waiting forever.
- The helper's error output (warnings, tracebacks, a crash's stack) goes
  to the log file, tagged "helper".
- Processes the helper starts (LibreOffice, Word) are reported ("child");
  when the helper is killed (cancel) or dies, they are stopped too. A
  helper that exits normally closes them itself.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from PyQt6.QtCore import QObject, QProcess, QTimer, pyqtSignal

from .. import PROJECT_DIR, logs, outputs
from . import Job, protocol

CANCELLED = "Cancelled"
CRASHED = "The helper stopped unexpectedly"
NOT_STARTED = "The helper didn't start"
HELLO_TIMEOUT_MS = 90_000  # a first start can be slow (antivirus scanning it), but not this slow


def helper_command() -> tuple[str, list[str]]:
    if getattr(sys, "frozen", False):  # PyInstaller build (step 5)
        return sys.executable, ["--job-runner"]
    return sys.executable, [str(PROJECT_DIR / "main.py"), "--job-runner"]


class ProcessWorker(QObject):
    fileProgress = pyqtSignal(object, int, float, str)  # job, index, fraction (-1: can't tell), text
    fileDone = pyqtSignal(object, int, str, list, dict)  # job, index, error ("" = ok), outputs, info
    jobFinished = pyqtSignal(object, int)  # job, number of files that failed or were cancelled
    thumbnailReady = pyqtSignal(str, str)  # source path, thumbnail path ("" = failed)

    def __init__(self, settings: dict | None = None, idle_ms: int = 30_000, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._settings = settings or {}
        self._proc: QProcess | None = None
        self._buffer = b""
        self._next_id = 1
        # id -> ("run", job, index) | ("thumb", source path); insertion order = helper order
        self._pending: dict[int, tuple] = {}
        self._requests: dict[int, dict] = {}  # id -> request, to resend after a crash
        self._temps: dict[int, list[Path]] = {}
        self._left: dict[int, list] = {}  # id(job) -> [job, files left, failed]
        self._stopping = False

        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.setInterval(idle_ms)
        self._idle.timeout.connect(self._close_idle)
        # One-shot, only while a helper is starting.
        self._hello = QTimer(self)
        self._hello.setSingleShot(True)
        self._hello.setInterval(HELLO_TIMEOUT_MS)
        self._hello.timeout.connect(lambda: self._give_up(f"{NOT_STARTED} (no answer)"))
        self._started_at = 0.0
        self._err_buffer = b""
        self._children: set[int] = set()  # started by the current helper

    # ------------------------------------------------------------------ API

    @property
    def running(self) -> bool:
        return self._proc is not None

    def submit(self, job: Job) -> None:
        if job.combine:  # one request, one result (reported as item 0)
            self._left[id(job)] = [job, 1, 0]
            first = job.items[0]
            self._send(("run", job, 0), {
                "type": "run", "spec": first.spec, "paths": [str(i.path) for i in job.items],
                "kinds": [i.kind for i in job.items], "option": job.option, "settings": self._settings,
            })
            return
        self._left[id(job)] = [job, len(job.items), 0]
        for index, item in enumerate(job.items):
            self._send(("run", job, index), {
                "type": "run", "spec": item.spec, "path": str(item.path),
                "kind": item.kind, "option": job.option, "settings": self._settings,
            })

    def request_thumbnail(self, path: Path, size: int, folder: Path) -> None:
        self._send(("thumb", str(path)), {"type": "thumb", "path": str(path), "size": size, "dir": str(folder)})

    def cancel(self) -> None:
        """Kill the helper; every queued file is reported as cancelled."""
        pending = list(self._pending.items())
        self._pending.clear()
        self._requests.clear()
        self._kill()
        for rid, entry in pending:
            self._drop_temps(rid)
            if entry[0] == "run":
                self._finish(entry[1], entry[2], CANCELLED, [], {})
            else:
                self.thumbnailReady.emit(entry[1], "")

    def shutdown(self) -> None:
        self._idle.stop()
        if self._proc is not None:
            self._proc.closeWriteChannel()
            if not self._proc.waitForFinished(2000):
                self._kill()

    # -------------------------------------------------------------- helpers

    def _send(self, entry: tuple, request: dict) -> None:
        rid = self._next_id
        self._next_id += 1
        request["id"] = rid
        self._pending[rid] = entry
        self._requests[rid] = request
        self._idle.stop()
        proc = self._ensure_process()
        if proc is not None and proc is self._proc:  # (not given up on while starting)
            proc.write(protocol.encode(request))

    def update_settings(self, settings: dict) -> None:
        """New settings (from the config) for the next requests."""
        self._settings = dict(settings)

    def _ensure_process(self) -> QProcess:
        if self._proc is not None and self._stopping:
            # Its stdin is already closed (idle exit under way): let it
            # finish on its own and start a fresh helper for this request.
            old, self._proc = self._proc, None
            old.readyReadStandardOutput.disconnect(self._on_output)
            old.finished.disconnect(self._on_finished)
            old.errorOccurred.disconnect(self._on_error)
            old.finished.connect(old.deleteLater)
        if self._proc is None:
            proc = QProcess(self)
            proc.readyReadStandardOutput.connect(self._on_output)
            proc.readyReadStandardError.connect(self._on_error_output)
            proc.finished.connect(self._on_finished)
            proc.errorOccurred.connect(self._on_error)
            program, args = helper_command()
            self._proc = proc
            self._buffer = self._err_buffer = b""
            self._stopping = False
            self._started_at = time.monotonic()
            self._hello.start()
            proc.start(program, args)
        return self._proc

    def _kill_children(self) -> None:
        from .. import platform_utils

        for pid in self._children:
            platform_utils.kill_process_tree(pid)
        self._children.clear()

    def _kill(self) -> None:
        self._idle.stop()
        self._hello.stop()
        self._kill_children()
        proc, self._proc = self._proc, None
        if proc is not None:
            proc.finished.disconnect(self._on_finished)
            proc.readyReadStandardOutput.disconnect(self._on_output)
            proc.errorOccurred.disconnect(self._on_error)
            proc.kill()
            proc.waitForFinished(2000)
            proc.deleteLater()

    def _close_idle(self) -> None:
        if self._proc is not None and not self._pending:
            self._stopping = True
            self._proc.closeWriteChannel()  # the helper exits at end of input

    def _on_output(self) -> None:
        proc = self.sender()
        if proc is not self._proc:
            return
        self._buffer += bytes(proc.readAllStandardOutput())
        *lines, self._buffer = self._buffer.split(b"\n")
        for line in lines:
            message = protocol.decode(line)
            if message is not None:
                self._handle(message)

    def _on_error_output(self) -> None:
        proc = self.sender()
        if proc is None:
            return
        self._err_buffer += bytes(proc.readAllStandardError()).replace(b"\r\n", b"\n")
        if b"\n" in self._err_buffer:
            done, _, self._err_buffer = self._err_buffer.rpartition(b"\n")
            logs.forward("helper", done.decode("utf-8", "replace"))

    def _on_error(self, error: QProcess.ProcessError) -> None:
        """Only "can't start" is handled here; a crash also ends in finished()."""
        proc = self.sender()
        if proc is self._proc and error == QProcess.ProcessError.FailedToStart:
            self._give_up(f"{NOT_STARTED} ({proc.errorString()})")

    def _give_up(self, reason: str) -> None:
        """The helper can't be used: everything queued fails with `reason`."""
        print(f"[jobs] {reason}: {' '.join(helper_command()[1]) or helper_command()[0]}", file=sys.stderr)
        short = reason.split(" (")[0]
        pending = list(self._pending.items())
        self._pending.clear()
        self._requests.clear()
        self._kill()
        for rid, entry in pending:
            self._drop_temps(rid)
            if entry[0] == "run":
                self._finish(entry[1], entry[2], short, [], {})
            else:
                self.thumbnailReady.emit(entry[1], "")

    def _handle(self, message: dict) -> None:
        if message.get("type") == "child":
            self._children.add(int(message["pid"]))
            return
        if message.get("type") == "hello":
            self._hello.stop()
            print(f"[jobs] helper ready in {round((time.monotonic() - self._started_at) * 1000)} ms "
                  f"(pid {message.get('pid')})", file=sys.stderr)
            return
        rid = message.get("id")
        entry = self._pending.get(rid)
        if entry is None:
            return
        kind = message["type"]
        if kind == "temp":
            self._temps.setdefault(rid, []).append(Path(message["path"]))
        elif kind == "progress" and entry[0] == "run":
            fraction = message.get("fraction")
            self.fileProgress.emit(entry[1], entry[2], -1.0 if fraction is None else float(fraction),
                                   str(message.get("text") or ""))
        elif kind in ("done", "error", "thumb"):
            self._pending.pop(rid)
            self._requests.pop(rid, None)
            self._temps.pop(rid, None)  # committed or already discarded by the helper
            if entry[0] == "run":
                error = message.get("message", "") if kind == "error" else ""
                self._finish(entry[1], entry[2], error, message.get("outputs", []), message.get("info") or {})
            else:
                self.thumbnailReady.emit(entry[1], message.get("path", "") if kind == "thumb" else "")
            if not self._pending:
                self._idle.start()

    def _finish(self, job: Job, index: int, error: str, paths: list, info: dict) -> None:
        self.fileDone.emit(job, index, error, paths, info)
        left = self._left.get(id(job))
        if left is None:
            return
        left[1] -= 1
        if error:
            left[2] += 1
        if left[1] <= 0:
            del self._left[id(job)]
            self.jobFinished.emit(job, left[2])

    def _on_finished(self, exit_code: int, status: QProcess.ExitStatus) -> None:
        proc, self._proc = self._proc, None
        if proc is not None:
            rest = bytes(proc.readAllStandardError()).replace(b"\r\n", b"\n")
            if self._err_buffer or rest:
                logs.forward("helper", (self._err_buffer + rest).decode("utf-8", "replace"))
            self._err_buffer = b""
            proc.deleteLater()
        self._idle.stop()
        said_hello = not self._hello.isActive()
        self._hello.stop()
        if self._stopping and not self._pending:
            self._children.clear()  # it closed them itself
            return  # normal idle exit
        self._kill_children()  # it died: what it started goes too
        if not self._pending:
            return
        if not said_hello:  # died while starting: a fresh one would too
            self._give_up(f"{NOT_STARTED} (exit code {exit_code})")
            return
        # Crashed (or exited) mid-request: fail the request it was on, then
        # resend the rest to a fresh helper.
        rid, entry = next(iter(self._pending.items()))
        self._pending.pop(rid)
        self._requests.pop(rid, None)
        self._drop_temps(rid)
        print(f"[jobs] helper stopped (exit {exit_code}, {status.name}) during request {rid}", file=sys.stderr)
        if entry[0] == "run":
            self._finish(entry[1], entry[2], CRASHED, [], {})
        else:
            self.thumbnailReady.emit(entry[1], "")
        rest = list(self._pending.items())
        self._pending.clear()
        for old_id, old_entry in rest:
            request = self._requests.pop(old_id)
            self._drop_temps(old_id)
            request = {k: v for k, v in request.items() if k != "id"}
            self._send(old_entry, request)

    def _drop_temps(self, rid: int) -> None:
        for path in self._temps.pop(rid, []):
            outputs.remove_temp(path)
