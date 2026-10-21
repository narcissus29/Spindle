"""Writing results safely, also in folders other people can write to."""

import os
import sys

import pytest

from app import outputs


def test_temp_names_are_random(tmp_path):
    a, b = outputs.temp_path_for(tmp_path / "r.pdf"), outputs.temp_path_for(tmp_path / "r.pdf")
    assert a != b and outputs.is_temp_path(a)


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_temp_is_never_written_through_a_planted_symlink(tmp_path, monkeypatch):
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me")
    tokens = iter(["aaaaaaaaaaaa", "bbbbbbbbbbbb"])
    monkeypatch.setattr(outputs.secrets, "token_hex", lambda n: next(tokens))
    planted = tmp_path / ".~r.txt.aaaaaaaaaaaa.part"
    planted.symlink_to(victim)
    temp = outputs.create_temp_file(tmp_path / "r.txt")
    assert temp.name == ".~r.txt.bbbbbbbbbbbb.part" and not temp.is_symlink()
    temp.write_text("result")
    assert victim.read_text() == "keep me"


def test_commit_never_replaces_a_file_that_appeared(tmp_path, monkeypatch):
    temp = outputs.create_temp_file(tmp_path / "r.txt")
    temp.write_text("new")
    (tmp_path / "r.txt").write_text("someone else's")
    real_lexists = os.path.lexists
    # The check says "free", but the file is there (it appeared in between).
    monkeypatch.setattr(outputs.os.path, "lexists", lambda p: False if str(p).endswith("r.txt") else real_lexists(p))
    dest = outputs.move_to_free_name(temp, tmp_path / "r.txt")
    assert dest.name == "r (1).txt" and dest.read_text() == "new"
    assert (tmp_path / "r.txt").read_text() == "someone else's" and not temp.exists()


def test_reserved_but_unwritten_outputs_leave_nothing(tmp_path):
    from app.handlers.common import Context

    src = tmp_path / "a.png"
    src.write_bytes(b"x")
    ctx = Context(src)
    ctx.output_file(".jpg")
    used = ctx.output_file(".webp")
    used.write_bytes(b"data")
    assert [p.name for p in ctx.commit()] == ["a.webp"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.png", "a.webp"]


# ---- the UI never goes online ----

def _serve():
    import http.server
    import threading

    hits = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(404)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, hits


def _show(qml_text, name, protect, tmp_path):
    from PyQt6.QtCore import QEventLoop, QTimer, QUrl
    from PyQt6.QtQuick import QQuickView

    from app import offline

    v = QQuickView()
    if protect:
        offline.protect(v.engine())
    v.rootContext().setContextProperty("name", name)
    qml = tmp_path / "probe.qml"
    qml.write_text("import QtQuick\nItem { width: 300; height: 80\n" + qml_text + "\n}\n")
    v.setSource(QUrl.fromLocalFile(str(qml)))
    v.show()
    loop = QEventLoop()
    QTimer.singleShot(1200, loop.quit)
    loop.exec()
    v.close()


def test_a_file_name_with_html_fetches_nothing(qapp, tmp_path):
    srv, hits = _serve()
    try:
        bait = f"photo<img src='http://127.0.0.1:{srv.server_address[1]}/t.png'>.jpg"
        # Rich text, unprotected: the request goes out (what this guards against).
        _show("Text { text: name }", bait, protect=False, tmp_path=tmp_path)
        assert hits == ["/t.png"]
        hits.clear()
        # The engine-wide block alone stops it ...
        _show("Text { text: name }", bait, protect=True, tmp_path=tmp_path)
        # ... and so does plain text, as every Text in Spindle's QML is.
        _show("Text { textFormat: Text.PlainText; text: name }", bait, protect=False, tmp_path=tmp_path)
        _show(f"Image {{ source: 'http://127.0.0.1:{srv.server_address[1]}/i.png' }}", "", protect=True,
              tmp_path=tmp_path)
        assert hits == []
    finally:
        srv.shutdown()


def test_every_qml_text_is_plain():
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "qml"
    for path in root.rglob("*.qml"):
        s = path.read_text(encoding="utf-8")
        for m in re.finditer(r"(?<![\w.])(Text|TextEdit) \{", s):
            depth, j = 1, m.end()
            while depth:
                depth += {"{": 1, "}": -1}.get(s[j], 0)
                j += 1
            block = s[m.end():j]
            assert "textFormat" in block, f"{path.name}: a {m.group(1)} without textFormat"
            assert "RichText" not in block and "AutoText" not in block, path.name
