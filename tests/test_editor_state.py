import numpy as np
import pytest

from app.editor import imaging, state as st


def test_history_undo_redo_and_modified():
    h = st.History(st.new_image_state())
    assert not h.can_undo and not h.modified
    a = st.turn_image(h.state, "cw")
    assert h.push(a, "Rotate")
    assert not h.push(dict(a), "Rotate")  # no change: not recorded
    b = {**a, "crop": [0.1, 0.1, 0.5, 0.5]}
    h.push(b, "Crop")
    assert h.undo_label == "Crop" and h.modified
    h.undo()
    assert h.state == a and h.redo_label == "Crop"
    h.mark_saved()
    assert not h.modified
    h.redo()
    assert h.modified
    h.undo()
    h.undo()
    assert h.state == st.new_image_state() and h.modified  # differs from the saved one
    h.push(st.turn_image(h.state, "h"), "Flip")
    assert not h.can_redo  # a new change drops what was undone


def test_crop_cleanup():
    assert st.clean_rect([0, 0, 1, 1]) is None
    assert st.clean_rect([-0.2, 0.5, 0.5, 0.9]) == [0.0, 0.5, 0.3, 0.5]
    assert st.clean_rect([0.5, 0.5, 0, 0.2]) is None


def test_four_quarter_turns_and_double_flips_are_identity():
    s = {**st.new_image_state(), "crop": [0.1, 0.2, 0.3, 0.4]}
    t = s
    for _ in range(4):
        t = st.turn_image(t, "cw")
    assert t == s
    assert st.turn_image(st.turn_image(s, "h"), "h") == s
    assert st.turn_image(st.turn_image(s, "v"), "v") == s
    assert st.turn_image(st.turn_image(s, "cw"), "ccw") == s


def _pattern(qapp, w=8, h=5):
    """Every pixel a different color, so any wrong turn shows."""
    from PyQt6.QtGui import QColor, QImage

    img = QImage(w, h, QImage.Format.Format_RGB32)
    for y in range(h):
        for x in range(w):
            img.setPixelColor(x, y, QColor(x * 30, y * 50, (x * 7 + y * 13) % 256))
    return img


def _pixels(img):
    from PyQt6.QtGui import QImage

    img = img.convertToFormat(QImage.Format.Format_RGB32)
    return [[img.pixel(x, y) for x in range(img.width())] for y in range(img.height())]


@pytest.mark.parametrize("ops", [["cw"], ["ccw"], ["h"], ["v"], ["cw", "h"], ["h", "cw"], ["v", "ccw", "cw", "cw"]])
def test_crop_stays_on_the_same_part_of_the_picture(qapp, ops):
    """Cropping then turning the result == turning with the crop carried
    along (what the state does)."""
    from PyQt6.QtGui import QTransform

    from PyQt6.QtCore import Qt

    img = _pattern(qapp)
    s = {**st.new_image_state(), "crop": [0.25, 0.2, 0.5, 0.6]}
    expected = imaging.render_image(img, s)
    for op in ops:
        s = st.turn_image(s, op)
        if op == "cw":
            expected = expected.transformed(QTransform().rotate(90))
        elif op == "ccw":
            expected = expected.transformed(QTransform().rotate(270))
        elif op == "h":
            expected = expected.flipped(Qt.Orientation.Horizontal)
        else:
            expected = expected.flipped(Qt.Orientation.Vertical)
    assert _pixels(imaging.render_image(img, s)) == _pixels(expected)


def test_pdf_page_turn_moves_the_crop():
    s = st.new_pdf_state(2)
    s = st.set_page(s, 1, crop=[0.1, 0.2, 0.3, 0.4])
    t = st.turn_page(s, 1, "cw")
    assert t["pages"][1]["rot"] == 90 and t["pages"][1]["crop"] == pytest.approx([0.4, 0.1, 0.4, 0.3])
    assert t["pages"][0] == s["pages"][0]


def test_output_tags():
    s = st.new_image_state()
    assert st.output_tag({**s, "crop": [0, 0, 0.5, 0.5]}) == "cropped"
    assert st.output_tag(st.turn_image(s, "cw")) == "edited"
    p = st.new_pdf_state(3)
    assert st.output_tag(st.set_page(p, 0, crop=[0, 0, 0.5, 0.5])) == "cropped"
    assert st.output_tag(st.set_page(p, 0, deleted=True)) == "edited"


def test_adjust_matches_the_shader_formula(qapp):
    """The numpy path must equal MultiEffect's per-pixel math (see
    imaging.py), within rounding."""
    from PyQt6.QtGui import QColor, QImage

    rnd = np.random.default_rng(3)
    img = QImage(37, 11, QImage.Format.Format_ARGB32)
    colors = rnd.integers(0, 256, size=(11, 37, 4))
    for y in range(11):
        for x in range(37):
            r, g, b, a = (int(v) for v in colors[y, x])
            img.setPixelColor(x, y, QColor(r, g, b, max(a, 1)))
    for b, c, s in [(0.2, 0, 0), (0, 0.5, 0), (0, -0.6, 0), (0, 0, 0.8), (0, 0, -1), (-0.1, 0.3, -0.4)]:
        out = imaging.apply_adjust(img, {"brightness": b, "contrast": c, "saturation": s})
        for y in range(0, 11, 3):
            for x in range(0, 37, 5):
                src = img.pixelColor(x, y)
                rgb = np.array([src.red(), src.green(), src.blue()], dtype=np.float64) / 255
                v = (rgb - 0.5) * (1 + c) + 0.5 + b
                gray = v @ [0.299, 0.587, 0.114]
                v = gray + (v - gray) * (1 + s)
                want = np.clip(np.round(v * 255), 0, 255)
                got = out.pixelColor(x, y)
                assert np.abs(np.array([got.red(), got.green(), got.blue()]) - want).max() <= 1
                assert got.alpha() == src.alpha()


def test_neutral_adjust_returns_the_same_image(qapp):
    img = _pattern(qapp)
    assert imaging.apply_adjust(img, dict(st.NO_ADJUST)) is img


def test_crop_pixels_rounding():
    r = imaging.crop_pixels(100, 50, [0.104, 0.5, 0.3, 0.5])
    assert (r.x(), r.y(), r.width(), r.height()) == (10, 25, 30, 25)
    tiny = imaging.crop_pixels(100, 50, [0.999, 0.999, 0.0001, 0.0001])
    assert tiny.width() >= 1 and tiny.height() >= 1
