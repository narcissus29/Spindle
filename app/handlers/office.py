"""Office documents -> PDF with the office app that is installed. Runs in
the helper process.

    to_pdf    report.docx -> report.pdf (also .doc .docm .rtf .odt, .xlsx .xls
              .xlsm .ods, .pptx .ppt .pptm .odp)
    convert   the same into a given path (Merge uses it)

Which app: on Windows, Microsoft Word / Excel / PowerPoint (COM) if that
one is installed, else LibreOffice; elsewhere LibreOffice. Nothing is
bundled: with neither, the file fails with "Needs Word or LibreOffice"
(Excel / PowerPoint for those files).

Safety, as the files can come from anywhere:
- macros never run (Office: AutomationSecurity = force disable;
  LibreOffice: its own profile, default macro security, headless);
- opened read-only, no dialogs, not added to recent files; the original
  is never changed;
- a password-protected file fails at once ("Password-protected
  document") instead of waiting on an invisible password prompt: a wrong
  password is passed, so Office reports an error rather than asking;
- an app that stops answering is killed after TIMEOUT_S ("Word didn't
  respond"). Every process this starts is reported to the wheel
  (ctx.child), so Cancel stops it too.

Office instances are started hidden, kept for the next file of a batch,
and closed when the helper exits. A PowerPoint the user already has open
is used as is (PowerPoint runs once per user) and never closed.
"""

from __future__ import annotations

import atexit
import shutil
import threading
import zipfile
from pathlib import Path

from .. import platform_utils as pu
from .common import Context, HandlerError

TIMEOUT_S = 300
_WRONG_PASSWORD = "spindle-no-password"  # Office fails on it instead of prompting

WORD, EXCEL, POWERPOINT = "word", "excel", "powerpoint"
FAMILY = {
    ".docx": WORD, ".doc": WORD, ".docm": WORD, ".rtf": WORD, ".odt": WORD,
    ".xlsx": EXCEL, ".xls": EXCEL, ".xlsm": EXCEL, ".ods": EXCEL,
    ".pptx": POWERPOINT, ".ppt": POWERPOINT, ".pptm": POWERPOINT, ".odp": POWERPOINT,
}
_APPS = {  # family -> (COM ProgID, name shown)
    WORD: ("Word.Application", "Word"),
    EXCEL: ("Excel.Application", "Excel"),
    POWERPOINT: ("PowerPoint.Application", "PowerPoint"),
}
_OOXML = {".docx", ".docm", ".xlsx", ".xlsm", ".pptx", ".pptm"}
_ODF = {".odt", ".ods", ".odp"}
_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def family_of(path: Path) -> str:
    return FAMILY.get(path.suffix.lower(), WORD)


def to_pdf(path: Path, option: str, ctx: Context) -> None:
    convert(path, ctx.output_file(".pdf"), ctx)
    ctx.progress(1.0)


def convert(path: Path, out: Path, ctx: Context) -> None:
    """Write `path` as a PDF to `out` (which may exist, empty)."""
    _refuse_encrypted(path)
    family = family_of(path)
    progid, name = _APPS[family]
    if pu.IS_WINDOWS and pu.office_app_installed(progid):
        ctx.progress(None, f"{name} is converting…")
        _office(family, path, out, ctx)
        return
    command = pu.libreoffice_command()
    if command is None:
        raise HandlerError(f"Needs {name} or LibreOffice")
    ctx.progress(None, "LibreOffice is converting…")
    _libreoffice(command, path, out, ctx)


def _refuse_encrypted(path: Path) -> None:
    """Password-protected OOXML is an OLE container instead of a zip;
    password-protected ODF lists encryption data in its manifest."""
    suffix = path.suffix.lower()
    try:
        with path.open("rb") as fh:
            head = fh.read(8)
        if suffix in _OOXML and head == _OLE:
            raise HandlerError("Password-protected document")
        if suffix in _ODF and zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                if b"encryption-data" in z.read("META-INF/manifest.xml"):
                    raise HandlerError("Password-protected document")
    except (OSError, KeyError, zipfile.BadZipFile):
        pass  # let the app say what is wrong with it


# ------------------------------------------------------------- LibreOffice

def _libreoffice(command: list[str], path: Path, out: Path, ctx: Context) -> None:
    profile, work = pu.libreoffice_folders(command, path)
    try:
        profile.mkdir(parents=True, exist_ok=True)
        args = command + [
            f"-env:UserInstallation={profile.as_uri()}",  # its own: an open LibreOffice can't take the job
            "--headless", "--invisible", "--nologo", "--norestore", "--nolockcheck", "--nodefault",
            "--convert-to", "pdf", "--outdir", str(work), str(path),
        ]
        proc = pu.start_hidden(args)
        ctx.child(proc.pid)
        try:
            output, _ = proc.communicate(timeout=TIMEOUT_S)
        except Exception:
            pu.kill_process_tree(proc.pid)
            proc.wait(10)
            raise HandlerError("LibreOffice didn't respond") from None
        text = output.decode("utf-8", "replace").strip()
        if text:
            print(f"[office] LibreOffice: {text}")
        made = work / f"{path.stem}.pdf"
        if not made.is_file() or made.stat().st_size == 0:
            raise HandlerError("LibreOffice couldn't convert it")
        shutil.move(str(made), str(out))
    finally:
        shutil.rmtree(work, ignore_errors=True)


# --------------------------------------------------- Microsoft Office (COM)

class _Instance:
    def __init__(self, app, pid: int | None) -> None:
        self.app = app
        self.pid = pid  # None: the user's own (PowerPoint already open)


_instances: dict[str, _Instance] = {}


def _instance(family: str, ctx: Context) -> _Instance:
    inst = _instances.get(family)
    if inst is not None:
        try:
            inst.app.Name  # still there?
            return inst
        except Exception:
            _instances.pop(family, None)
    progid, _name = _APPS[family]
    app, pid = pu.com_application(progid)
    inst = _Instance(app, pid)
    if pid is not None:
        ctx.child(pid)
        try:
            app.Visible = False
        except Exception:
            pass
    try:
        app.DisplayAlerts = 0 if family != EXCEL else False  # Word: wdAlertsNone; PowerPoint: ppAlertsNone
    except Exception:
        pass
    _instances[family] = inst
    return inst


def _quit_all() -> None:
    for inst in list(_instances.values()):
        if inst.pid is not None:  # only what Spindle started
            try:
                inst.app.Quit()
            except Exception:
                pu.kill_process_tree(inst.pid)
    _instances.clear()


atexit.register(_quit_all)


def _office(family: str, path: Path, out: Path, ctx: Context) -> None:
    name = _APPS[family][1]
    inst = _instance(family, ctx)
    app = inst.app
    # The user's own PowerPoint gets its setting back afterwards.
    saved_security = None
    try:
        saved_security = app.AutomationSecurity
        app.AutomationSecurity = 3  # msoAutomationSecurityForceDisable: no macros, ever
    except Exception:
        if inst.pid is None:
            raise HandlerError("Macros couldn't be turned off; not opening it") from None
    timer = None
    if inst.pid is not None:  # one that stops answering is stopped
        timer = threading.Timer(TIMEOUT_S, pu.kill_process_tree, (inst.pid,))
        timer.daemon = True
        timer.start()
    try:
        _export(family, app, path, out)
    except HandlerError:
        raise
    except Exception as exc:
        if timer is not None and not timer.is_alive():
            _instances.pop(family, None)
            raise HandlerError(f"{name} didn't respond") from None
        message = str(exc)
        print(f"[office] {name}: {message}")
        if "password" in message.lower():
            raise HandlerError("Password-protected document") from None
        raise HandlerError(f"{name} couldn't convert it") from None
    finally:
        if timer is not None:
            timer.cancel()
        if saved_security is not None and inst.pid is None:
            try:
                app.AutomationSecurity = saved_security
            except Exception:
                pass
    if not out.is_file() or out.stat().st_size == 0:
        raise HandlerError(f"{name} couldn't convert it")


def _export(family: str, app, path: Path, out: Path) -> None:
    """The Office object model calls (positional: late binding)."""
    src, dst = str(path), str(out)
    if family == WORD:
        # Open(FileName, ConfirmConversions, ReadOnly, AddToRecentFiles, PasswordDocument)
        doc = app.Documents.Open(src, False, True, False, _WRONG_PASSWORD)
        try:
            # ExportAsFixedFormat(OutputFileName, wdExportFormatPDF, OpenAfterExport,
            #   wdExportOptimizeForPrint, wdExportAllDocument, From, To, wdExportDocumentContent,
            #   IncludeDocProps, KeepIRM, wdExportCreateHeadingBookmarks, DocStructureTags,
            #   BitmapMissingFonts, UseISO19005_1)
            doc.ExportAsFixedFormat(dst, 17, False, 0, 0, 1, 1, 0, True, True, 1, True, True, False)
        finally:
            doc.Close(0)  # wdDoNotSaveChanges
    elif family == EXCEL:
        app.AskToUpdateLinks = False
        app.EnableEvents = False
        # Open(Filename, UpdateLinks, ReadOnly, Format, Password, WriteResPassword,
        #   IgnoreReadOnlyRecommended, Origin, Delimiter, Editable, Notify, Converter, AddToMru)
        book = app.Workbooks.Open(src, 0, True, 1, _WRONG_PASSWORD, "", True, 2, ",", False, False, 1, False)
        try:
            # ExportAsFixedFormat(xlTypePDF, Filename, xlQualityStandard, IncludeDocProperties,
            #   IgnorePrintAreas)
            book.ExportAsFixedFormat(0, dst, 0, True, False)
        finally:
            book.Close(False)
    else:
        # Open(FileName[::password], ReadOnly, Untitled, WithWindow): the
        # wrong password makes a protected file fail instead of asking.
        pres = app.Presentations.Open(f"{src}::{_WRONG_PASSWORD}", -1, 0, 0)
        try:
            pres.SaveAs(dst, 32)  # ppSaveAsPDF
        finally:
            pres.Close()
