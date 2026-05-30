#!/usr/bin/env python3
"""pixel-watermark-cleaner (pwc)

Batch CLI that regenerates *visible* watermark(s) sitting inside known
rectangular region(s) of generated images, using local inpainting
(OpenCV's cv2.inpaint). Built for pixel-art game assets where the mark lies
on top of real content (clothing, weapons, scabbards, ...), so cropping or
flat-fill would destroy the artwork -- inpainting rebuilds plausible pixels.

Region(s) can be given on the command line, loaded from a JSON config, or drawn
interactively with the region picker (``--pick`` / the ``pwc-pick`` command).

Scope (by design):
  * Only the rectangle(s) you point at are regenerated.
  * Invisible, image-wide provenance signals (e.g. SynthID) are NOT detected
    or removed. This tool does not touch them.
  * Originals are never overwritten; output always goes to a separate folder.
  * Intended for assets you have the rights to edit, with AI-generated
    disclosure kept intact.

Dependencies are intentionally light: opencv + numpy only. The interactive
picker additionally needs Tkinter (stdlib; system package ``python3-tk``).
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

import engine

SUPPORTED_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


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
        description="Regenerate visible watermark region(s) via local inpainting.",
    )
    p.add_argument("inputs", nargs="+", help="input image file(s) or folder(s)")
    p.add_argument("--out", default="./cleaned", help="output directory")
    p.add_argument("--config",
                   help="JSON file of default options (e.g. fixed region(s))")

    # region: explicit rectangle, corner + box, or a list of rectangles
    p.add_argument("--region", nargs=4, type=int, metavar=("X", "Y", "W", "H"),
                   help="explicit watermark rectangle")
    p.add_argument("--regions", type=json.loads, metavar="JSON",
                   help='multiple rectangles as JSON, e.g. "[[x,y,w,h],...]" '
                        "(usually supplied via --config or the picker)")
    p.add_argument("--corner", choices=["br", "bl", "tr", "tl"],
                   help="anchor a box in this corner")
    p.add_argument("--box", nargs=2, type=int, metavar=("W", "H"),
                   help="box size for --corner")
    p.add_argument("--margin", nargs=2, type=int, default=[0, 0],
                   metavar=("MX", "MY"), help="inset of the box from the corner")
    p.add_argument("--relative", action="store_true",
                   help="interpret region coords as fractions of width/height "
                        "(0..1), so one config fits images of different sizes")

    # inpainting
    p.add_argument("--method", choices=["telea", "ns", "lama"], default="telea",
                   help="inpaint backend: telea/ns (OpenCV, default) or lama "
                        "(deep learning, opt-in; needs the 'ml' extra)")
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
                   help="don't inpaint; just save a copy with the region(s) "
                        "outlined, to check coordinates")
    p.add_argument("--recursive", action="store_true",
                   help="recurse into input folders")

    # interactive selection
    p.add_argument("--pick", action="store_true",
                   help="draw the region(s) on a representative image first, "
                        "then apply them to the whole batch")
    p.add_argument("--pick-relative", action="store_true",
                   help="like --pick, but store coords as fractions (--relative)")
    p.add_argument("--max-view", nargs=2, type=int, default=[1280, 800],
                   metavar=("W", "H"), help="max picker window size in px")
    p.add_argument("--save-config", metavar="FILE",
                   help="write the chosen region(s)/settings to a JSON config")
    p.add_argument("--dry-run", action="store_true",
                   help="don't write outputs; just report what would happen")

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
    """Return a single (x, y, rw, rh) for --region or --corner/--box. Pure
    geometry; not clamped to the image -- build_mask clamps when rasterising."""
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


def resolve_regions(args, w, h):
    """Return a list of integer (x, y, rw, rh) rectangles for this image size.

    Priority: --regions (list) > --region (single) > --corner/--box. When
    ``args.relative`` is set, --regions/--region values are read as fractions of
    (w, h). Corner boxes are always absolute and recomputed per image size."""
    if getattr(args, "regions", None):
        raw = args.regions
    elif args.region:
        raw = [args.region]
    elif args.corner and args.box:
        return [resolve_region(args, w, h)]
    else:
        raise SystemExit(
            "error: no region given. Use --region / --corner+--box, a config "
            "with 'regions', or draw them with --pick.")

    relative = bool(getattr(args, "relative", False))
    out = []
    for r in raw:
        x, y, rw, rh = r
        if relative:
            x, y, rw, rh = x * w, y * h, rw * w, rh * h
        out.append((int(round(x)), int(round(y)),
                    int(round(rw)), int(round(rh))))
    return out


def _as_region_list(regions):
    """Accept either a single (x, y, w, h) or a list of them."""
    if len(regions) and isinstance(regions[0], (list, tuple, np.ndarray)):
        return list(regions)
    return [regions]


def build_mask(shape, regions, dilate):
    """Binary uint8 mask (255 = inpaint) for one or more rectangles, unioned and
    clamped to the image bounds. With ``dilate`` > 0 the result grows by
    ~dilate px in every direction."""
    h, w = shape[:2]
    mask = np.zeros((h, w), np.uint8)
    for x, y, rw, rh in _as_region_list(regions):
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(w, x + rw), min(h, y + rh)
        if x1 > x0 and y1 > y0:
            mask[y0:y1, x0:x1] = 255
    if dilate > 0:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                      (2 * dilate + 1, 2 * dilate + 1))
        mask = cv2.dilate(mask, k)
    return mask


# alpha / palette / inpainting all live in engine.py, the shared source of
# truth used by both this CLI and the GUI app. These re-exports keep the public
# names (and the tests that import them) working.
split_alpha = engine.split_alpha
merge_alpha = engine.merge_alpha
build_palette = engine.build_palette
snap_to_palette = engine.snap_to_palette


# --------------------------------------------------------------------------- #
# core
# --------------------------------------------------------------------------- #
def process_image(img, args, regions):
    """Inpaint the masked rectangle(s) and composite them back over the
    untouched original. Pixels outside the mask, and the alpha channel, are
    preserved byte-for-byte."""
    mask = build_mask(img.shape, regions, dilate=0)   # engine applies --dilate
    return engine.clean_image(img, mask,
                              method=args.method, radius=args.radius,
                              dilate=args.dilate,
                              palette_match=args.palette_match,
                              max_colors=args.max_colors)


def draw_preview(img, regions):
    """A copy of the image with the region(s) outlined (no inpainting)."""
    color, alpha = split_alpha(img)
    vis = color.copy()
    c = (0, 0, 255) if vis.ndim == 3 else 255      # red box, or white on gray
    for x, y, rw, rh in _as_region_list(regions):
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


def representative_image(inputs, recursive):
    """The first supported image among the inputs -- the one shown in --pick."""
    for src, _ in iter_inputs(inputs, recursive):
        return src
    return None


def save_config(args, path):
    """Persist the chosen region(s) and inpaint settings as a reusable config."""
    data = {
        "method": args.method,
        "radius": args.radius,
        "dilate": args.dilate,
        "palette-match": args.palette_match,
        "max-colors": args.max_colors,
    }
    if getattr(args, "regions", None):
        data["regions"] = [list(r) for r in args.regions]
        if getattr(args, "relative", False):
            data["relative"] = True
    elif args.region:
        data["region"] = list(args.region)
    elif args.corner and args.box:
        data["corner"] = args.corner
        data["box"] = list(args.box)
        data["margin"] = list(args.margin)
    p = Path(path)
    if p.parent and not p.parent.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def run(args):
    out_root = Path(args.out)
    processed = skipped = failed = 0
    first_size = None
    warned_size = False

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

            h, w = img.shape[:2]
            absolute = not getattr(args, "relative", False) and not (
                args.corner and args.box)
            if first_size is None:
                first_size = (w, h)
            elif absolute and (w, h) != first_size and not warned_size:
                print(f"warning: {src} is {w}x{h}, not {first_size[0]}x"
                      f"{first_size[1]}; fixed pixel coords may not line up. "
                      "Consider --pick-relative / 'relative' coords.",
                      file=sys.stderr)
                warned_size = True

            regions = resolve_regions(args, w, h)
            result = draw_preview(img, regions) if args.preview \
                else process_image(img, args, regions)

            if args.dry_run:
                print(f"would write: {src} -> {dst}  regions={regions}")
                processed += 1
                continue

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

    tail = " (dry run)" if args.dry_run else ""
    print(f"\ndone{tail}: {processed} written, {skipped} skipped, "
          f"{failed} failed")
    if processed == 0 and failed == 0 and skipped == 0:
        print("no supported images found in inputs", file=sys.stderr)
        return 1
    return 1 if failed else 0


def main(argv=None):
    args = parse_args(argv)

    if args.pick or args.pick_relative:
        from picker import pick_regions          # lazy: Tkinter only when needed
        rep = representative_image(args.inputs, args.recursive)
        if rep is None:
            print("no image to pick from", file=sys.stderr)
            return 1
        relative = args.pick_relative
        img = cv2.imread(str(rep), cv2.IMREAD_UNCHANGED)
        initial = []
        if img is not None and (getattr(args, "regions", None) or args.region):
            initial = resolve_regions(args, img.shape[1], img.shape[0])
        try:
            picked = pick_regions(str(rep), args.max_view[0], args.max_view[1],
                                  relative=relative, initial=initial)
        except ImportError as e:
            raise SystemExit(
                f"error: the region picker needs Tkinter ({e}). It ships with "
                "CPython but on Linux is a separate OS package: "
                "`sudo apt install python3-tk` (Debian/Ubuntu) or "
                "`sudo dnf install python3-tkinter` (Fedora). On macOS/Windows "
                "use the python.org installer. Or pass coordinates directly "
                "with --region / --regions / --config.")
        if not picked:
            print("no regions selected; nothing to do", file=sys.stderr)
            return 0
        args.regions = picked
        args.relative = relative
        print(f"selected {len(picked)} region(s) on {rep}")

    if args.save_config:
        save_config(args, args.save_config)
        print(f"saved config -> {args.save_config}")

    return run(args)


if __name__ == "__main__":
    sys.exit(main())
