# pixel-watermark-cleaner (`pwc`)

A batch CLI that regenerates a **visible** watermark sitting inside a known
rectangular region of generated images, using local inpainting
(`cv2.inpaint`). Built for **pixel-art game assets**, where the mark is overlaid
on real content — clothing, weapons, scabbards — so cropping or flat-fill would
wreck the artwork. Inpainting rebuilds plausible pixels from the surrounding
content instead.

## Scope

This tool **only** regenerates the rectangle you point it at.

- It does **not** detect or remove invisible, image-wide provenance signals
  (e.g. SynthID). Those are out of scope and untouched.
- It is meant for assets **you have the right to edit**, and it assumes you keep
  any required "AI-generated" disclosure intact. Removing a visible watermark
  does not remove the obligation to disclose AI generation where that applies.
- Originals are **never** overwritten — output always goes to a separate folder.

## Install

```bash
pip install -e .          # installs the `pwc` command
# or, just the runtime deps, then run via python:
pip install -r requirements.txt
```

Core dependencies are intentionally light: **OpenCV + numpy** only.

## Usage

```bash
# Point at a corner-anchored box (most common for a fixed watermark):
pwc assets/ --out cleaned/ --recursive --corner br --box 40 16 --margin 4 4

# Or give an explicit rectangle:
pwc hero.png --out cleaned/ --region 210 230 40 16

# Without installing:
python clean.py hero.png --corner br --box 40 16
```

Output mirrors the input layout under `--out` (default `./cleaned`).

### Region

Two ways to specify the watermark rectangle:

| Option | Meaning |
| --- | --- |
| `--region X Y W H` | explicit rectangle (top-left origin) |
| `--corner {br,bl,tr,tl}` + `--box W H` + `--margin MX MY` | a `W×H` box inset by `(MX, MY)` from the chosen corner |

### Inpainting

| Option | Default | Meaning |
| --- | --- | --- |
| `--method {telea,ns}` | `telea` | `cv2.inpaint` algorithm |
| `--radius N` | `3` | inpaint radius in px |
| `--dilate N` | `0` | grow the mask by ~N px to swallow a semi-transparent glow/halo around the mark |

### Pixel-art helpers

| Option | Default | Meaning |
| --- | --- | --- |
| `--palette-match` | off | snap regenerated pixels to colours **already present** in the image — never invents a new colour |
| `--max-colors N` | `16` | cap the matched palette to its N most common colours (`<=0` = no cap) |

### Other

| Option | Meaning |
| --- | --- |
| `--preview` | don't inpaint; save a copy with the region outlined, to check coordinates |
| `--recursive` | recurse into input folders |
| `--config FILE` | load defaults from a JSON file (see below) |

### Fixed coordinates with `--config`

If your watermark is always in the same place, stop retyping coordinates: put
them in a JSON file and pass `--config`. Keys are the long option names (dashes
or underscores both work). **Explicit CLI flags always override the config.**

```jsonc
// watermark.example.json
{
  "corner": "br",
  "box": [40, 16],
  "margin": [4, 4],
  "method": "telea",
  "radius": 3,
  "dilate": 2,
  "palette-match": true,
  "max-colors": 16
}
```

```bash
pwc assets/ --recursive --config watermark.example.json
pwc assets/ --recursive --config watermark.example.json --dilate 4   # override one value
```

## Guarantees (locked by tests)

- Pixels **outside** the (dilated) mask are byte-for-byte identical to the input.
- The **alpha channel** is passed through untouched (input == output).
- Every pixel **inside** the mask is regenerated.
- With `--palette-match`, regenerated pixels only ever use colours that already
  exist elsewhere in the image.
- The original file is never modified.

Supported formats: `png`, `jpg`/`jpeg`, `webp`, `bmp`. PNG alpha is preserved.

## Development

```bash
pip install -e ".[dev]"
pytest -q
```

Tests synthesise their fixtures in code, so there are no binary assets in the
repo. CI runs `pytest` on every push and pull request.

## License

MIT — see [LICENSE](LICENSE).
