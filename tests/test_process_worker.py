"""ProcessWorker: the UI side of the helper (QProcess, Qt event loop)."""

import time
from pathlib import Path

import pytest

from app.jobs import Job, JobItem
from app.jobs.process import CANCELLED, CRASHED, ProcessWorker
from tests.conftest import make_pdf


def wait_until(qapp, condition, timeout=30.0):
    from PyQt6.QtCore import QEventLoop

    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise TimeoutError("condition not met")
        qapp.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)


class Recorder:
    def __init__(self, worker):
        self.done, self.finished, self.progress, self.thumbs = [], [], [], []
        worker.fileDone.connect(lambda job, i, err, outs, info: self.done.append((i, err, outs)))
        worker.jobFinished.connect(lambda job, failed: self.finished.append(failed))
        worker.fileProgress.connect(lambda job, i, f, text: self.progress.append((i, f, text)))
        worker.thumbnailReady.connect(lambda src, thumb: self.thumbs.append((src, thumb)))


def fake_pdfs(folder: Path, names):
    paths = []
    for name in names:
        p = folder / name
        p.write_bytes(b"%PDF-1.4\n")
        paths.append(p)
    return paths


def job(paths, spec, option="TXT", kind="pdf"):
    return Job("convert", option, tuple(JobItem(p, kind, spec) for p in paths))


def test_batch_runs_file_by_file(qapp, tmp_path):
    w = ProcessWorker(idle_ms=60_000)
    rec = Recorder(w)
    srcs = [make_pdf(tmp_path / f"doc{i}.pdf", pages=2) for i in range(3)]
    w.submit(job(srcs, "app.handlers.pdf:to_txt"))
    wait_until(qapp, lambda: rec.finished)
    assert [d[0] for d in rec.done] == [0, 1, 2] and all(d[1] == "" for d in rec.done)
    assert rec.finished == [0]
    assert all((tmp_path / f"doc{i}.txt").exists() for i in range(3))
    assert rec.progress  # per-page progress arrived, with the page
    assert "Page 2/2" in [t for _i, _f, t in rec.progress]
    w.shutdown()


def test_cancel_kills_helper_and_cleans_up(qapp, tmp_path):
    w = ProcessWorker(idle_ms=60_000)
    rec = Recorder(w)
    srcs = fake_pdfs(tmp_path, ["a.pdf", "b.pdf", "c.pdf"])
    w.submit(job(srcs, "tests.helpers:slow"))
    wait_until(qapp, lambda: rec.progress)  # first file is mid-way
    w.cancel()
    assert [d[1] for d in rec.done] == [CANCELLED] * 3 and rec.finished == [3]
    assert not w.running
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.pdf", "b.pdf", "c.pdf"]  # temp removed
    # and the next job gets a fresh helper
    w.submit(job([make_pdf(tmp_path / "next.pdf", pages=1)], "app.handlers.pdf:to_txt"))
    wait_until(qapp, lambda: len(rec.finished) == 2)
    assert rec.done[-1][1] == "" and (tmp_path / "next.txt").exists()
    w.shutdown()


def test_crash_fails_one_file_and_the_batch_continues(qapp, tmp_path):
    w = ProcessWorker(idle_ms=60_000)
    rec = Recorder(w)
    srcs = fake_pdfs(tmp_path, ["one.pdf", "two-crash.pdf", "three.pdf"])
    w.submit(job(srcs, "tests.helpers:crash_on_marked"))
    wait_until(qapp, lambda: rec.finished)
    assert [(d[0], d[1]) for d in rec.done] == [(0, ""), (1, CRASHED), (2, "")]
    assert rec.finished == [1]
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["one.pdf", "one.txt", "three.pdf", "three.txt", "two-crash.pdf"]  # crash temp removed
    w.shutdown()


def test_helper_exits_when_idle(qapp, tmp_path):
    w = ProcessWorker(idle_ms=300)
    rec = Recorder(w)
    w.submit(job(fake_pdfs(tmp_path, ["a.pdf"]), "tests.helpers:noisy"))
    wait_until(qapp, lambda: rec.finished)
    assert w.running
    wait_until(qapp, lambda: not w.running, timeout=5)


def test_thumbnail(qapp, tmp_path):
    w = ProcessWorker(idle_ms=60_000)
    rec = Recorder(w)
    src = make_pdf(tmp_path / "report.pdf", pages=1)
    w.request_thumbnail(src, 64, tmp_path / "thumbs")
    wait_until(qapp, lambda: rec.thumbs)
    [(source, thumb)] = rec.thumbs
    assert source == str(src) and Path(thumb).exists()
    w.shutdown()
