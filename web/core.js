/**
 * Pure, dependency-free image core for the web app.
 *
 * Mirrors the Python `engine.py` invariants so the browser behaves identically:
 *   - pixels OUTSIDE the mask are byte-for-byte identical to the input
 *   - the alpha channel is preserved exactly
 *   - only masked pixels change
 *   - palette-match only ever emits colours already present in the source
 *
 * No DOM, no OpenCV here -- the actual inpaint is injected as a function, so
 * the whole clean/compose pipeline is unit-testable under Node. The browser
 * passes an OpenCV.js-backed inpaint (see engine.js); tests pass a fake.
 *
 * Conventions: RGBA is a Uint8(Clamped)Array of length w*h*4 (canvas order).
 * A mask is a Uint8Array of length w*h, 0 = keep, non-zero = regenerate.
 */

export function emptyMask(w, h) {
  return new Uint8Array(w * h);
}

export function hasMask(mask) {
  for (let i = 0; i < mask.length; i++) if (mask[i]) return true;
  return false;
}

// -- mask painting (image-space coords) ------------------------------------ //
export function paintCircle(mask, w, h, cx, cy, r, value = 255) {
  cx = Math.round(cx); cy = Math.round(cy); r = Math.max(1, Math.round(r));
  const r2 = r * r;
  for (let dy = -r; dy <= r; dy++) {
    const yy = cy + dy;
    if (yy < 0 || yy >= h) continue;
    for (let dx = -r; dx <= r; dx++) {
      const xx = cx + dx;
      if (xx < 0 || xx >= w) continue;
      if (dx * dx + dy * dy <= r2) mask[yy * w + xx] = value;
    }
  }
  return mask;
}

export function paintLine(mask, w, h, x0, y0, x1, y1, r, value = 255) {
  const dx = x1 - x0, dy = y1 - y0;
  const steps = Math.max(1, Math.ceil(Math.hypot(dx, dy)));
  for (let i = 0; i <= steps; i++) {
    const t = i / steps;
    paintCircle(mask, w, h, x0 + dx * t, y0 + dy * t, r, value);
  }
  return mask;
}

export function paintRect(mask, w, h, x0, y0, x1, y1, value = 255) {
  const xa = Math.max(0, Math.min(x0, x1) | 0);
  const xb = Math.min(w - 1, Math.max(x0, x1) | 0);
  const ya = Math.max(0, Math.min(y0, y1) | 0);
  const yb = Math.min(h - 1, Math.max(y0, y1) | 0);
  for (let y = ya; y <= yb; y++) {
    const row = y * w;
    for (let x = xa; x <= xb; x++) mask[row + x] = value;
  }
  return mask;
}

export function eraseCircle(mask, w, h, cx, cy, r) {
  return paintCircle(mask, w, h, cx, cy, r, 0);
}

/** Grow a binary mask by ~r px in each direction (separable square dilation). */
export function dilate(mask, w, h, r) {
  if (!r || r <= 0) return mask.slice();
  const tmp = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) {
    const row = y * w;
    for (let x = 0; x < w; x++) {
      let v = 0;
      for (let dx = -r; dx <= r && !v; dx++) {
        const xx = x + dx;
        if (xx >= 0 && xx < w && mask[row + xx]) v = 255;
      }
      tmp[row + x] = v;
    }
  }
  const out = new Uint8Array(w * h);
  for (let x = 0; x < w; x++) {
    for (let y = 0; y < h; y++) {
      let v = 0;
      for (let dy = -r; dy <= r && !v; dy++) {
        const yy = y + dy;
        if (yy >= 0 && yy < h && tmp[yy * w + x]) v = 255;
      }
      out[y * w + x] = v;
    }
  }
  return out;
}

// -- palette matching ------------------------------------------------------- //
/** Colours present OUTSIDE the mask, capped to the `maxColors` most frequent. */
export function buildPalette(rgba, mask, w, h, maxColors = 16) {
  const counts = new Map();
  for (let i = 0; i < w * h; i++) {
    if (mask[i]) continue;
    const key = (rgba[i * 4] << 16) | (rgba[i * 4 + 1] << 8) | rgba[i * 4 + 2];
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  let entries = [...counts.entries()];
  if (entries.length === 0) return [[0, 0, 0]];
  if (maxColors > 0 && entries.length > maxColors) {
    entries.sort((a, b) => b[1] - a[1]);
    entries = entries.slice(0, maxColors);
  }
  return entries.map(([key]) => [(key >> 16) & 255, (key >> 8) & 255, key & 255]);
}

export function snapToPalette(r, g, b, palette) {
  let best = palette[0], bestD = Infinity;
  for (const c of palette) {
    const d = (r - c[0]) ** 2 + (g - c[1]) ** 2 + (b - c[2]) ** 2;
    if (d < bestD) { bestD = d; best = c; }
  }
  return best;
}

// -- compose & clean -------------------------------------------------------- //
/**
 * Composite the inpainted RGB into the masked region of the original, keeping
 * everything else (and the whole alpha channel) byte-for-byte. `paintedRGB` is
 * a full-image Uint8Array of length w*h*3.
 */
export function composite(origRGBA, paintedRGB, mask, w, h, opts = {}) {
  const out = Uint8ClampedArray.from(origRGBA);   // copy: alpha + outside kept
  let palette = null;
  if (opts.paletteMatch) palette = buildPalette(origRGBA, mask, w, h, opts.maxColors || 16);
  for (let i = 0; i < w * h; i++) {
    if (!mask[i]) continue;
    let r = paintedRGB[i * 3], g = paintedRGB[i * 3 + 1], b = paintedRGB[i * 3 + 2];
    if (palette) { const s = snapToPalette(r, g, b, palette); r = s[0]; g = s[1]; b = s[2]; }
    out[i * 4] = r; out[i * 4 + 1] = g; out[i * 4 + 2] = b;
    // out[i*4+3] (alpha) deliberately untouched
  }
  return out;
}

/**
 * Full clean pipeline. `inpaint(rgba, w, h, mask, opts) -> Uint8Array(w*h*3)`
 * is injected (OpenCV.js in the browser, a fake in tests). Returns new RGBA.
 */
export function cleanRGBA(rgba, mask, w, h, opts, inpaint) {
  const m = opts && opts.dilate > 0 ? dilate(mask, w, h, opts.dilate) : mask;
  if (!hasMask(m)) return Uint8ClampedArray.from(rgba);   // nothing selected
  const paintedRGB = inpaint(rgba, w, h, m, opts || {});
  return composite(rgba, paintedRGB, m, w, h, opts || {});
}

/** A display copy of the image with the mask tinted on top (for the canvas). */
export function overlay(rgba, mask, w, h, color = [255, 0, 0], alpha = 0.45) {
  const out = Uint8ClampedArray.from(rgba);
  for (let i = 0; i < w * h; i++) {
    if (!mask[i]) continue;
    out[i * 4] = out[i * 4] * (1 - alpha) + color[0] * alpha;
    out[i * 4 + 1] = out[i * 4 + 1] * (1 - alpha) + color[1] * alpha;
    out[i * 4 + 2] = out[i * 4 + 2] * (1 - alpha) + color[2] * alpha;
  }
  return out;
}
