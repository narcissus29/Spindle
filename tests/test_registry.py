from app import ICON_DIR, handlers
from app.filetypes import IMAGE, PDF


def test_add_bg_only_for_images():
    assert "Add BG" not in handlers.options_for(PDF, handlers.ACTIONS)
    assert "Add BG" in handlers.options_for(IMAGE, handlers.ACTIONS)


def test_mixed_pdf_and_image_actions_have_no_add_bg():
    from app.bridge import _batch_options, _File
    from pathlib import Path

    files = [_File(Path("a.pdf"), PDF, "PDF"), _File(Path("b.png"), IMAGE, "PNG")]
    names = _batch_options(files, handlers.ACTIONS)
    assert "Add BG" not in names and "Compress" in names


def test_every_option_has_an_icon_with_path_data():
    from app.icons import icon_path

    for kind in handlers.REGISTRY.values():
        for wheel in kind.values():
            for name in wheel:
                icon = handlers.ICONS.get(name)
                assert icon and (ICON_DIR / f"{icon}.svg").exists(), name
                assert icon_path(icon).startswith("M"), name


def test_editor_options_only_for_single_files():
    from app.bridge import _batch_options, _File
    from pathlib import Path

    one = [_File(Path("a.png"), IMAGE, "PNG")]
    two = one + [_File(Path("b.png"), IMAGE, "PNG")]
    assert {"Crop", "Edit", "Annotate", "Redact"} <= set(_batch_options(one, handlers.ACTIONS))
    assert _batch_options(two, handlers.ACTIONS) == ["Compress", "Metadata", "Add BG"]
    assert handlers.is_editor(handlers.get_handler(PDF, handlers.ACTIONS, "Crop"))
    assert not handlers.is_editor(handlers.get_handler(PDF, handlers.ACTIONS, "Compress"))


def test_editor_drop_requests_the_editor_and_shows_opening(qapp):
    from pathlib import Path

    from PyQt6.QtCore import QUrl

    from app.bridge import Bridge
    from app.config import Config

    b = Bridge(Config())
    asked = []
    b.editorRequested.connect(lambda tool, path: asked.append((tool, Path(path).name)))
    jobs = []
    b.jobRequested.connect(jobs.append)
    b.open()
    assert b.dragEnter([QUrl.fromLocalFile("/tmp/photo.jpg")])
    crop = [o["name"] for o in b.options].index("Crop")
    assert b.drop(crop)
    assert asked == [("crop", "photo.jpg")] and not jobs
    assert b.statusText == "Opening…" and not b.busy
    assert b.dragEnter([QUrl.fromLocalFile("/tmp/other.jpg")]) is False  # this wheel is about to close
    closed = []
    b.closeRequested.connect(lambda: closed.append(True))
    b.editor_ready()
    assert closed and b.statusText == ""


def test_editor_failure_is_shown_in_the_pill(qapp):
    from PyQt6.QtCore import QUrl

    from app.bridge import Bridge
    from app.config import Config

    b = Bridge(Config())
    b.open()
    b.dragEnter([QUrl.fromLocalFile("/tmp/secret.pdf")])
    b.park()  # PDFs open on Convert; the editor wedges are on Actions
    b.switchWheel()
    names = [o["name"] for o in b.options]
    b.activate(names.index("Redact"))
    assert b.statusText == "Opening…"
    b.editor_failed("Password-protected PDF")
    assert b.statusText == "Password-protected PDF"


def _files(*names):
    from pathlib import Path

    from app.bridge import _File
    from app.filetypes import format_label, kind_from_path

    return [_File(Path(n), kind_from_path(Path(n)), format_label(Path(n))) for n in names]


def test_every_multi_file_drop_has_pdf_each_and_merge():
    """Several files: "PDF" makes one PDF per file wherever every file can
    become one; "Merge" makes one combined PDF from any mix."""
    from app.bridge import _batch_options

    assert "Merge" not in _batch_options(_files("a.pdf"), handlers.CONVERT)
    assert "Merge" not in _batch_options(_files("a.png"), handlers.CONVERT)
    for names, has_pdf in ((("a.png", "b.jpg"), True), (("a.docx", "b.xlsx", "c.pptx"), True),
                           (("a.docx", "b.png"), True), (("a.pdf", "b.pdf"), False),
                           (("a.pdf", "b.png"), False), (("a.pdf", "b.odt", "c.jpg"), False)):
        options = _batch_options(_files(*names), handlers.CONVERT)
        assert "Merge" in options and options[-1] == "Merge", names
        assert ("PDF" in options) == has_pdf, names  # a PDF has nothing to become
    assert "Merge" not in _batch_options(_files("a.pdf", "b.pdf"), handlers.ACTIONS)


def _drop_on(b, names, option, wheel_switch=False):
    from PyQt6.QtCore import QUrl

    b.open()
    assert b.dragEnter([QUrl.fromLocalFile(f"/tmp/{n}") for n in names])
    if wheel_switch:
        b.park()
        b.switchWheel()
        b.activate([o["name"] for o in b.options].index(option))
    else:
        assert b.drop([o["name"] for o in b.options].index(option))


def test_several_images_merge_is_one_combined_job(qapp):
    from app.bridge import Bridge
    from app.config import Config

    b = Bridge(Config())
    jobs = []
    b.jobRequested.connect(jobs.append)
    _drop_on(b, ["z.png", "a.jpg", "m.webp"], "Merge", wheel_switch=True)  # images open on Actions
    [job] = jobs
    assert job.combine and [i.path.name for i in job.items] == ["z.png", "a.jpg", "m.webp"]
    assert job.items[0].spec == "app.handlers.combine:to_one_pdf"
    assert b.statusText == "Working…"  # one file to make, not "File 1/3"


def test_several_images_pdf_makes_one_each(qapp):
    from app.bridge import Bridge
    from app.config import Config

    b = Bridge(Config())
    jobs = []
    b.jobRequested.connect(jobs.append)
    _drop_on(b, ["z.png", "a.jpg"], "PDF", wheel_switch=True)
    [job] = jobs
    assert not job.combine and [i.spec for i in job.items] == ["app.handlers.image:convert"] * 2


def test_documents_open_on_convert_with_pdf(qapp):
    from PyQt6.QtCore import QUrl

    from app.bridge import Bridge
    from app.config import Config

    b = Bridge(Config())
    jobs = []
    b.jobRequested.connect(jobs.append)
    b.open()
    assert b.dragEnter([QUrl.fromLocalFile("/tmp/report.docx")])
    assert b.wheelName == handlers.CONVERT and [o["name"] for o in b.options] == ["PDF"] and not b.canSwitch
    assert b.drop(0)
    assert jobs[0].items[0].spec == "app.handlers.office:to_pdf" and jobs[0].items[0].kind == "document"
    b.dismiss()
    b.closeFinished()
    b.open()
    assert b.dragEnter([QUrl.fromLocalFile(f"/tmp/{n}") for n in ("a.docx", "b.pptx", "c.pdf")])
    assert [o["name"] for o in b.options] == ["Merge"]


def test_single_image_to_pdf_unchanged(qapp):
    from app.bridge import Bridge
    from app.config import Config

    b = Bridge(Config())
    jobs = []
    b.jobRequested.connect(jobs.append)
    _drop_on(b, ["a.png"], "PDF", wheel_switch=True)
    [job] = jobs
    assert not job.combine and job.items[0].spec == "app.handlers.image:convert"


def test_merge_pdfs_is_one_combined_job(qapp):
    from app.bridge import Bridge
    from app.config import Config

    b = Bridge(Config())
    jobs = []
    b.jobRequested.connect(jobs.append)
    _drop_on(b, ["b.pdf", "a.pdf"], "Merge")  # PDFs open on Convert
    [job] = jobs
    assert job.combine and [i.path.name for i in job.items] == ["b.pdf", "a.pdf"]


def test_drop_zone_rules(qapp):
    """Shortcut with nothing in hand: only the wheel takes input, focus loss
    and drops outside the ring don't close it, one action does."""
    from PyQt6.QtCore import QUrl

    from app.bridge import Bridge
    from app.config import Config

    b = Bridge(Config())
    closed = []
    b.closeRequested.connect(lambda: closed.append(True))
    b.open(drop_zone=True)
    assert b.dropZone and b.wheel_only and not b.pinned
    b.window_active_changed(True)
    b.window_active_changed(False)
    assert not closed  # focus loss ignored
    b.dragEnter([QUrl.fromLocalFile("/tmp/a.pdf")])
    b.drop(-1)  # missed the ring
    assert not closed and b.fileCount == 0
    b.dragEnter([QUrl.fromLocalFile("/tmp/a.pdf")])
    b.drop([o["name"] for o in b.options].index("TXT"))
    assert not closed and b.busy
    b.file_done(_job_of(b), 0, "", ["/tmp/a.txt"], {})
    b._result_timer.timeout.emit()  # "Done" shown -> closes
    assert closed
    b.closeFinished()
    b.open()
    assert not b.dropZone  # every open decides again


def _job_of(b):
    from app.jobs import Job, JobItem
    from pathlib import Path

    return Job("convert", "TXT", (JobItem(Path("/tmp/a.pdf"), "pdf", "x"),))


def test_popup_rules_unchanged(qapp):
    from app.bridge import Bridge
    from app.config import Config

    b = Bridge(Config())
    closed = []
    b.closeRequested.connect(lambda: closed.append(True))
    b.open(drop_zone=False)
    assert not b.wheel_only
    b.window_active_changed(True)
    b.window_active_changed(False)
    assert closed


def test_drop_zone_set_after_open_and_drag_seen(qapp):
    from PyQt6.QtCore import QUrl

    from app.bridge import Bridge
    from app.config import Config

    b = Bridge(Config())
    b.open()
    assert not b.drag_seen
    b.set_drop_zone(True)
    assert b.dropZone
    b.dragEnter([QUrl.fromLocalFile("/tmp/a.pdf")])
    assert b.drag_seen


def test_mixed_drop_merges_into_one_job(qapp):
    from app.bridge import Bridge
    from app.config import Config

    b = Bridge(Config())
    jobs = []
    b.jobRequested.connect(jobs.append)
    _drop_on(b, ["cover.jpg", "report.pdf", "back.png"], "Merge", wheel_switch=True)  # a mix opens on Actions
    [job] = jobs
    assert job.combine and [(i.path.name, i.kind) for i in job.items] == [
        ("cover.jpg", "image"), ("report.pdf", "pdf"), ("back.png", "image")]


# ---- parked files are a stack that grows ----

def _urls(*names):
    from PyQt6.QtCore import QUrl

    return [QUrl.fromLocalFile(f"/tmp/{n}") for n in names]


def _parked_bridge(*names):
    from app.bridge import Bridge
    from app.config import Config

    b = Bridge(Config())
    b.open()
    assert b.dragEnter(_urls(*names)) and b.park()
    return b


def test_drop_on_center_while_parked_adds_and_skips_duplicates(qapp):
    b = _parked_bridge("a.jpg", "b.png")
    assert b.fileCount == 2 and b.parked
    assert b.dragEnter(_urls("c.jpg", "a.jpg"))  # a.jpg is parked already
    assert b.fileCount == 3 and b.parked          # the badge shows the total while hovering
    assert b.park()
    assert b.fileCount == 3 and b.parked and b.formatLabel == "3 files"
    assert b.dragEnter(_urls("b.png")) and b.park()  # only a duplicate: nothing changes
    assert b.fileCount == 3


def test_options_are_for_the_whole_stack(qapp):
    from app import handlers

    b = _parked_bridge("a.png")
    one = [o["name"] for o in b.options]
    assert "Crop" in one  # an editor tool: one file only
    assert b.dragEnter(_urls("b.png")) and b.park()
    two = [o["name"] for o in b.options]
    assert "Crop" not in two
    b.switchWheel()
    assert b.wheelName == handlers.CONVERT and "PDF" in [o["name"] for o in b.options]


def test_drag_leaving_a_stack_puts_it_back(qapp):
    b = _parked_bridge("a.pdf")
    assert b.dragEnter(_urls("b.pdf", "c.pdf")) and b.fileCount == 3
    b.dragLeave()
    assert b.fileCount == 1 and b.parked


def test_refused_addition_keeps_the_stack(qapp):
    b = _parked_bridge("a.pdf")
    assert not b.dragEnter(_urls("notes.xyz"))  # unsupported: nothing in common
    assert b.refused or b.fileCount == 2
    b._refused_timer.timeout.emit()
    assert b.fileCount == 1 and b.parked and not b.refused


def test_drop_on_a_wedge_while_parked_runs_on_the_whole_stack(qapp):
    b = _parked_bridge("a.pdf", "b.pdf")
    jobs = []
    b.jobRequested.connect(jobs.append)
    assert b.dragEnter(_urls("c.pdf"))
    assert b.drop([o["name"] for o in b.options].index("TXT"))
    [job] = jobs
    assert [i.path.name for i in job.items] == ["a.pdf", "b.pdf", "c.pdf"] and not b.parked


def test_clear_button_and_close_put_the_stack_away(qapp):
    b = _parked_bridge("a.pdf", "b.pdf")
    b.clearStack()
    assert not b.parked and b.fileCount == 0 and b.is_shown  # the wheel stays open
    assert b.dragEnter(_urls("c.pdf")) and b.park() and b.fileCount == 1  # a fresh stack
    b.dismiss()
    b.closeFinished()
    assert not b.parked and b.fileCount == 0
    b.open()
    assert b.dragEnter(_urls("d.pdf")) and b.park() and b.fileCount == 1


def test_a_new_drag_without_parked_files_still_replaces(qapp):
    from app.bridge import Bridge
    from app.config import Config

    b = Bridge(Config())
    b.open()
    assert b.dragEnter(_urls("a.pdf"))
    b.dragLeave()
    assert b.dragEnter(_urls("b.pdf")) and b.fileCount == 1
