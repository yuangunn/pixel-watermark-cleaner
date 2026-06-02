"""Headless tests for the picker's geometry/state engine (picker_core).

These cover the math that the Tkinter shell relies on -- fitting, coordinate
mapping, drag normalisation, hit-testing, undo/clear, and absolute/relative
output -- with no display required. The thin widget layer in picker.py is
exercised separately (and only renders); all real logic lives here.
"""
import pytest

import picker_core as pc


# -- fitting / scaling ------------------------------------------------------ #
def test_fit_scale_never_upscales():
    assert pc.fit_scale(100, 100, 500, 500) == 1.0


def test_fit_scale_downscales_to_limiting_dim():
    # 1000x500 into 400x400 -> width limits -> 0.4
    assert pc.fit_scale(1000, 500, 400, 400) == pytest.approx(0.4)


def test_fit_scale_degenerate_sizes_are_safe():
    assert pc.fit_scale(0, 0, 100, 100) == 1.0
    assert pc.fit_scale(10, 10, 0, 0) > 0


def test_view_size_rounds_and_floors_at_one():
    assert pc.view_size(1000, 500, 0.4) == (400, 200)
    assert pc.view_size(1, 1, 0.001) == (1, 1)


# -- coordinate mapping ----------------------------------------------------- #
def test_canvas_to_image_inverts_scale_and_clamps():
    assert pc.canvas_to_image(20, 10, 0.5, 100, 100) == (40, 20)
    # out-of-bounds canvas point clamps into the image
    assert pc.canvas_to_image(10_000, 10_000, 0.5, 100, 100) == (99, 99)
    assert pc.canvas_to_image(-5, -5, 0.5, 100, 100) == (0, 0)


def test_image_to_canvas_applies_scale():
    assert pc.image_to_canvas(40, 20, 0.5) == (20.0, 10.0)


# -- rectangle helpers ------------------------------------------------------ #
@pytest.mark.parametrize("pts,expected", [
    ((10, 10, 30, 40), (10, 10, 20, 30)),   # already ordered
    ((30, 40, 10, 10), (10, 10, 20, 30)),   # reversed corners
    ((30, 10, 10, 40), (10, 10, 20, 30)),   # mixed
])
def test_normalize_rect(pts, expected):
    assert pc.normalize_rect(*pts) == expected


def test_clamp_rect_clips_to_image():
    assert pc.clamp_rect((90, 90, 50, 50), 100, 100) == (90, 90, 10, 10)


def test_clamp_rect_returns_none_when_empty():
    assert pc.clamp_rect((100, 100, 10, 10), 100, 100) is None
    assert pc.clamp_rect((5, 5, 0, 0), 100, 100) is None


def test_point_in_rect():
    r = (10, 10, 20, 20)
    assert pc.point_in_rect(15, 15, r)
    assert pc.point_in_rect(10, 10, r)        # on the edge counts
    assert not pc.point_in_rect(31, 31, r)


def test_relative_absolute_roundtrip():
    rect = (25, 40, 50, 20)
    rel = pc.to_relative(rect, 100, 80)
    assert rel == (0.25, 0.5, 0.5, 0.25)
    assert pc.to_absolute(rel, 100, 80) == rect


# -- PickerState ------------------------------------------------------------ #
def test_state_initial_regions_are_clamped():
    s = pc.PickerState(100, 100, 1000, 1000,
                       initial=[(10, 10, 20, 20), (90, 90, 50, 50)])
    assert s.regions == [(10, 10, 20, 20), (90, 90, 10, 10)]


def test_state_add_drag_commits_clamped_region():
    s = pc.PickerState(100, 100, 1000, 1000)
    r = s.add_drag(30, 40, 10, 10)            # reversed corners
    assert r == (10, 10, 20, 30)
    assert s.regions == [(10, 10, 20, 30)]


def test_state_add_drag_ignores_tiny_rect():
    s = pc.PickerState(100, 100, 1000, 1000)
    assert s.add_drag(10, 10, 11, 11) is None  # below MIN_SIZE
    assert s.regions == []


def test_state_hit_returns_topmost():
    s = pc.PickerState(100, 100, 1000, 1000)
    s.add_drag(0, 0, 50, 50)
    s.add_drag(10, 10, 40, 40)                 # drawn later -> on top
    assert s.hit(20, 20) == 1
    assert s.hit(5, 5) == 0                     # only the first covers here
    assert s.hit(99, 99) is None


def test_state_remove_and_undo_and_clear():
    s = pc.PickerState(100, 100, 1000, 1000)
    s.add_drag(0, 0, 30, 30)
    s.add_drag(50, 50, 80, 80)
    assert s.remove_at(60, 60) is True
    assert len(s.regions) == 1
    assert s.remove_at(99, 99) is False
    assert s.pop_last() == (0, 0, 30, 30)
    assert s.pop_last() is None                 # empty undo is safe
    s.add_drag(0, 0, 20, 20)
    s.clear()
    assert s.regions == []


def test_state_result_absolute_and_relative():
    s = pc.PickerState(100, 80, 1000, 1000)
    s.add_drag(25, 40, 75, 60)
    assert s.result() == [[25, 40, 50, 20]]
    assert s.result(relative=True) == [[0.25, 0.5, 0.5, 0.25]]


def test_state_scale_and_mapping_consistent():
    s = pc.PickerState(1000, 500, 400, 400)    # scale 0.4
    assert s.scale == pytest.approx(0.4)
    assert s.view_size() == (400, 200)
    # a canvas click at the view centre maps to the image centre
    assert s.to_image(200, 100) == (500, 250)
