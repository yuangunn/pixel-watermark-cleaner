"""Tests for the shared inpainting engine.

The engine is the single source of truth both the CLI and the GUI rely on, so
the locked invariants are asserted here directly against the mask-based API:

  * pixels outside the mask are byte-for-byte identical to the input
  * the alpha channel is passed through untouched
  * an empty mask leaves the image completely unchanged
  * masked pixels are regenerated (and a covering mask removes the mark)
  * palette-match only ever emits colours already present in the source
"""
import numpy as np
import pytest

import engine


def bgra_with_mark(h=40, w=40):
    img = np.zeros((h, w, 4), np.uint8)
    img[:, :, 0] = 200
    img[:, :, 1] = 120
    img[:, :, 2] = 40
    img[:, :, 3] = (np.add.outer(np.arange(h), np.arange(w)) % 256).astype(np.uint8)
    img[h - 12:h, w - 12:w, :3] = (255, 0, 255)        # magenta watermark
    return img


def block_mask(h=40, w=40):
    m = np.zeros((h, w), np.uint8)
    m[h - 12:h, w - 12:w] = 255
    return m


# -- channel handling ------------------------------------------------------- #
def test_split_merge_roundtrip_bgra():
    img = bgra_with_mark()
    color, alpha = engine.split_alpha(img)
    assert color.shape == (40, 40, 3)
    assert alpha is not None
    assert np.array_equal(engine.merge_alpha(color, alpha), img)


def test_split_alpha_none_for_plain_bgr():
    img = np.zeros((8, 8, 3), np.uint8)
    color, alpha = engine.split_alpha(img)
    assert alpha is None
    assert np.array_equal(color, img)


# -- core invariants -------------------------------------------------------- #
def test_outside_mask_identical_and_alpha_preserved():
    img = bgra_with_mark()
    mask = block_mask()
    out = engine.clean_image(img, mask, method="telea")
    sel = mask > 0
    assert np.array_equal(img[:, :, :3][~sel], out[:, :, :3][~sel])
    assert np.array_equal(img[:, :, 3], out[:, :, 3])


def test_covering_mask_removes_the_mark():
    img = bgra_with_mark()
    out = engine.clean_image(img, block_mask(), method="telea")
    produced = set(map(tuple, out[block_mask() > 0][:, :3].tolist()))
    assert (255, 0, 255) not in produced


def test_empty_mask_leaves_image_untouched():
    img = bgra_with_mark()
    out = engine.clean_image(img, np.zeros((40, 40), np.uint8))
    assert np.array_equal(out, img)


def test_dilate_expands_selection():
    img = bgra_with_mark()
    mask = block_mask()
    base = engine.clean_image(img, mask, method="telea", dilate=0)
    grown = engine.clean_image(img, mask, method="telea", dilate=3)
    # the dilated run changes strictly more pixels than the plain one
    changed_base = np.any(img[:, :, :3] != base[:, :, :3], axis=2).sum()
    changed_grown = np.any(img[:, :, :3] != grown[:, :, :3], axis=2).sum()
    assert changed_grown > changed_base


def test_mask_shape_mismatch_raises():
    img = bgra_with_mark()
    with pytest.raises(ValueError):
        engine.clean_image(img, np.zeros((10, 10), np.uint8))


def test_non_binary_mask_is_thresholded():
    img = bgra_with_mark()
    soft = block_mask().astype(np.uint8)
    soft[soft > 0] = 7                                  # tiny non-zero values
    out = engine.clean_image(img, soft, method="telea")
    # 7 still counts as "selected": the mark is regenerated
    produced = set(map(tuple, out[block_mask() > 0][:, :3].tolist()))
    assert (255, 0, 255) not in produced


# -- palette match ---------------------------------------------------------- #
def test_palette_match_only_uses_existing_colours():
    img = bgra_with_mark()
    mask = block_mask()
    out = engine.clean_image(img, mask, method="telea",
                             palette_match=True, max_colors=8)
    allowed = set(map(tuple, img[:, :, :3][mask == 0].reshape(-1, 3).tolist()))
    produced = set(map(tuple, out[:, :, :3][mask > 0].reshape(-1, 3).tolist()))
    assert produced <= allowed


# -- backend discovery ------------------------------------------------------ #
def test_available_methods_always_has_cv2():
    methods = engine.available_methods()
    assert "telea" in methods and "ns" in methods


def test_unknown_method_raises():
    img = bgra_with_mark()
    with pytest.raises(ValueError):
        engine.clean_image(img, block_mask(), method="nope")


def test_lama_method_errors_cleanly_when_unavailable():
    if engine.lama_available():
        pytest.skip("LaMa is installed in this environment")
    img = bgra_with_mark()
    with pytest.raises(Exception):
        engine.clean_image(img, block_mask(), method="lama")
