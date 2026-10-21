"""Single-instance guard over QLocalServer / QLocalSocket.

The first process listens on a per-user local socket (a Unix socket on Linux,
a named pipe on Windows). Later processes connect, send one command line
("show", "hide", "toggle", "quit") and exit. Everything is event-driven;
nothing polls.

The editor process uses the same socket to report back to the wheel:
"editor-ready" once its window is up, "editor-failed <message>" if the file
can't be edited. The setup window (welcome / settings) sends
"reload-config", "restart" and "settings", and asks questions that get a
one-line answer: "?hotkey Ctrl+Alt+Space" (Windows: "ok" or why not),
"?hotkey-pause" / "?hotkey-resume" (while it records a new shortcut),
"?hotkey-state" ("ok Alt+Shift+Space", or "off ..." if another app has it).

Two copies starting at the same moment (autostart while the user opens
Spindle) must not both become the resident one: a socket only exists once
its owner is up, and a Windows named pipe can even be created twice. So
the resident process also holds a lock file from the start (`acquire`);
whoever doesn't get it waits for the other one's socket instead.
"""

from __future__ import annotations

import getpass
import hashlib
import os

import time

from PyQt6.QtCore import QDir, QLockFile, QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

from . import APP_ID, platform_utils

COMMANDS = ("show", "hide", "toggle", "quit", "editor-ready", "reload-config", "restart", "settings", "noop")
_PREFIXED = ("editor-failed ",)  # commands that carry a message


def _base_name() -> str:
    try:
        user = getpass.getuser()
    except Exception:
        user = "user"
    digest = hashlib.sha1(user.encode("utf-8")).hexdigest()[:12]
    suffix = os.environ.get("SPINDLE_INSTANCE", "")  # tests: a separate instance next to a real one
    return f"{APP_ID}-{digest}" + (f"-{suffix}" if suffix else "")


def _server_name() -> str:
    """Linux: a socket in the user's private runtime folder (a full path);
    Windows: a named pipe (only this user may connect)."""
    folder = platform_utils.runtime_dir()
    return str(folder / _base_name()) if folder is not None else _base_name()


def _lock_path() -> str:
    folder = platform_utils.runtime_dir()
    return str(folder / f"{_base_name()}.lock") if folder is not None else \
        QDir.temp().absoluteFilePath(f"{_base_name()}.lock")


class SingleInstance(QObject):
    commandReceived = pyqtSignal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._name = _server_name()
        self._server: QLocalServer | None = None
        self._lock: QLockFile | None = None
        # Answers "?question" commands with one line (set by the app).
        self.responder = lambda question: ""

    def acquire(self, timeout_ms: int = 0) -> bool:
        """Take the lock of the resident process (kept until exit). False:
        another copy holds it (it is running, or starting up). A lock left
        by a crashed process is taken over."""
        lock = QLockFile(_lock_path())
        lock.setStaleLockTime(0)  # stale only if its process is gone
        if not lock.tryLock(timeout_ms):
            return False
        self._lock = lock
        return True

    def wait_for_running(self, command: str, timeout_s: float = 15.0) -> bool:
        """Another copy holds the lock but has no socket yet (it is still
        starting): hand it `command` as soon as it listens."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.send_to_running(command, timeout_ms=300):
                return True
            time.sleep(0.2)
        return False

    def send_to_running(self, command: str, timeout_ms: int = 600) -> bool:
        """Return True if a running instance received the command."""
        sock = QLocalSocket()
        sock.connectToServer(self._name)
        if not sock.waitForConnected(timeout_ms):
            return False
        sock.write((command + "\n").encode("utf-8"))
        sock.flush()
        sock.waitForBytesWritten(timeout_ms)
        sock.disconnectFromServer()
        if sock.state() != QLocalSocket.LocalSocketState.UnconnectedState:
            sock.waitForDisconnected(timeout_ms)
        return True

    def ask(self, question: str, timeout_ms: int = 2000) -> str | None:
        """Send "?question" to the running instance and wait for its
        one-line answer (None: not running / no answer)."""
        sock = QLocalSocket()
        sock.connectToServer(self._name)
        if not sock.waitForConnected(600):
            return None
        sock.write(("?" + question + "\n").encode("utf-8"))
        sock.flush()
        answer = None
        while not sock.canReadLine():
            if not sock.waitForReadyRead(timeout_ms):
                break
        if sock.canReadLine():
            answer = bytes(sock.readLine()).decode("utf-8", "replace").strip()
        sock.disconnectFromServer()
        return answer

    def listen(self) -> bool:
        server = QLocalServer(self)
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if not server.listen(self._name):
            # A crashed instance can leave a stale socket file behind on Unix.
            # send_to_running() already failed, so nobody owns it.
            QLocalServer.removeServer(self._name)
            if not server.listen(self._name):
                print(f"[instance] cannot listen on {self._name}: {server.errorString()}")
                return False
        server.newConnection.connect(self._on_new_connection)
        self._server = server
        return True

    def close(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
        if self._lock is not None:
            self._lock.unlock()
            self._lock = None

    def _on_new_connection(self) -> None:
        assert self._server is not None
        while self._server.hasPendingConnections():
            sock = self._server.nextPendingConnection()
            sock.readyRead.connect(lambda s=sock: self._read(s))
            sock.disconnected.connect(sock.deleteLater)
            if sock.bytesAvailable():
                self._read(sock)

    def _read(self, sock: QLocalSocket) -> None:
        while sock.canReadLine():
            command = bytes(sock.readLine()).decode("utf-8", "replace").strip()
            if command.startswith("?"):
                try:
                    answer = self.responder(command[1:])
                except Exception as exc:  # keep the instance alive
                    answer = f"error {exc}"
                sock.write((answer.replace("\n", " ") + "\n").encode("utf-8"))
                sock.flush()
                continue
            if command in COMMANDS or command.startswith(_PREFIXED):
                self.commandReceived.emit(command)
            else:
                print(f"[instance] ignoring unknown command {command!r}")
