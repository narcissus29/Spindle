"""Run the real wheel (`main.py`) as a separate process for a test, with
its own instance name, so it never meets a Spindle the user is running.
The caller isolates the config (environment / app name) first."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def start(*args: str, env: dict | None = None) -> subprocess.Popen:
    full = {**os.environ, "QT_QPA_PLATFORM": "offscreen", **(env or {})}
    return subprocess.Popen([sys.executable, str(ROOT / "main.py"), *args], env=full, cwd=str(ROOT),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace")


def ask(question: str, timeout_ms: int = 2000) -> str | None:
    from app.single_instance import SingleInstance

    return SingleInstance().ask(question, timeout_ms)


def wait_until_up(proc: subprocess.Popen, timeout_s: float = 30) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"the wheel exited ({proc.returncode}):\n{proc.stdout.read()}")
        if ask("hotkey-state", 300) is not None:
            return
        time.sleep(0.2)
    raise RuntimeError("the wheel didn't start")


def stop(proc: subprocess.Popen, timeout_s: float = 15) -> str:
    """Ask it to quit; returns everything it printed."""
    from app.single_instance import SingleInstance

    if proc.poll() is None:
        SingleInstance().send_to_running("quit")
        try:
            proc.wait(timeout_s)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(5)
    return proc.stdout.read()
