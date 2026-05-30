"""Headless tests for the GUI document model (app_core).

Covers the whole edit flow the window depends on -- painting the mask,
box-select, erase, clean-via-engine, undo/redo, and save -- with no display.
The Tkinter widget layer (app.py) is exercised separately under Xvfb.
"""
import numpy as np
import pytest

import app_core
import engine


def bgra_with_mark(h=40, w=40):
    img = np.zeros((h, w, 4), np.uint8)
    img[:, :, 0] = 200
    img[:, :, 1] = 120
    img[:, :, 2] = 40
    img[:, :, 3] = 255
    img[h - 12:h, w - 12:w, :3] = (255, 0, 255)
    return img


def make_doc():
    return app_core.Document(bgra_with_mark())


# -- painting --------------------------------------------------------------- #
def test_paint_circle_sets_mask():
    d = make_doc()
    assert not d.has_mask()
    d.paint_circle(34, 34, 5)
    assert d.has_mask()
    assert d.mask[34, 34] == 255


def test_paint_rect_fills_region():
    d = make_doc()
    d.paint_rect(28, 28, 39, 39)
    assert d.mask[28:40, 28:40].all()
    assert d.mask[0, 0] == 0


def test_erase_removes_from_mask():
    d = make_doc()
    d.paint_circle(34, 34, 8)
    d.erase_circle(34, 34, 8)
    assert not d.has_mask()


def test_paint_line_is_thick_and_connected():
    d = make_doc()
    d.paint_line(5, 5, 30, 30, radius=3)
    assert d.mask[5, 5] == 255 and d.mask[30, 30] == 255
    assert d.mask[17, 17] == 255          # somewhere along the stroke


# -- clean via engine ------------------------------------------------------- #
def test_apply_clean_removes_mark_and_preserves_outside():
    d = make_doc()
    before = d.image.copy()
    d.paint_rect(28, 28, 39, 39)
    mask = d.mask.copy()
    assert d.apply_clean(method="telea") is True

    sel = mask > 0
    assert np.array_equal(before[:, :, :3][~sel], d.image[:, :, :3][~sel])
    assert np.array_equal(before[:, :, 3], d.image[:, :, 3])    # alpha kept
    produced = set(map(tuple, d.image[:, :, :3][sel].reshape(-1, 3).tolist()))
    assert (255, 0, 255) not in produced
    assert not d.has_mask()               # mask reset after a clean


def test_apply_clean_noop_without_mask():
    d = make_doc()
    assert d.apply_clean() is False
    assert not d.can_undo()


# -- undo / redo ------------------------------------------------------------ #
def test_undo_redo_roundtrip():
    d = make_doc()
    original = d.image.copy()
    d.paint_rect(28, 28, 39, 39)
    d.apply_clean(method="telea")
    cleaned = d.image.copy()

    assert d.can_undo()
    assert d.undo() is True
    assert np.array_equal(d.image, original)
    assert d.can_redo()
    assert d.redo() is True
    assert np.array_equal(d.image, cleaned)


def test_undo_empty_is_safe():
    d = make_doc()
    assert d.undo() is False
    assert d.redo() is False


def test_new_edit_clears_redo():
    d = make_doc()
    d.paint_rect(28, 28, 39, 39)
    d.apply_clean(method="telea")
    d.undo()
    assert d.can_redo()
    d.paint_circle(5, 5, 3)
    d.apply_clean(method="telea")
    assert not d.can_redo()                # a fresh edit invalidates redo


def test_history_is_bounded():
    d = make_doc()
    for _ in range(app_core.Document.MAX_HISTORY + 10):
        d.paint_circle(20, 20, 2)
        d.apply_clean(method="telea")
    assert len(d._undo) <= app_core.Document.MAX_HISTORY


# -- save ------------------------------------------------------------------- #
def test_save_writes_file_and_preserves_alpha(tmp_path):
    d = make_doc()
    d.paint_rect(28, 28, 39, 39)
    d.apply_clean(method="telea")
    out = tmp_path / "out.png"
    d.save(str(out))
    assert out.exists()
    reread = app_core.load_image(out)
    assert reread.shape == (40, 40, 4)
    assert not d.dirty


def test_save_without_path_raises():
    d = make_doc()
    with pytest.raises(ValueError):
        d.save()


def test_open_missing_file_raises(tmp_path):
    with pytest.raises(IOError):
        app_core.Document.open(tmp_path / "nope.png")


# -- overlay (display preview) ---------------------------------------------- #
def test_overlay_tints_only_masked_area():
    d = make_doc()
    d.paint_rect(28, 28, 39, 39)
    vis = d.overlay()
    assert vis.shape == (40, 40, 3)
    # masked area shifted toward the tint colour; unmasked area unchanged
    base_bgr, _ = engine.split_alpha(d.image)
    assert np.array_equal(vis[0:10, 0:10], base_bgr[0:10, 0:10])
    assert not np.array_equal(vis[30, 30], base_bgr[30, 30])
