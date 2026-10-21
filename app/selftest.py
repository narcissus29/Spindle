"""`--selftest`: the packaged app checks and measures itself (also on a CI
machine with no screen: QT_QPA_PLATFORM=offscreen).

It starts like the real app (its own socket and config, so a running
Spindle is never touched), then:
  1. idle memory of the resident wheel process, fresh;
  2. shows and hides the wheel, idle memory again;
  3. runs real jobs in the helper (PDF -> DOCX, 12 MP photo -> under
     200 KB) and reads the helper's peak memory;
  4. opens the editor on that photo and reads its peak memory;
  5. checks the log file has lines from the wheel, the helper and the
     editor;
and prints one JSON line ("SELFTEST {...}") with everything, plus "ok".
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

from PyQt6.QtCore import QTimer

from . import platform_utils as pu

MB = 1024 * 1024


def _mb(value):
    return round(value / MB, 1) if value else None


def _make_files(folder: Path) -> tuple[Path, Path]:
    """A one-page text PDF (written by hand: the wheel process doesn't load
    PyMuPDF) and a noisy 12 MP photo."""
    import random

    from PyQt6.QtGui import QColor, QImage, QPainter

    pdf = folder / "letter.pdf"
    content = b"BT /F1 24 Tf 72 720 Td (Spindle self-test) Tj 0 -40 Td (Hello) Tj ET"
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    pdf.write_bytes(bytes(out))

    photo = folder / "photo.jpg"
    rnd = random.Random(3)
    image = QImage(4000, 3000, QImage.Format.Format_RGB32)
    image.fill(QColor("#4a7bd0"))
    p = QPainter(image)
    for _ in range(6000):
        p.fillRect(rnd.randrange(4000), rnd.randrange(3000), rnd.randrange(4, 40), rnd.randrange(4, 40),
                   QColor(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)))
    p.end()
    image.save(str(photo), "JPG", 92)
    return pdf, photo


def _check_log() -> dict:
    from . import logs

    try:
        text = logs.log_path().read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    return {"wheel": "--- wheel started" in text, "helper": "helper ready in" in text,
            "editor": "--- editor started" in text}


def run(app, bridge, window, worker, start_editor, quit_app) -> None:
    """Called by main() instead of waiting for the user."""
    from .jobs import Job, JobItem

    report: dict = {"platform": sys.platform, "qpa": app.platformName(), "version": None}
    from . import __version__

    report["version"] = __version__
    folder = Path(tempfile.mkdtemp(prefix="spindle-selftest-"))
    state: dict = {"helper_peak": {}, "jobs": []}

    def mem(key: str) -> None:
        rss, private = pu.memory_info()
        report[key] = {"rss_mb": _mb(rss), "private_mb": _mb(private)}

    def step1() -> None:
        mem("idle_fresh")
        window.show_wheel()
        QTimer.singleShot(1500, step2)

    def step2() -> None:
        window.hide_wheel()
        QTimer.singleShot(4000, step3)

    def step3() -> None:
        mem("idle_after_use")
        pdf, photo = _make_files(folder)
        state["photo"] = photo
        state["pending"] = 2
        worker.fileDone.connect(on_done)
        worker.submit(Job("convert", "DOCX", (JobItem(pdf, "pdf", "app.handlers.pdf:to_docx"),)))
        worker.submit(Job("actions", "200 KB", (JobItem(photo, "image", "app.handlers.compress:to_target"),)))
        poll_helper()

    def poll_helper() -> None:
        proc = getattr(worker, "_proc", None)
        if proc is not None and proc.processId():
            m = pu.process_memory(int(proc.processId()))
            if m["peak"] and m["peak"] > (state["helper_peak"].get("peak") or 0):
                state["helper_peak"] = m
        if state["pending"] > 0:
            QTimer.singleShot(100, poll_helper)

    def on_done(job, index, error, outputs, info) -> None:
        state["jobs"].append({"option": job.option, "error": error,
                              "outputs": [Path(o).name for o in outputs], "note": info.get("note", "")})
        state["pending"] -= 1
        if state["pending"] == 0:
            report["helper"] = {"peak_mb": _mb(state["helper_peak"].get("peak")),
                                "rss_mb": _mb(state["helper_peak"].get("rss"))}
            report["jobs"] = state["jobs"]
            QTimer.singleShot(200, step4)

    def step4() -> None:
        state["editor_t0"] = time.monotonic()
        state["editor_pid"] = start_editor(state["photo"])
        QTimer.singleShot(500, poll_editor)

    def poll_editor() -> None:
        pid = state.get("editor_pid")
        ready = bridge_ready()
        if pid:
            m = pu.process_memory(pid)
            if m["peak"]:
                state["editor_mem"] = m
        if ready and time.monotonic() - state["editor_ready_at"] > 2.5:
            m = state.get("editor_mem", {})
            report["editor"] = {"peak_mb": _mb(m.get("peak")), "rss_mb": _mb(m.get("rss")),
                                "open_s": round(state["editor_ready_at"] - state["editor_t0"], 2)}
            pu.kill_process(pid)
            finish()
            return
        if time.monotonic() - state["editor_t0"] > 60:
            report["editor"] = {"error": "editor never reported ready"}
            pu.kill_process(pid) if pid else None
            finish()
            return
        QTimer.singleShot(250, poll_editor)

    def bridge_ready() -> bool:
        if "editor_ready_at" not in state and state.get("ready"):
            state["editor_ready_at"] = time.monotonic()
        return "editor_ready_at" in state

    def finish() -> None:
        report["log"] = _check_log()
        ok = (all(not j["error"] for j in state["jobs"]) and "error" not in report.get("editor", {})
              and all(report["log"].values()))
        report["ok"] = ok
        print("SELFTEST " + json.dumps(report), flush=True)
        import shutil

        shutil.rmtree(folder, ignore_errors=True)
        quit_app(0 if ok else 1)

    def editor_reported_ready() -> None:
        state["ready"] = True

    run.editor_ready = editor_reported_ready  # main() forwards "editor-ready" here
    QTimer.singleShot(5000, step1)
