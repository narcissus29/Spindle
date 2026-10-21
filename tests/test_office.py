"""Word / Excel / PowerPoint / OpenDocument -> PDF with the office app that
is installed: Microsoft Office through COM (faked here: CI has no Office),
LibreOffice for real wherever it is installed (CI installs it)."""

import os
import shutil
import sys
import threading
import time
from pathlib import Path

import pytest

from app import filetypes, platform_utils as pu
from app.handlers import office
from app.handlers.common import Context, HandlerError
from tests.conftest import make_docx, make_image, make_odf, make_pdf, make_xlsx

OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def text_of(pdf: Path) -> str:
    import pymupdf

    with pymupdf.open(pdf) as doc:
        return " ".join(page.get_text() for page in doc)


def write_pdf(dst: str, text: str = "converted") -> None:
    import pymupdf

    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), text)
    doc.save(dst)
    doc.close()


# ------------------------------------------------------------- detection

def test_documents_are_recognised_by_content(tmp_path):
    docx = make_docx(tmp_path / "a.docx")
    for p in (docx, make_xlsx(tmp_path / "b.xlsx"), make_odf(tmp_path / "c.odt"), make_odf(tmp_path / "d.ods"),
              make_odf(tmp_path / "e.odp")):
        assert filetypes.kind_from_path(p) == filetypes.DOCUMENT and filetypes.sniff_kind(p) == filetypes.DOCUMENT
    (tmp_path / "f.rtf").write_bytes(b"{\\rtf1\\ansi Hello}")
    (tmp_path / "g.doc").write_bytes(OLE + b"\0" * 504)
    assert filetypes.sniff_kind(tmp_path / "f.rtf") == filetypes.sniff_kind(tmp_path / "g.doc") == filetypes.DOCUMENT
    import zipfile

    with zipfile.ZipFile(tmp_path / "h.docx", "w") as z:  # a plain zip named .docx
        z.writestr("notes.txt", "hi")
    assert filetypes.sniff_kind(tmp_path / "h.docx") is None
    assert filetypes.format_label(docx) == "DOCX"


def test_password_protected_files_fail_at_once(tmp_path):
    (tmp_path / "secret.docx").write_bytes(OLE + b"\0" * 504)  # protected OOXML is an OLE container
    for p in (tmp_path / "secret.docx", make_odf(tmp_path / "secret.odt", encrypted=True)):
        with pytest.raises(HandlerError, match="Password-protected document"):
            office.convert(p, tmp_path / "out.pdf", Context(p))


@pytest.mark.parametrize("name, app", [("a.docx", "Word"), ("b.xlsx", "Excel"), ("c.odp", "PowerPoint")])
def test_without_an_office_app_it_says_what_is_needed(tmp_path, monkeypatch, name, app):
    monkeypatch.setattr(pu, "office_app_installed", lambda progid: False)
    monkeypatch.setattr(pu, "libreoffice_command", lambda: None)
    src = tmp_path / name
    {".docx": make_docx, ".xlsx": make_xlsx, ".odp": make_odf}[src.suffix](src)
    with pytest.raises(HandlerError, match=f"^Needs {app} or LibreOffice$"):
        office.convert(src, tmp_path / "out.pdf", Context(src))


# --------------------------------------------------- Microsoft Office (fake)

class FakeOffice:
    """Records the object-model calls; writes a real PDF on export."""

    def __init__(self, family, fail=None, delay=0.0):
        self.calls, self.family, self.fail, self.delay = [], family, fail, delay
        self.Visible, self.DisplayAlerts, self.AutomationSecurity = True, -1, 1
        self.Name = family
        app = self

        class Doc:
            def ExportAsFixedFormat(self, *args):
                app.calls.append(("export", args))
                time.sleep(app.delay)
                if app.fail:
                    raise app.fail
                write_pdf(args[1] if app.family == "excel" else args[0])

            def SaveAs(self, dst, fmt):
                app.calls.append(("saveas", (dst, fmt)))
                write_pdf(dst)

            def Close(self, *args):
                app.calls.append(("close", args))

        class Collection:
            def __init__(self, name):
                self.name = name

            def Open(self, *args):
                app.calls.append(("open", args, app.AutomationSecurity))
                if app.fail and "password" in str(app.fail).lower():
                    raise app.fail
                return Doc()

        self.Documents, self.Workbooks, self.Presentations = (Collection(n) for n in ("doc", "book", "pres"))

    def Quit(self):
        self.calls.append(("quit",))


@pytest.fixture
def fake_office(monkeypatch):
    made, killed, children = [], [], []

    def install(family="word", pid=4242, **kw):
        app = FakeOffice(family, **kw)
        monkeypatch.setattr(pu, "IS_WINDOWS", True)
        monkeypatch.setattr(pu, "office_app_installed", lambda progid: True)
        monkeypatch.setattr(pu, "com_application", lambda progid: (made.append(progid), (app, pid))[1])
        monkeypatch.setattr(pu, "kill_process_tree", killed.append)
        office._instances.clear()
        return app

    yield install, made, killed, children
    office._instances.clear()


def ctx_for(src, children):
    return Context(src, on_child=children.append)


def test_word_opens_read_only_with_macros_off_and_is_reused(tmp_path, fake_office):
    install, made, killed, children = fake_office
    app = install("word")
    for name in ("a.docx", "b.docx"):
        src = make_docx(tmp_path / name)
        out = tmp_path / f"{src.stem}.pdf"
        office.convert(src, out, ctx_for(src, children))
        assert text_of(out).strip() == "converted"
    assert made == ["Word.Application"] and children == [4242]  # one Word for the batch, reported once
    assert app.Visible is False and app.DisplayAlerts == 0
    opens = [c for c in app.calls if c[0] == "open"]
    assert all(c[2] == 3 for c in opens)  # macros forced off before opening
    path, confirm, read_only, recent, password = opens[0][1]
    assert read_only is True and recent is False and confirm is False and password == office._WRONG_PASSWORD
    export = next(c for c in app.calls if c[0] == "export")[1]
    assert export[1] == 17 and export[2] is False  # PDF, not opened afterwards
    assert ("close", (0,)) in app.calls  # never saved
    office._quit_all()
    assert ("quit",) in app.calls


def test_excel_and_powerpoint_calls(tmp_path, fake_office):
    install, made, killed, children = fake_office
    xl = install("excel")
    src = make_xlsx(tmp_path / "a.xlsx")
    office.convert(src, tmp_path / "a.pdf", ctx_for(src, children))
    opened = next(c for c in xl.calls if c[0] == "open")[1]
    assert opened[1] == 0 and opened[2] is True and opened[4] == office._WRONG_PASSWORD  # no link updates, read-only
    assert next(c for c in xl.calls if c[0] == "export")[1][:2] == (0, str(tmp_path / "a.pdf"))
    office._instances.clear()
    pp = install("powerpoint", pid=None)  # the user's own PowerPoint, already open
    pp.AutomationSecurity = 2
    src = make_odf(tmp_path / "s.odp")
    office.convert(src, tmp_path / "s.pdf", ctx_for(src, children))
    opened = next(c for c in pp.calls if c[0] == "open")
    assert opened[1][0].endswith("::" + office._WRONG_PASSWORD) and opened[1][1:] == (-1, 0, 0) and opened[2] == 3
    assert next(c for c in pp.calls if c[0] == "saveas")[1][1] == 32
    assert pp.AutomationSecurity == 2  # the user's setting is back
    office._quit_all()
    assert ("quit",) not in pp.calls and not killed  # never closed: it is the user's


def test_office_errors(tmp_path, fake_office):
    install, made, killed, children = fake_office
    install("word", fail=Exception("The password is incorrect. Word cannot open the document."))
    src = make_docx(tmp_path / "a.docx")
    with pytest.raises(HandlerError, match="^Password-protected document$"):
        office.convert(src, tmp_path / "a.pdf", Context(src))
    office._instances.clear()
    install("word", fail=Exception("Command failed"))
    with pytest.raises(HandlerError, match="^Word couldn't convert it$"):
        office.convert(src, tmp_path / "a.pdf", Context(src))


def test_office_that_stops_answering_is_killed(tmp_path, fake_office, monkeypatch):
    install, made, killed, children = fake_office
    monkeypatch.setattr(office, "TIMEOUT_S", 0.2)
    install("word", delay=0.6, fail=Exception("RPC server unavailable"))
    src = make_docx(tmp_path / "a.docx")
    with pytest.raises(HandlerError, match="^Word didn't respond$"):
        office.convert(src, tmp_path / "a.pdf", Context(src))
    assert killed == [4242] and "word" not in office._instances


# ------------------------------------------------------- LibreOffice (real)

# CI installs LibreOffice and sets SPINDLE_REQUIRE_LIBREOFFICE: there these tests must run.
needs_lo = pytest.mark.skipif(pu.libreoffice_command() is None and not os.environ.get("SPINDLE_REQUIRE_LIBREOFFICE"),
                              reason="LibreOffice isn't installed")


@pytest.fixture(scope="module")
def lo_profile(tmp_path_factory):
    return tmp_path_factory.mktemp("lo-profile")


@pytest.fixture
def libreoffice(monkeypatch, lo_profile):
    monkeypatch.setattr(pu, "office_app_installed", lambda progid: False)  # LibreOffice even on Windows
    real = pu.libreoffice_folders

    def folders(command, source):
        profile, work = real(command, source)
        return (lo_profile if profile.parent.name != "common" else profile), work
    monkeypatch.setattr(pu, "libreoffice_folders", folders)


@needs_lo
@pytest.mark.parametrize("maker, name, text", [
    (make_docx, "letter.docx", "Hello Spindle DOCX"), (make_xlsx, "sheet.xlsx", "Hello Spindle XLSX"),
    (make_odf, "notes.odt", "Hello Spindle ODF"), (make_odf, "talk.odp", "Hello Spindle ODF")])
def test_libreoffice_converts(tmp_path, libreoffice, maker, name, text):
    src = maker(tmp_path / name)
    children = []
    ctx = Context(src, on_child=children.append)
    office.to_pdf(src, "PDF", ctx)
    [out] = ctx.commit()
    assert out.name == f"{src.stem}.pdf" and text in text_of(out) and children
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([name, out.name])  # nothing left over


@needs_lo
def test_merge_documents_images_and_pdfs_in_order(qapp, tmp_path, libreoffice):
    from app.handlers.combine import to_one_pdf

    paths = [make_docx(tmp_path / "1 cover.docx", "First part"), make_image(tmp_path / "2 photo.png", "PNG"),
             make_pdf(tmp_path / "3 report.pdf", pages=2), make_odf(tmp_path / "4 end.odt", "Last part")]
    ctx = Context(paths[0])
    to_one_pdf(paths, "Merge", ctx)
    [out] = ctx.commit()
    import pymupdf

    with pymupdf.open(out) as doc:
        pages = [p.get_text() for p in doc]
    assert out.name == "1 cover (combined).pdf"
    assert "First part" in pages[0] and "Hello page 1" in pages[2] and "Last part" in pages[-1]


# ---------------------------------------------- cancel stops what it started

def _alive(pid: int) -> bool:
    if pu.IS_WINDOWS:
        return pid in pu.process_ids(Path(sys.executable).name)
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        return state not in ("Z", "X")
    except OSError:
        return False


def test_cancel_stops_processes_the_helper_started(qapp, tmp_path):
    from app.jobs import Job, JobItem
    from app.jobs.process import ProcessWorker
    from tests.test_process_worker import Recorder, wait_until

    src = make_docx(tmp_path / "a.docx")
    w = ProcessWorker(idle_ms=60_000)
    rec = Recorder(w)
    w.submit(Job("convert", "PDF", (JobItem(src, "document", "tests.helpers:starts_a_child"),)))
    wait_until(qapp, lambda: (tmp_path / "child.pid").exists() and w._children, timeout=30)
    pid = int((tmp_path / "child.pid").read_text())
    assert _alive(pid)
    w.cancel()
    deadline = time.monotonic() + 10
    while _alive(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not _alive(pid)
