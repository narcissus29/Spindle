"""The helper process, spoken to over its real stdin/stdout."""

import json
import subprocess
import sys
from pathlib import Path

from tests.conftest import ROOT, make_pdf


def helper():
    return subprocess.Popen([sys.executable, str(ROOT / "main.py"), "--job-runner"], cwd=ROOT,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def talk(requests: list[dict], timeout=60) -> tuple[list[dict], str, int]:
    proc = helper()
    data = "".join(json.dumps(r) + "\n" for r in requests).encode()
    out, err = proc.communicate(data, timeout=timeout)  # closing stdin = helper exits
    messages = [json.loads(line) for line in out.decode().splitlines()]
    assert messages[0]["type"] == "hello" and messages[0]["pid"] == proc.pid  # first: it is up
    return messages[1:], err.decode(), proc.returncode


def run_request(rid, spec, path, kind="pdf", option="TXT"):
    return {"type": "run", "id": rid, "spec": spec, "path": str(path), "kind": kind, "option": option, "settings": {}}


def test_run_reports_temp_progress_and_done(tmp_path):
    src = make_pdf(tmp_path / "report.pdf", pages=3)
    messages, _err, code = talk([run_request(1, "app.handlers.pdf:to_txt", src)])
    assert code == 0
    types = [m["type"] for m in messages]
    assert types[0] == "temp" and "progress" in types and types[-1] == "done"
    assert messages[-1]["outputs"] == [str(tmp_path / "report.txt")]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["report.pdf", "report.txt"]  # no temp left


def test_library_output_cannot_corrupt_the_protocol(tmp_path):
    src = tmp_path / "a.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    messages, err, _ = talk([run_request(1, "tests.helpers:noisy", src)])
    assert [m["type"] for m in messages] == ["temp", "done"]
    assert "this is not JSON" in err and "raw write to fd 1" in err  # went to stderr instead


def test_errors_are_messages_not_crashes(tmp_path):
    src = tmp_path / "a.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    png_named_pdf = tmp_path / "b.pdf"
    png_named_pdf.write_bytes(b"\x89PNG\r\n\x1a\n")
    messages, _, code = talk([
        run_request(1, "tests.helpers:fail", src),
        run_request(2, "app.handlers.pdf:to_txt", png_named_pdf),
        run_request(3, "app.handlers.pdf:to_txt", tmp_path / "missing.pdf"),
    ])
    assert code == 0
    errors = {m["id"]: m["message"] for m in messages if m["type"] == "error"}
    assert errors == {1: "Nope", 2: "Doesn't look like a PDF file", 3: "File not found"}


def test_thumbnail_request(tmp_path):
    src = make_pdf(tmp_path / "report.pdf", pages=1)
    messages, _, _ = talk([{"type": "thumb", "id": 9, "path": str(src), "size": 64, "dir": str(tmp_path / "t")}])
    [msg] = messages
    assert msg["type"] == "thumb" and Path(msg["path"]).exists()


def test_ui_side_never_imports_the_heavy_libraries():
    code = ("import sys; import app.bridge, app.jobs.process, app.handlers, app.window, app.editor.launcher; "
            "print([m for m in ('pymupdf', 'fitz', 'pdf2docx', 'cv2', 'numpy') if m in sys.modules])")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                         env={**__import__("os").environ, "QT_QPA_PLATFORM": "offscreen"})
    assert out.stdout.strip() == "[]", out.stderr


def test_skip_is_a_done_with_a_reason(qapp, tmp_path):
    from tests.conftest import make_photo

    src = make_photo(tmp_path / "photo.jpg", size=(64, 64))
    messages, _, _ = talk([run_request(1, "app.handlers.background:add_bg", src, kind="image", option="Add BG")])
    assert messages[-1] == {"type": "done", "id": 1, "outputs": [], "info": {"note": "No transparency", "skipped": True}}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["photo.jpg"]
