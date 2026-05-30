#!/usr/bin/env python3
"""pixel-watermark-cleaner (pwc)

Batch CLI that regenerates a *visible* watermark sitting inside a known
rectangular region of generated images, using local inpainting
(OpenCV's cv2.inpaint). Built for pixel-art game assets where the mark lies
on top of real content (clothing, weapons, scabbards, ...), so cropping or
flat-fill would destroy the artwork -- inpainting rebuilds plausible pixels.

Scope (by design):
  * Only the rectangle you point at is regenerated.
  * Invisible, image-wide provenance signals (e.g. SynthID) are NOT detected
    or removed. This tool does not touch them.
  * Originals are never overwritten; output always goes to a separate folder.
  * Intended for assets you have the rights to edit, with AI-generated
    disclosure kept intact.

Dependencies are intentionally light: opencv + numpy only.
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

SUPPORTED_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
INPAINT_FLAGS = {"telea": cv2.INPAINT_TELEA, "ns": cv2.INPAINT_NS}


# --------------------------------------------------------------------------- #
# argument parsing (+ optional --config that seeds defaults)
# --------------------------------------------------------------------------- #
def load_config(path):
    """Load CLI defaults from a JSON object (e.g. a fixed watermark region)."""
    try:
        with open(path) as f:
            data = json.load(f)
    except OSError as e:
        raise SystemExit(f"error: cannot read config {path}: {e}")
    except json.JSONDecodeError as e:
        raise SystemExit(f"error: invalid JSON in config {path}: {e}")
    if not isinstance(data, dict):
        raise SystemExit(f"error: config {path} must be a JSON object")
    return data


def parse_args(argv=None):
    # Pre-scan --config with a throwaway parser so its values can seed defaults;
    # explicit CLI flags still win (set_defaults only changes the *defaults*).
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config")
    cfg_ns, _ = pre.parse_known_args(argv)

    p = argparse.ArgumentParser(
        prog="pwc",
        description="Regenerate a visible watermark region via local inpainting.",
    )
    p.add_argument("inputs", nargs="+", help="input image file(s) or folder(s)")
    p.add_argument("--out", default="./cleaned", help="output directory")
    p.add_argument("--config",
                   help="JSON file of default options (e.g. a fixed region)")

    # region: either an explicit rectangle, or a corner + box (+ margin)
    p.add_argument("--region", nargs=4, type=int, metavar=("X", "Y", "W", "H"),
                   help="explicit watermark rectangle")
    p.add_argument("--corner", choices=["br", "bl", "tr", "tl"],
                   help="anchor a box in this corner")
    p.add_argument("--box", nargs=2, type=int, metavar=("W", "H"),
                   help="box size for --corner")
    p.add_argument("--margin", nargs=2, type=int, default=[0, 0],
                   metavar=("MX", "MY"), help="inset of the box from the corner")

    # inpainting
    p.add_argument("--method", choices=["telea", "ns"], default="telea",
                   help="cv2.inpaint algorithm (default: telea)")
    p.add_argument("--radius", type=int, default=3,
                   help="inpaint radius in px (default: 3)")
    p.add_argument("--dilate", type=int, default=0,
                   help="grow the mask by ~N px to swallow a semi-transparent "
                        "glow/halo around the mark (default: 0)")

    # post-processing / modes
    p.add_argument("--palette-match", action="store_true",
                   help="snap regenerated pixels to colours already present "
                        "in the image (good for flat pixel-art palettes)")
    p.add_argument("--max-colors", type=int, default=16,
                   help="cap the matched palette to its N most common colours "
                        "(default: 16; <=0 means no cap)")
    p.add_argument("--preview", action="store_true",
                   help="don't inpaint; just save a copy with the region "
                        "outlined, to check coordinates")
    p.add_argument("--recursive", action="store_true",
                   help="recurse into input folders")

    if cfg_ns.config:
        cfg = load_config(cfg_ns.config)
        valid = {a.dest for a in p._actions}
        seeded = {k.replace("-", "_"): v for k, v in cfg.items()}
        unknown = sorted(set(seeded) - valid)
        if unknown:
            raise SystemExit("error: unknown config keys: " + ", ".join(unknown))
        p.set_defaults(**{k: v for k, v in seeded.items() if k != "config"})

    return p.parse_args(argv)


# --------------------------------------------------------------------------- #
# geometry
# --------------------------------------------------------------------------- #
def resolve_region(args, w, h):
    """Return (x, y, rw, rh) for the watermark rectangle (pure geometry; not
    clamped to the image -- build_mask clamps when rasterising)."""
    if args.region:
        x, y, rw, rh = args.region
        return (x, y, rw, rh)
    if args.corner and args.box:
        bw, bh = args.box
        mx, my = args.margin
        x = mx if args.corner in ("tl", "bl") else w - bw - mx
        y = my if args.corner in ("tl", "tr") else h - bh - my
        return (x, y, bw, bh)
    raise SystemExit(
        "error: specify the region with --region X Y W H, "
        "or --corner {br,bl,tr,tl} --box W H [--margin MX MY]")


def build_mask(shape, region, dilate):
    """Binary uint8 mask (255 = inpaint). Clamped to the image bounds. With
    ``dilate`` > 0 the rectangle grows by ~dilate px in every direction."""
    h, w = shape[:2]
    x, y, rw, rh = region
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(w, x + rw), min(h, y + rh)
    mask = np.zeros((h, w), np.uint8)
    if x1 > x0 and y1 > y0:
        mask[y0:y1, x0:x1] = 255
    if dilate > 0:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                      (2 * dilate + 1, 2 * dilate + 1))
        mask = cv2.dilate(mask, k)
    return mask


# --------------------------------------------------------------------------- #
# channels: keep alpha completely out of the inpaint path
# --------------------------------------------------------------------------- #
def split_alpha(img):
    """Return (colour, alpha). Alpha is None when the image has none. The
    colour array is a contiguous copy ready for cv2.inpaint (1 or 3 channels)."""
    if img.ndim == 3 and img.shape[2] == 4:        # BGRA
        return np.ascontiguousarray(img[:, :, :3]), img[:, :, 3].copy()
    if img.ndim == 3 and img.shape[2] == 2:        # gray + alpha
        return np.ascontiguousarray(img[:, :, 0]), img[:, :, 1].copy()
    return img.copy(), None


def merge_alpha(color, alpha):
    if alpha is None:
        return color
    return np.dstack([color, alpha])


# --------------------------------------------------------------------------- #
# palette matching (snap to colours that already exist in the source)
# --------------------------------------------------------------------------- #
def build_palette(color, mask, max_colors):
    """Colours present *outside* the mask (the real content), optionally capped
    to the ``max_colors`` most frequent. Every entry truly occurs in the
    source, so snapping to it can never invent a colour."""
    src = color[mask == 0]
    if src.size == 0:                              # mask covers everything
        src = color.reshape(-1, color.shape[-1]) if color.ndim == 3 \
            else color.reshape(-1)
    src = src.reshape(len(src), -1)
    colors, counts = np.unique(src, axis=0, return_counts=True)
    if 0 < max_colors < len(colors):
        colors = colors[np.argsort(counts)[::-1][:max_colors]]
    return colors


def snap_to_palette(pixels, palette):
    """Snap each pixel (N, C) to its nearest palette colour (Euclidean)."""
    p = pixels.astype(np.int32)[:, None, :]        # (N, 1, C)
    pal = palette.astype(np.int32)[None, :, :]     # (1, K, C)
    idx = ((p - pal) ** 2).sum(axis=2).argmin(axis=1)
    return palette[idx]


# --------------------------------------------------------------------------- #
# core
# --------------------------------------------------------------------------- #
def process_image(img, args, region):
    """Inpaint the masked rectangle and composite it back over the untouched
    original. Pixels outside the mask, and the alpha channel, are preserved
    byte-for-byte."""
    color, alpha = split_alpha(img)
    mask = build_mask(color.shape, region, args.dilate)
    painted = cv2.inpaint(color, mask, args.radius, INPAINT_FLAGS[args.method])

    m = mask > 0
    sel = painted[m]
    if args.palette_match and sel.size:
        palette = build_palette(color, mask, args.max_colors)
        snapped = snap_to_palette(sel.reshape(len(sel), -1), palette)
        sel = snapped.reshape(sel.shape)

    out = color.copy()
    out[m] = sel
    return merge_alpha(out, alpha)


def draw_preview(img, region):
    """A copy of the image with the region outlined (no inpainting)."""
    color, alpha = split_alpha(img)
    x, y, rw, rh = region
    vis = color.copy()
    c = (0, 0, 255) if vis.ndim == 3 else 255      # red box, or white on gray
    cv2.rectangle(vis, (x, y), (x + rw - 1, y + rh - 1), c, 1)
    return merge_alpha(vis, alpha)


# --------------------------------------------------------------------------- #
# input discovery / output
# --------------------------------------------------------------------------- #
def iter_inputs(inputs, recursive):
    """Yield (source_path, relative_output_path) for every supported image."""
    for inp in inputs:
        p = Path(inp)
        if p.is_dir():
            walk = p.rglob("*") if recursive else p.glob("*")
            for f in sorted(walk):
                if f.is_file() and f.suffix.lower() in SUPPORTED_EXTS:
                    yield f, f.relative_to(p)
        elif p.is_file():
            yield p, Path(p.name)
        else:
            print(f"warning: not found, skipping: {p}", file=sys.stderr)


def run(args):
    out_root = Path(args.out)
    processed = skipped = failed = 0

    for src, rel in iter_inputs(args.inputs, args.recursive):
        dst = out_root / rel
        try:
            if dst.resolve() == src.resolve():
                print(f"refusing to overwrite original: {src}", file=sys.stderr)
                skipped += 1
                continue

            img = cv2.imread(str(src), cv2.IMREAD_UNCHANGED)
            if img is None:
                print(f"warning: cannot read image: {src}", file=sys.stderr)
                failed += 1
                continue

            region = resolve_region(args, img.shape[1], img.shape[0])
            result = draw_preview(img, region) if args.preview \
                else process_image(img, args, region)

            dst.parent.mkdir(parents=True, exist_ok=True)
            if not cv2.imwrite(str(dst), result):
                raise IOError("cv2.imwrite returned False")

            verb = "preview" if args.preview else "cleaned"
            print(f"{verb}: {src} -> {dst}")
            processed += 1
        except SystemExit:
            raise
        except Exception as e:                     # keep the batch going
            print(f"error processing {src}: {e}", file=sys.stderr)
            failed += 1

    print(f"\ndone: {processed} written, {skipped} skipped, {failed} failed")
    if processed == 0 and failed == 0 and skipped == 0:
        print("no supported images found in inputs", file=sys.stderr)
        return 1
    return 1 if failed else 0


def main(argv=None):
    return run(parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
