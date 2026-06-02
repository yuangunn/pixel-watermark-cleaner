# pixel-watermark-cleaner (`pwc`)

Regenerate **visible** watermarks on generated images by painting over them and
inpainting just that area — the surrounding content is rebuilt, so the artwork
underneath survives. Built for **pixel-art game assets**, where the mark sits on
top of real content (clothing, weapons, scabbards) and cropping or flat-fill
would wreck it.

Four ways to use it, same approach underneath:

- 🌐 **Web app / PWA** (`web/`) — runs **in the browser**, desktop *and mobile*,
  no install and no upload. Works offline after first load. Batch-cleans many
  same-size images from one mask. (OpenCV.js / WebAssembly.)
- 🖱️ **Desktop app** (`pwc-app`) — open an image, **brush or box** over the
  watermark, click **Clean**, **Save**. Paint-style, Undo/Redo. Prebuilt
  executables are on the [Releases](../../releases) page (no Python needed).
- 🎯 **Batch picker** (`pwc … --pick`) — draw the region once on a sample image,
  then clean a whole folder with those coordinates.
- ⌨️ **Headless CLI** (`pwc`) — give coordinates directly / via a JSON config;
  ideal for scripts and CI.

## Intended use & responsible use

A tool for **regenerating watermarks on images you have the right to edit** —
primarily your own AI-generated game assets, where a visible mark sits on top of
artwork you created and want to keep.

**✅ Use it for**

- Cleaning visible watermarks/marks from assets **you own or created**.
- Your own AI-generated images — where *you* remain responsible for any required
  "AI-generated" disclosure. Removing a visible watermark does **not** remove
  that obligation.

**🚫 Don't use it for**

- Removing watermarks, signatures, or copyright marks from content you **don't
  own or aren't licensed to edit** (stock photos, other artists' work, etc.).
- Stripping a provider's watermark to bypass licensing or paywalls.
- Removing or altering **copyright-management information** to misrepresent
  authorship or to facilitate infringement.

### Scope — what it touches

- It **only** regenerates the area you point it at; every other pixel (and the
  alpha channel) is byte-for-byte unchanged.
- It does **not** detect or remove invisible, image-wide provenance signals
  (e.g. SynthID). Those are out of scope and untouched.
- Originals are **never** overwritten — you save to a new file / output folder.

> **Disclaimer.** This software is provided "as is" under the MIT License, with
> no warranty of any kind. You are solely responsible for ensuring you have the
> right to modify any image you process, and for complying with applicable laws
> (including copyright and DMCA §1202 regarding copyright-management information)
> and any third-party terms. The authors accept no liability for misuse.

## Get it

**Prebuilt app (easiest):** download the executable for your OS from
[Releases](../../releases) and run it. Windows `.exe`, macOS, and Linux builds
are produced automatically.

**From source:**

```bash
pip install -e .            # installs pwc, pwc-pick, and the pwc-app GUI
```

Core dependencies are intentionally light: **OpenCV + numpy** only. The GUI/
picker also need **Tkinter**, which ships with CPython but on Linux is a
separate OS package:

```bash
sudo apt install python3-tk        # Debian/Ubuntu
sudo dnf install python3-tkinter   # Fedora
# macOS / Windows: use the python.org installer (Tk included)
```

## Desktop app

```bash
pwc-app              # or:  python app.py [image]
```

1. **Open** an image.
2. Pick **Brush** (paint freely) or **Box** (drag a rectangle) and cover the
   watermark. Right-drag erases; `[` / `]` resize the brush.
3. Choose the **Engine** (`telea`/`ns`, or `lama` if installed), optionally
   **Grow** the selection a few px to catch a glow, and **Palette** to snap to
   existing colours.
4. **Clean ▶** regenerates just the painted pixels. **Undo**/**Redo** as needed.
5. **Save As** — defaults to `name_cleaned.png` and warns before overwriting the
   original.

| Shortcut | |
| --- | --- |
| `Ctrl-Z` / `Ctrl-Y` | undo / redo |
| `Enter` | clean |
| `Ctrl-S` | save as |
| `[` / `]` | brush smaller / larger |

### Higher-quality inpainting (optional)

The default OpenCV backend is tiny and instant, great for flat pixel-art. For
busier images you can opt into **LaMa**, a deep-learning inpainter (closer to
"generative erase"). It's a heavy, separate install (pulls in PyTorch) and is
**not** bundled in the prebuilt app:

```bash
pip install -e ".[ml]"     # adds torch + simple-lama-inpainting
```

Then pick `lama` as the engine in the app, or `--method lama` on the CLI. The
first run downloads the model weights.

## Web app (offline, in the browser)

A zero-install version that runs **entirely client-side** — desktop *and mobile*
browsers, no server, no upload. After the first load it works **offline** and is
installable as a PWA. It uses OpenCV.js (WebAssembly) for the same Telea/NS
inpainting; the heavier LaMa backend is desktop/server-only.

Run locally (a service worker needs `http://`, not `file://`, so serve it):

```bash
cd web
python3 -m http.server 8000      # then open http://localhost:8000
```

Or host the `web/` folder on any static host (GitHub Pages, Netlify, …).

**Batch:** drop in several images of the **same size** with the watermark in the
**same spot**, paint the mask once, and **Clean all & download** runs every image
(one file downloads directly; several are zipped). Brush / Box / Erase,
adjustable size, palette-snap, and grow are all there, and it's touch-friendly.

The image logic lives in `web/core.js` (pure, unit-tested under Node, mirroring
the Python engine's invariants); `web/engine.js` is the OpenCV.js glue. OpenCV.js
and JSZip are **vendored** (`web/vendor/`), so there's no third-party CDN
dependency. Deploy `web/` to any static host — an included Pages workflow
(`.github/workflows/pages.yml`) publishes it on push to `main` once Pages is
enabled (private repos need a paid plan).

## Batch: draw the region once, clean the whole folder

For many same-layout images, skip the per-image app. A window opens on the first
image; drag a box (or several) over the watermark(s), press **Enter**, and every
image in the folder is cleaned with those coordinates:

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

## Architecture

| Module | Role |
| --- | --- |
| `engine.py` | the one inpainting entry point (`clean_image(img, mask, …)`); alpha handling, palette snap, cv2 + optional LaMa backends. Both UIs call this. |
| `clean.py` | batch CLI (`pwc`) — input discovery, region geometry, config. |
| `picker.py` / `picker_core.py` | batch region picker (`pwc-pick`); core is the headless geometry/state. |
| `app.py` / `app_core.py` | desktop app (`pwc-app`); core is the headless document model (mask, undo/redo, save). |

Keeping the engine and every UI's logic in headless cores means the locked
invariants are asserted once and the Tkinter layers stay thin.

## Development

```bash
pip install -e ".[dev]"
pytest -q                       # 78 headless tests
```

The geometry, document model, and engine are fully unit-tested without a
display. The thin Tkinter layers are exercised by `tests/gui_smoke.py` — which
builds the real window, paints with mouse events, and runs clean/undo/save —
which CI runs under a virtual framebuffer (Xvfb). Tests synthesise their
fixtures in code, so there are no binary assets in the repo.

## Building executables

The release workflow builds standalone apps with PyInstaller on each OS and
attaches them to a GitHub Release when you push a `v*` tag. To build locally:

```bash
pip install -e ".[build]"
pyinstaller packaging/pwc-app.spec     # -> dist/pwc-app(.exe)
```

## License

MIT — see [LICENSE](LICENSE).

### Third-party components

- **OpenCV** (`opencv-python-headless`) — Apache-2.0
- **NumPy** — BSD-3-Clause
- Optional `[ml]` backend: **PyTorch** (BSD-3-Clause) and **LaMa** via
  `simple-lama-inpainting`. The LaMa model weights are downloaded at runtime and
  carry their **own license** (review it before commercial use); they are **not**
  redistributed in this repository or bundled in the prebuilt app.
- Prebuilt executables are produced with **PyInstaller**, whose bootloader has a
  GPL-with-exception that permits distributing bundled apps under any license.
