"""Regression tests that lock the documented, verified behaviour of clean.py.

Fixtures are synthesised in code (no binary blobs in the repo). The locked
invariants are:

* pixels outside the (dilated) mask are byte-for-byte identical to the input
* the alpha channel is passed through untouched
* every pixel inside the mask is changed (high-contrast fill, dilate=0)
* --corner + --box resolves to the right rectangle in every corner
* --palette-match only ever emits colours that already exist in the source
* the original input file is never modified
"""
from argparse import Namespace

import cv2
import numpy as np
import pytest

import clean


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def region_ns(**kw):
    """A minimal Namespace good enough for clean.resolve_region(s)."""
    base = dict(region=None, regions=None, corner=None, box=None,
                margin=[0, 0], relative=False)
    base.update(kw)
    return Namespace(**base)


def make_bgra(path, h=64, w=64):
    """A BGRA asset: a few flat content colours, a per-pixel alpha ramp (varies
    even under the mark), and a bright magenta 16x16 watermark anchored in the
    bottom-right corner (exactly what ``--corner br --box 16 16`` masks)."""
    img = np.zeros((h, w, 4), np.uint8)
    img[:, :, 0] = 200
    img[:, :, 1] = 120
    img[:, :, 2] = 40
    img[10:20, :, :3] = (30, 220, 90)
    img[40:50, :, :3] = (10, 10, 230)
    img[:, :, 3] = (np.add.outer(np.arange(h), np.arange(w)) % 256).astype(np.uint8)
    img[h - 16:h, w - 16:w, :3] = (255, 0, 255)
    assert cv2.imwrite(str(path), img)
    return img


def make_flat_bgr(path, h=48, w=48):
    """Uniform background with a high-contrast watermark block in the corner, so
    inpainting is guaranteed to change every masked pixel."""
    img = np.empty((h, w, 3), np.uint8)
    img[:] = (120, 60, 30)
    img[h - 12:h, w - 12:w] = (0, 255, 255)
    assert cv2.imwrite(str(path), img)
    return img


def read(path):
    return cv2.imread(str(path), cv2.IMREAD_UNCHANGED)


# --------------------------------------------------------------------------- #
# (a) lossless outside the mask  +  (b) alpha preserved
# --------------------------------------------------------------------------- #
def test_outside_mask_is_byte_identical_and_alpha_preserved(tmp_path):
    src = tmp_path / "in" / "a.png"
    src.parent.mkdir()
    make_bgra(src)
    out = tmp_path / "out"

    rc = clean.main([str(src), "--out", str(out),
                     "--corner", "br", "--box", "16", "16", "--dilate", "2"])
    assert rc == 0

    o, r = read(src), read(out / "a.png")
    assert o.shape == r.shape == (64, 64, 4)

    region = clean.resolve_region(region_ns(corner="br", box=[16, 16]),
                                  o.shape[1], o.shape[0])
    mask = clean.build_mask(o.shape, region, dilate=2)
    outside = mask == 0

    # (a) every pixel the tool did not touch is identical, channel for channel
    assert np.array_equal(o[:, :, :3][outside], r[:, :, :3][outside])
    # (b) alpha is identical everywhere, including under the inpainted region
    assert np.array_equal(o[:, :, 3], r[:, :, 3])


def test_grayscale_input_without_alpha_runs(tmp_path):
    src = tmp_path / "in" / "g.png"
    src.parent.mkdir()
    g = np.full((40, 40), 128, np.uint8)
    g[28:40, 28:40] = 255
    assert cv2.imwrite(str(src), g)

    rc = clean.main([str(src), "--out", str(tmp_path / "out"),
                     "--corner", "br", "--box", "12", "12"])
    assert rc == 0
    assert (tmp_path / "out" / "g.png").exists()


# --------------------------------------------------------------------------- #
# (c) corner + box geometry
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("corner,box,margin,w,h,expected", [
    ("tl", [20, 10], [5, 5], 100, 80, (5, 5, 20, 10)),
    ("tr", [20, 10], [5, 5], 100, 80, (75, 5, 20, 10)),
    ("bl", [20, 10], [5, 5], 100, 80, (5, 65, 20, 10)),
    ("br", [20, 10], [5, 5], 100, 80, (75, 65, 20, 10)),
    ("br", [20, 10], [0, 0], 100, 80, (80, 70, 20, 10)),
    ("br", [32, 32], [4, 4], 100, 80, (64, 44, 32, 32)),
])
def test_resolve_region_corners(corner, box, margin, w, h, expected):
    args = region_ns(corner=corner, box=box, margin=margin)
    assert clean.resolve_region(args, w, h) == expected


def test_explicit_region_passthrough():
    args = region_ns(region=[3, 7, 11, 13])
    assert clean.resolve_region(args, 100, 100) == (3, 7, 11, 13)


def test_missing_region_raises():
    with pytest.raises(SystemExit):
        clean.resolve_region(region_ns(), 100, 100)


def test_build_mask_clamps_to_bounds():
    # a box hanging off the bottom-right must not raise and must stay in-frame
    mask = clean.build_mask((20, 20), (15, 15, 10, 10), dilate=0)
    assert mask.shape == (20, 20)
    assert mask[15:, 15:].all() and mask[:15, :15].sum() == 0


# --------------------------------------------------------------------------- #
# (d) palette-match only emits existing colours
# --------------------------------------------------------------------------- #
def test_palette_match_uses_only_existing_colours(tmp_path):
    src = tmp_path / "in" / "a.png"
    src.parent.mkdir()
    make_bgra(src)
    out = tmp_path / "out"

    rc = clean.main([str(src), "--out", str(out), "--corner", "br",
                     "--box", "16", "16", "--palette-match", "--max-colors", "8"])
    assert rc == 0

    o = read(src)[:, :, :3]
    r = read(out / "a.png")[:, :, :3]
    region = clean.resolve_region(region_ns(corner="br", box=[16, 16]),
                                  o.shape[1], o.shape[0])
    mask = clean.build_mask(o.shape, region, dilate=0)

    # the contract: regenerated pixels snap to colours that exist OUTSIDE the
    # mask in the original image -- never an invented (e.g. averaged) colour.
    allowed = set(map(tuple, o[mask == 0].reshape(-1, 3).tolist()))
    produced = set(map(tuple, r[mask > 0].reshape(-1, 3).tolist()))
    assert produced <= allowed
    assert (255, 0, 255) not in produced       # the watermark colour is gone


def test_build_palette_caps_to_max_colors():
    bgr = np.arange(6, dtype=np.uint8).repeat(3).reshape(1, 6, 3)
    mask = np.zeros((1, 6), np.uint8)          # nothing masked -> whole row is source
    assert len(clean.build_palette(bgr, mask, max_colors=3)) == 3


def test_snap_to_palette_picks_nearest():
    palette = np.array([[0, 0, 0], [255, 255, 255]], np.uint8)
    pixels = np.array([[10, 10, 10], [200, 200, 200]], np.uint8)
    out = clean.snap_to_palette(pixels, palette)
    assert np.array_equal(out, np.array([[0, 0, 0], [255, 255, 255]], np.uint8))


# --------------------------------------------------------------------------- #
# every masked pixel changes (high-contrast fill, dilate=0)
# --------------------------------------------------------------------------- #
def test_every_masked_pixel_changes(tmp_path):
    src = tmp_path / "in" / "f.png"
    src.parent.mkdir()
    make_flat_bgr(src)
    out = tmp_path / "out"

    rc = clean.main([str(src), "--out", str(out),
                     "--corner", "br", "--box", "12", "12"])
    assert rc == 0

    o, r = read(src), read(out / "f.png")
    region = clean.resolve_region(region_ns(corner="br", box=[12, 12]),
                                  o.shape[1], o.shape[0])
    mask = clean.build_mask(o.shape, region, dilate=0)
    inside = mask > 0
    changed = np.any(o[inside].reshape(-1, 3) != r[inside].reshape(-1, 3), axis=1)
    assert changed.all()


# --------------------------------------------------------------------------- #
# originals are never modified; preview is non-destructive
# --------------------------------------------------------------------------- #
def test_original_file_is_never_modified(tmp_path):
    src = tmp_path / "in" / "a.png"
    src.parent.mkdir()
    make_bgra(src)
    before = src.read_bytes()

    clean.main([str(src), "--out", str(tmp_path / "out"),
                "--corner", "br", "--box", "16", "16"])

    assert src.read_bytes() == before


def test_refuses_to_overwrite_original(tmp_path):
    src = tmp_path / "a.png"
    make_bgra(src)
    before = src.read_bytes()

    # out dir == the dir holding the source -> dst would equal src
    rc = clean.main([str(src), "--out", str(tmp_path),
                     "--corner", "br", "--box", "16", "16"])
    assert rc == 0                       # skipped, not an error
    assert src.read_bytes() == before


def test_preview_writes_overlay_without_inpainting(tmp_path):
    src = tmp_path / "in" / "a.png"
    src.parent.mkdir()
    make_bgra(src)
    out = tmp_path / "out"

    rc = clean.main([str(src), "--out", str(out), "--corner", "br",
                     "--box", "16", "16", "--preview"])
    assert rc == 0
    r = read(out / "a.png")
    assert r.shape == (64, 64, 4)        # alpha kept in preview too
    # preview must NOT inpaint: the magenta watermark is still present
    assert np.any(np.all(r[:, :, :3] == (255, 0, 255), axis=-1))


# --------------------------------------------------------------------------- #
# folder traversal
# --------------------------------------------------------------------------- #
def test_recursive_preserves_subfolder_layout(tmp_path):
    root = tmp_path / "in"
    (root / "sub").mkdir(parents=True)
    make_bgra(root / "top.png")
    make_bgra(root / "sub" / "nested.png")
    out = tmp_path / "out"

    rc = clean.main([str(root), "--out", str(out), "--recursive",
                     "--corner", "br", "--box", "16", "16"])
    assert rc == 0
    assert (out / "top.png").exists()
    assert (out / "sub" / "nested.png").exists()


def test_non_recursive_skips_subfolders(tmp_path):
    root = tmp_path / "in"
    (root / "sub").mkdir(parents=True)
    make_bgra(root / "top.png")
    make_bgra(root / "sub" / "nested.png")
    out = tmp_path / "out"

    clean.main([str(root), "--out", str(out),
                "--corner", "br", "--box", "16", "16"])
    assert (out / "top.png").exists()
    assert not (out / "sub" / "nested.png").exists()


# --------------------------------------------------------------------------- #
# --config seeds defaults; explicit CLI flags still win
# --------------------------------------------------------------------------- #
def test_config_seeds_defaults_and_cli_overrides(tmp_path):
    import json
    cfg = tmp_path / "wm.json"
    cfg.write_text(json.dumps({"corner": "br", "box": [16, 16], "method": "ns"}))

    a = clean.parse_args(["x.png", "--config", str(cfg)])
    assert a.corner == "br" and a.box == [16, 16] and a.method == "ns"

    a2 = clean.parse_args(["x.png", "--config", str(cfg),
                           "--box", "8", "8", "--method", "telea"])
    assert a2.box == [8, 8]              # CLI wins
    assert a2.method == "telea"          # CLI wins
    assert a2.corner == "br"             # still from config


def test_config_rejects_unknown_keys(tmp_path):
    cfg = tmp_path / "bad.json"
    cfg.write_text('{"regon": [1, 2, 3, 4]}')
    with pytest.raises(SystemExit):
        clean.parse_args(["x.png", "--config", str(cfg)])


def test_config_dashed_keys_are_accepted(tmp_path):
    import json
    cfg = tmp_path / "d.json"
    cfg.write_text(json.dumps({"palette-match": True, "max-colors": 12}))
    a = clean.parse_args(["x.png", "--region", "0", "0", "4", "4",
                          "--config", str(cfg)])
    assert a.palette_match is True
    assert a.max_colors == 12


# --------------------------------------------------------------------------- #
# multiple regions
# --------------------------------------------------------------------------- #
def make_two_marks(path, h=64, w=64):
    """Magenta mark in the br corner, yellow mark in the tl corner."""
    img = np.zeros((h, w, 4), np.uint8)
    img[:, :, 0] = 200
    img[:, :, 1] = 120
    img[:, :, 2] = 40
    img[:, :, 3] = (np.add.outer(np.arange(h), np.arange(w)) % 256).astype(np.uint8)
    img[h - 16:h, w - 16:w, :3] = (255, 0, 255)
    img[0:12, 0:12, :3] = (255, 255, 0)
    assert cv2.imwrite(str(path), img)
    return img


def test_resolve_regions_list():
    args = region_ns(regions=[[48, 48, 16, 16], [0, 0, 12, 12]])
    assert clean.resolve_regions(args, 64, 64) == [(48, 48, 16, 16), (0, 0, 12, 12)]


def test_resolve_regions_single_region_wrapped():
    args = region_ns(region=[3, 7, 11, 13])
    assert clean.resolve_regions(args, 100, 100) == [(3, 7, 11, 13)]


def test_resolve_regions_relative_scales_with_size():
    args = region_ns(regions=[[0.75, 0.75, 0.25, 0.25]], relative=True)
    assert clean.resolve_regions(args, 64, 64) == [(48, 48, 16, 16)]
    assert clean.resolve_regions(args, 128, 128) == [(96, 96, 32, 32)]


def test_build_mask_unions_multiple_regions():
    mask = clean.build_mask((64, 64), [(48, 48, 16, 16), (0, 0, 12, 12)], dilate=0)
    assert mask[48:64, 48:64].all()
    assert mask[0:12, 0:12].all()
    assert mask[30, 30] == 0                  # untouched middle


def test_two_marks_both_removed_outside_lossless(tmp_path):
    src = tmp_path / "in" / "two.png"
    src.parent.mkdir()
    make_two_marks(src)
    out = tmp_path / "out"

    rc = clean.main([str(src), "--out", str(out),
                     "--regions", "[[48,48,16,16],[0,0,12,12]]"])
    assert rc == 0

    o = read(src)
    r = read(out / "two.png")
    mask = clean.build_mask(o.shape, [(48, 48, 16, 16), (0, 0, 12, 12)], 0)
    outside = mask == 0
    produced = set(map(tuple, r[mask > 0][:, :3].tolist()))
    assert (255, 0, 255) not in produced       # magenta gone
    assert (255, 255, 0) not in produced       # yellow gone
    assert np.array_equal(o[:, :, :3][outside], r[:, :, :3][outside])
    assert np.array_equal(o[:, :, 3], r[:, :, 3])


# --------------------------------------------------------------------------- #
# config save round-trips back into a working run
# --------------------------------------------------------------------------- #
def test_save_config_roundtrip(tmp_path):
    import json
    args = region_ns(regions=[[48, 48, 16, 16], [0, 0, 12, 12]],
                     method="ns", radius=4, dilate=2,
                     palette_match=True, max_colors=8)
    cfg = tmp_path / "picked.json"
    clean.save_config(args, str(cfg))

    data = json.loads(cfg.read_text())
    assert data["regions"] == [[48, 48, 16, 16], [0, 0, 12, 12]]
    assert data["method"] == "ns" and data["dilate"] == 2
    assert data["palette-match"] is True

    # the saved file must parse straight back into a usable namespace
    reloaded = clean.parse_args(["img.png", "--config", str(cfg)])
    assert reloaded.regions == [[48, 48, 16, 16], [0, 0, 12, 12]]
    assert reloaded.method == "ns"


def test_save_config_creates_missing_parent_dirs(tmp_path):
    args = region_ns(regions=[[1, 2, 3, 4]], method="telea", radius=3,
                     dilate=0, palette_match=False, max_colors=16)
    cfg = tmp_path / "nested" / "deeper" / "wm.json"
    clean.save_config(args, str(cfg))         # parent dirs don't exist yet
    assert cfg.exists()


def test_save_config_relative_flag(tmp_path):
    import json
    args = region_ns(regions=[[0.75, 0.75, 0.25, 0.25]], relative=True,
                     method="telea", radius=3, dilate=0,
                     palette_match=False, max_colors=16)
    cfg = tmp_path / "rel.json"
    clean.save_config(args, str(cfg))
    data = json.loads(cfg.read_text())
    assert data["relative"] is True
    assert data["regions"] == [[0.75, 0.75, 0.25, 0.25]]


def test_dry_run_writes_nothing(tmp_path):
    src = tmp_path / "in" / "a.png"
    src.parent.mkdir()
    make_bgra(src)
    out = tmp_path / "out"

    rc = clean.main([str(src), "--out", str(out), "--region", "48", "48",
                     "16", "16", "--dry-run"])
    assert rc == 0
    assert not out.exists()                    # nothing written
