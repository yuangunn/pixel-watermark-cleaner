# pixel-watermark-cleaner (`pwc`)

A batch CLI that regenerates **visible** watermark(s) sitting inside known
rectangular region(s) of generated images, using local inpainting
(`cv2.inpaint`). Built for **pixel-art game assets**, where the mark is overlaid
on real content — clothing, weapons, scabbards — so cropping or flat-fill would
wreck the artwork. Inpainting rebuilds plausible pixels from the surrounding
content instead.

You can point at the region(s) on the command line, store them in a JSON config,
or **draw them on a representative image** and apply them across the whole batch.

## Scope

This tool **only** regenerates the rectangle(s) you point it at.

- It does **not** detect or remove invisible, image-wide provenance signals
  (e.g. SynthID). Those are out of scope and untouched.
- It is meant for assets **you have the right to edit**, and it assumes you keep
  any required "AI-generated" disclosure intact. Removing a visible watermark
  does not remove the obligation to disclose AI generation where that applies.
- Originals are **never** overwritten — output always goes to a separate folder.

## Install

```bash
pip install -e .            # installs the `pwc` and `pwc-pick` commands
# or, just the runtime deps, then run via python:
pip install -r requirements.txt
```

Core dependencies are intentionally light: **OpenCV + numpy** only. The
interactive picker also needs **Tkinter**, which ships with CPython but on Linux
is a separate OS package:

```bash
sudo apt install python3-tk        # Debian/Ubuntu
sudo dnf install python3-tkinter   # Fedora
# macOS / Windows: use the python.org installer (Tk included)
```

## Quick start — draw the region, clean the batch

The fastest way. A window opens on the first image in your input; drag a box (or
several) over the watermark(s), press **Enter**, and every image is cleaned with
those coordinates:

```bash
pwc assets/ --out cleaned/ --recursive --pick
```

Add `--save-config wm.json` to remember the coordinates, then next time skip the
window entirely:

```bash
pwc assets/ --out cleaned/ --recursive --config wm.json
```

If your images differ in size, pick in **relative** mode so the box scales to
each image:

```bash
pwc assets/ --out cleaned/ --recursive --pick-relative --save-config wm.json
```

### Picker controls

| Input | Action |
| --- | --- |
| Left-drag | draw a selection rectangle |
| Right-click | delete the rectangle under the cursor |
| `u` / `Ctrl-Z` | undo the last rectangle |
| `c` | clear all |
| `Enter` | confirm and clean |
| `Esc` / `q` | cancel |

`pwc-pick IMAGE` runs the picker standalone and prints the regions as JSON (with
`--save-config` to write a config), handy for scripting.

## Usage without the picker

```bash
# Corner-anchored box (most common for one fixed watermark):
pwc assets/ --out cleaned/ --recursive --corner br --box 40 16 --margin 4 4

# Explicit rectangle:
pwc hero.png --out cleaned/ --region 210 230 40 16

# Several rectangles at once:
pwc hero.png --out cleaned/ --regions "[[210,230,40,16],[0,0,32,12]]"

# Without installing:
python clean.py hero.png --corner br --box 40 16
```

Output mirrors the input layout under `--out` (default `./cleaned`).

### Region

| Option | Meaning |
| --- | --- |
| `--region X Y W H` | one explicit rectangle (top-left origin) |
| `--regions "[[x,y,w,h],…]"` | several rectangles as JSON |
| `--corner {br,bl,tr,tl}` + `--box W H` + `--margin MX MY` | a `W×H` box inset by `(MX, MY)` from a corner |
| `--relative` | read region coords as fractions of width/height (0..1) so one config fits different image sizes |

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

### Workflow / modes

| Option | Meaning |
| --- | --- |
| `--pick` / `--pick-relative` | draw region(s) on a representative image, then apply to the whole batch |
| `--save-config FILE` | write the chosen region(s) + settings to a JSON config |
| `--config FILE` | load defaults from a JSON config (CLI flags still override) |
| `--preview` | don't inpaint; save a copy with the region(s) outlined, to check coordinates |
| `--dry-run` | don't write anything; just report what would happen |
| `--recursive` | recurse into input folders |
| `--max-view W H` | cap the picker window size (default `1280 800`) |

### Config file

Keys are the long option names (dashes or underscores both work). **Explicit CLI
flags always override the config.**

```jsonc
// wm.json  (e.g. produced by --save-config)
{
  "regions": [[210, 230, 40, 16], [0, 0, 32, 12]],
  "method": "telea",
  "radius": 3,
  "dilate": 2,
  "palette-match": true,
  "max-colors": 16
}
```

```bash
pwc assets/ --recursive --config wm.json
pwc assets/ --recursive --config wm.json --dilate 4   # override one value
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

The picker's geometry/state engine (`picker_core.py`) is fully unit-tested
headlessly. The thin Tkinter widget layer (`picker.py`) is exercised separately
by `tests/gui_smoke.py`, which CI runs under a virtual framebuffer (Xvfb). Tests
synthesise their fixtures in code, so there are no binary assets in the repo.

## License

MIT — see [LICENSE](LICENSE).
