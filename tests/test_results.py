"""What the pill and the notification say when a run ends."""

from pathlib import Path

import pytest

from app.config import Config
from app.jobs import Job, JobItem


@pytest.fixture
def bridge(qapp):
    from app.bridge import Bridge

    b = Bridge(Config())
    notes = []
    b.notify.connect(lambda t, body: notes.append((t, body)))
    b.notes = notes
    return b


def run(b, wheel, option, results):
    """results: list of (name, error, outputs, info) per file."""
    job = Job(wheel, option, tuple(JobItem(Path(n), "pdf", "x:y") for n, *_ in results))
    b._submit(job)
    for i, (name, error, outputs, info) in enumerate(results):
        b.file_done(job, i, error, outputs, info)
    return b._result_label(), b.notes[-1] if b.notes else None


def test_compress_single(bridge):
    label, note = run(bridge, "actions", "Compress", [("r.pdf", "", ["r (compressed).pdf"], {"note": "−62%", "before": 4_100_000, "after": 1_558_000})])
    assert label == "−62%"
    assert note == ("Compress: done", "r.pdf: 4.1 MB → 1.6 MB (−62%)")


def test_batch_with_some_already_compact(bridge):
    label, note = run(bridge, "actions", "Compress", [
        ("a.jpg", "", ["a (compressed).jpg"], {"note": "−50%", "before": 2_000_000, "after": 1_000_000}),
        ("b.jpg", "", [], {"note": "Already compact", "skipped": True}),
    ])
    assert label == "−50%"
    assert note == ("Compress: done", "1 of 2 files done, 1 skipped · 2.0 MB → 1.0 MB (−50%)")


def test_all_skipped_says_why(bridge):
    label, note = run(bridge, "actions", "Add BG", [("a.jpg", "", [], {"note": "No transparency", "skipped": True})] * 2)
    assert label == "No transparency"


def test_single_skip_notification(bridge):
    label, note = run(bridge, "actions", "Add BG", [("a.jpg", "", [], {"note": "No transparency", "skipped": True})])
    assert label == "No transparency" and note == ("Add BG", "a.jpg: No transparency")


def test_metadata_detail_in_notification(bridge):
    label, note = run(bridge, "actions", "Metadata", [("t.jpg", "", ["t (clean).jpg"], {"note": "Cleaned", "detail": "Removed EXIF, XMP"})])
    assert label == "Cleaned" and note == ("Metadata: done", "t.jpg: Removed EXIF, XMP")
