# pixel-watermark-cleaner — Frontend Design Handoff

A spec sheet for redesigning the desktop app's UI. The pixel logic is **done and
frozen** in headless modules; this doc tells a designer exactly what the UI must
let a user do, what state exists, and which functions a new frontend binds to —
so the visual design can change freely while staying implementable.

- **Product:** a lightweight, "MS-Paint-light" desktop tool to remove a *visible*
  watermark from an image by selecting the spot and regenerating (inpainting) it.
- **Primary platform:** Windows (`.exe`); also macOS / Linux. Single window,
  offline, no account.
- **Reference screenshots:** the two "before select / after clean" captures
  shared in chat show the *current* Tkinter implementation. Treat them as the
  functional baseline, **not** a visual target.

---

## 1. Current layout (baseline wireframe)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ [Open] [Save As] │ (•)Brush ( )Box  Size[≡≡──] │ Engine[telea▾] □Palette       │   toolbar
│                                  Grow[2▲▼] │ [Clean ▶] [Undo] [Redo] [Clear]    │   (single row, wraps)
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│                         IMAGE CANVAS  (dark #202020 bg)                        │
│                   selection drawn as a translucent RED overlay                 │
│                                                                                │
├──────────────────────────────────────────────────────────────────────────────┤
│ cleaned    1140x780    tool:box    brush:14    engine:telea                    │   status bar
└──────────────────────────────────────────────────────────────────────────────┘
```

Three zones: **toolbar** (controls), **canvas** (image + selection overlay),
**status bar** (feedback). A redesign may reorganize these freely (side panel,
floating tools, ribbon, etc.) as long as every control below is reachable.

---

## 2. Component inventory

| # | Control | Type | Options / range | Default | What it does |
|---|---------|------|-----------------|---------|--------------|
| 1 | **Open** | button | — | — | File picker; loads an image into the canvas |
| 2 | **Save As** | button | — | — | Save result to a new file (see Save flow) |
| 3 | **Tool: Brush** | radio | — | selected | Freehand paint the selection mask |
| 4 | **Tool: Box** | radio | — | — | Drag a rectangle into the selection mask |
| 5 | **Size** | slider | 2–80 (px) | 14 | Brush / eraser radius (image pixels) |
| 6 | **Engine** | dropdown | `telea`, `ns`, `lama`* | `telea` | Inpainting algorithm |
| 7 | **Palette** | checkbox | on/off | off | Snap regenerated pixels to colours already in the image (pixel-art safe) |
| 8 | **Grow** | stepper | 0–20 (px) | 2 | Expand the selection outward before cleaning (catches glow/edges) |
| 9 | **Clean ▶** | button (primary) | — | — | Regenerate the selected area; clears the selection |
| 10 | **Undo** | button | — | — | Step back (history depth 30) |
| 11 | **Redo** | button | — | — | Step forward |
| 12 | **Clear** | button | — | — | Discard the current selection (does not change the image) |

\* `lama` (deep-learning, higher quality, slower) appears **only when the
optional ML backend is installed**. The UI must query availability, not assume.
*Not currently surfaced:* an inpaint `radius` (fixed at 3) — a redesign may
optionally expose it.

---

## 3. Screen states

| State | Canvas | Status text (current copy) | Enabled |
|-------|--------|----------------------------|---------|
| **Empty** (no image) | dark, blank | `Open an image to start.` | Open only |
| **Loaded** | image shown, no overlay | `opened {path}` then `{w}x{h}  tool:…  brush:…  engine:…` | all tools |
| **Selecting** | red overlay grows as user paints/drags | `selected watermark — press Clean` | Clean, Clear |
| **No selection + Clean pressed** | unchanged | `paint over the watermark first` | — |
| **Cleaning** (LaMa can be slow) | *(none today)* | *(none today)* | — |
| **Cleaned** | image updated, overlay gone | `cleaned` | Undo |
| **After Undo/Redo** | image swapped | `undo` / `redo` | Redo / Undo |
| **Error** (e.g. ML model fails to load) | unchanged | modal: title `Clean failed`, body = error | — |
| **Unsaved changes** | — | `dirty` flag is tracked | Save As |

> Design gaps worth filling: there is **no busy/progress state** and **no brush
> cursor preview** today — both are good additions (LaMa may take seconds).

---

## 4. Primary user flow

1. **Open** an image.
2. Choose **Brush** or **Box**; (optionally adjust **Size**).
3. Paint / drag over the watermark → red selection overlay appears.
   - Right-drag (or eraser) to subtract; **Clear** to reset selection.
4. (Optional) tune **Engine**, **Grow**, **Palette**.
5. **Clean ▶** → the selected pixels are regenerated; selection resets.
6. Repeat / **Undo** / **Redo** until satisfied.
7. **Save As** → new file (defaults to `name_cleaned.ext`; warns before
   overwriting the original).

---

## 5. Interaction map (current bindings — rebindable)

| Input | Action |
|-------|--------|
| Left press / drag | Brush: paint • Box: rubber-band rectangle |
| Right press / drag | Erase from selection |
| `Enter` | Clean |
| `Ctrl+Z` / `Ctrl+Y` | Undo / Redo |
| `Ctrl+S` | Save As |
| `[` / `]` | Brush smaller / larger |
| Mouse over canvas | crosshair cursor |

---

## 6. Copy & labels (current)

Buttons: `Open`, `Save As`, `Brush`, `Box`, `Size`, `Engine`, `Palette`,
`Grow`, `Clean ▶`, `Undo`, `Redo`, `Clear`.
Status messages: `Open an image to start.`, `opened {path}`,
`paint over the watermark first`, `selected watermark — press Clean`, `cleaned`,
`undo`, `redo`, `cleared selection`, `saved {path}`.
Dialogs: window title `pixel-watermark-cleaner`; overwrite prompt
`Overwrite original?` / `That's the original file. Overwrite it anyway?`; error
`Clean failed`.
All copy is open to rewriting/localization.

## 7. Current visual tokens (all flexible)

- Canvas background `#202020`; selection overlay **red** at ~45% opacity; box
  rubber-band outline `#23d18b` (dashed). Pixel-art images render
  **nearest-neighbour** (crisp, no blur). These are defaults, not requirements.

---

## 8. Functional contract — what a new frontend MUST call (fixed)

The UI is a thin shell over two headless, unit-tested modules. Build any
frontend (web, native, prettier Tk) against these and the pixel behaviour is
guaranteed.

### `app_core.Document` — per-image editing state
```
Document.open(path) -> Document          # load from disk (raises IOError)
Document(image, path=None)               # or wrap an existing array
  .image            # current pixels (numpy, see §9)
  .mask             # HxW uint8, 0 / 255 (the selection)
  .w, .h, .path, .dirty
  .paint_circle(x, y, radius)            # brush dab        (image-space coords)
  .paint_line(x0,y0,x1,y1, radius)       # smooth brush stroke
  .paint_rect(x0,y0,x1,y1)               # box select
  .erase_circle(x, y, radius)            # subtract from selection
  .clear_mask()      .has_mask() -> bool
  .apply_clean(method="telea", radius=3, dilate=0,
               palette_match=False, max_colors=16) -> bool   # False if no selection
  .undo() -> bool    .redo() -> bool     .can_undo()/.can_redo() -> bool
  .save(path) -> path                    # writes; refuses empty path
  .overlay(mask_color=(0,0,255), alpha=0.45) -> BGR array     # image + tinted selection, for display
  MAX_HISTORY = 30
module: load_image(path), save_image(path, img), SUPPORTED_READ
```

### `engine` — the pixel work (Document calls this; UI usually doesn't directly)
```
engine.clean_image(img, mask, method="telea", radius=3, dilate=0,
                   palette_match=False, max_colors=16) -> img
engine.available_methods() -> ["telea","ns"(,"lama")]   # drives the Engine dropdown
engine.lama_available() -> bool                          # is the ML backend installed?
engine.DEFAULT_METHOD = "telea"
```

### `picker_core` — canvas ↔ image coordinate mapping (for zoom/fit)
```
fit_scale(w, h, max_w, max_h) -> scale          # scale to fit image in a viewport
view_size(w, h, scale) -> (view_w, view_h)
canvas_to_image(cx, cy, scale, w, h) -> (ix, iy) # map a click back to image pixels
```
**Rule:** all selection coordinates passed to `Document` are **image pixels**.
The UI converts screen→image via `canvas_to_image` before calling paint/erase.

---

## 9. Data shapes & formats

- **Image:** numpy `uint8`, channel-last, **BGR(A)** order (OpenCV):
  `HxW` (gray), `HxWx2` (gray+alpha), `HxWx3` (BGR), `HxWx4` (BGRA).
- **Mask:** `HxW` `uint8`, `0` = keep, `255` = regenerate.
- **Coordinates:** image pixels, origin top-left.
- **Read formats:** `.png .jpg .jpeg .webp .bmp`. **Alpha (PNG transparency) is
  preserved** end-to-end. Save defaults to PNG.

---

## 10. Invariants (non-negotiable — the redesign must not break these)

1. Pixels **outside** the selection are byte-for-byte unchanged.
2. The **alpha channel** is preserved exactly.
3. The **original file is never overwritten** silently — saving goes to a new
   file; overwriting the source requires explicit confirmation.
4. It only regenerates the **user-selected area** — it does not auto-detect or
   touch invisible, image-wide provenance signals.
   (See the repo README "Intended use / responsible use".)

---

## 11. Fixed vs. free

| Fixed (functional) | Free (yours to design) |
|---|---|
| The 12 controls' *capabilities* (§2) | Their layout, grouping, icons, labels, theme |
| The operations & params (§8) | Toolbar vs side panel vs ribbon; light/dark; spacing |
| Data shapes, formats, invariants (§9–10) | Cursors, overlay colour/opacity, animations |
| Image-pixel coordinate rule (§8) | Zoom/pan, fit modes, minimap |

---

## 12. Enhancement opportunities (nice-to-have backlog for the designer)

- **Busy / progress** indicator for `lama` (can take seconds; model loads lazily).
- **Brush cursor preview** (circle sized to the brush) and a live size readout.
- **Zoom & pan** for large images (today it fit-scales to the window only).
- **Before/after** compare (toggle or slider).
- Adjustable **overlay opacity**; optional separate "mask view".
- Surface the inpaint **radius**; quick presets ("logo corner", "diagonal mark").
- An **empty state** with a drop-target ("Drop an image, or Open…").
- Optional **batch/folder** entry point (the engine + a region picker already
  support batch via the CLI).

---

## 13. Out of scope (don't design these)

- Removing watermarks from content the user doesn't own / isn't licensed to edit.
- Detecting or stripping invisible provenance/AI signals (e.g. SynthID).
- Cloud upload, accounts, or telemetry — this is a local, offline tool.
