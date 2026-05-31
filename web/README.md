# pixel-watermark-cleaner — web app (offline PWA)

Runs entirely in the browser (desktop + mobile), no server, no upload. Offline
after first load; installable as a PWA. Uses OpenCV.js (WebAssembly) for the
same Telea/Navier-Stokes inpainting as the desktop app.

## Run

A service worker + ES modules need `http://` (not `file://`), so serve the
folder:

```bash
python3 -m http.server 8000      # then open http://localhost:8000
```

Any static host works too (GitHub Pages, Netlify, …) — it's just static files.

## Use

1. **Open…** or drop in one or many images.
2. **Brush / Box / Erase** over the watermark (size slider; `[` / `]` to resize;
   `Ctrl/Cmd+Z` to undo).
3. Optionally tune **Engine** (telea/ns), **Palette**, **Grow**.
4. **Preview** checks the result on the first image.
5. **Clean all & download** processes every loaded image with the same mask —
   one file downloads directly, several come back as `cleaned.zip`.

**Batch rule:** images must be the **same size** (same watermark position).
Differently-sized files are skipped with a notice.

## Files

| File | Role |
| --- | --- |
| `core.js` | pure image logic — mask ops, alpha, palette, composite, clean pipeline. No DOM/wasm; unit-tested under Node (`tests/`). |
| `engine.js` | OpenCV.js loader + inpaint glue (the injected inpaint for `core`). |
| `app.js` | UI controller: files, canvas painting (pointer/touch), preview, batch + ZIP. |
| `sw.js` | service worker — offline caching of the app shell + OpenCV.js/JSZip. |
| `index.html`, `styles.css` | minimal shell (visual design is intentionally plain — see `../docs/design-handoff.md`). |

## Notes

- OpenCV.js and JSZip load from a CDN and are then cached for offline use. For
  guaranteed first-load-offline, vendor `opencv.js` locally and point
  `OPENCV_URL` in `engine.js` at it.
- The LaMa (deep-learning) backend is **not** in the web build — it's
  desktop/server-only.

## Test

```bash
node --test 'web/tests/*.test.js'      # from the repo root
```
