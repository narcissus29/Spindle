from pathlib import Path

from app import outputs
from app.handlers.common import Context


def test_free_path_counts_up(tmp_path: Path):
    target = tmp_path / "report.docx"
    assert outputs.free_path(target) == target
    target.write_text("x")
    assert outputs.free_path(target).name == "report (1).docx"
    (tmp_path / "report (1).docx").write_text("x")
    assert outputs.free_path(target).name == "report (2).docx"


def test_free_path_for_folders(tmp_path: Path):
    folder = tmp_path / "report (PNG)"
    folder.mkdir()
    assert outputs.free_path(folder, is_dir=True).name == "report (PNG) (1)"


def test_context_writes_to_hidden_temp_then_commits(tmp_path: Path):
    src = tmp_path / "report.pdf"
    src.write_text("x")
    (tmp_path / "report.txt").write_text("already here")
    seen = []
    ctx = Context(src, on_temp=seen.append)
    tmp = ctx.output_file(".txt")
    assert tmp.name.startswith(".~report.txt.") and tmp.name.endswith(".part")
    assert seen == [tmp]
    tmp.write_text("new")
    [final] = ctx.commit()
    assert final.name == "report (1).txt" and final.read_text() == "new"
    assert (tmp_path / "report.txt").read_text() == "already here"
    assert not tmp.exists()


def test_context_discard_removes_temps(tmp_path: Path):
    src = tmp_path / "a.pdf"
    src.write_text("x")
    ctx = Context(src)
    f = ctx.output_file(".txt")
    f.write_text("x")
    d = ctx.output_dir("PNG")
    (d / "page-001.png").write_text("x")
    ctx.discard()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.pdf"]


def test_remove_temp_refuses_real_files(tmp_path: Path):
    real = tmp_path / "keep.txt"
    real.write_text("x")
    outputs.remove_temp(real)
    assert real.exists()
