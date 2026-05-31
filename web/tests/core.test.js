/**
 * Node tests for the browser image core. No DOM, no OpenCV: the inpaint step is
 * faked, so these lock the same invariants the Python engine guarantees.
 *
 * Run: node --test web/tests/
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as core from '../core.js';

const W = 20, H = 20;

// A BGRA-agnostic RGBA fixture: solid teal, opaque, with a magenta block.
function fixture(w = W, h = H) {
  const rgba = new Uint8ClampedArray(w * h * 4);
  for (let i = 0; i < w * h; i++) {
    rgba[i * 4] = 40; rgba[i * 4 + 1] = 160; rgba[i * 4 + 2] = 160; rgba[i * 4 + 3] = 255;
  }
  for (let y = h - 6; y < h; y++)
    for (let x = w - 6; x < w; x++) {
      const i = y * w + x;
      rgba[i * 4] = 255; rgba[i * 4 + 1] = 0; rgba[i * 4 + 2] = 255;
    }
  return rgba;
}

function blockMask(w = W, h = H) {
  const m = core.emptyMask(w, h);
  core.paintRect(m, w, h, w - 6, h - 6, w - 1, h - 1);
  return m;
}

// Fake inpaint: paints the whole image solid grey (so we can see exactly which
// pixels the pipeline lets through into the result).
const GREY = 77;
const fakeInpaint = (rgba, w, h) => {
  const out = new Uint8Array(w * h * 3);
  out.fill(GREY);
  return out;
};

test('paintRect / paintCircle set the mask; emptyMask is empty', () => {
  const m = core.emptyMask(W, H);
  assert.equal(core.hasMask(m), false);
  core.paintCircle(m, W, H, 10, 10, 3);
  assert.equal(core.hasMask(m), true);
  assert.equal(m[10 * W + 10], 255);
});

test('eraseCircle clears mask pixels', () => {
  const m = core.emptyMask(W, H);
  core.paintCircle(m, W, H, 10, 10, 4);
  core.eraseCircle(m, W, H, 10, 10, 4);
  assert.equal(core.hasMask(m), false);
});

test('paintLine is connected', () => {
  const m = core.emptyMask(W, H);
  core.paintLine(m, W, H, 2, 2, 17, 17, 1);
  assert.equal(m[2 * W + 2], 255);
  assert.equal(m[17 * W + 17], 255);
  assert.equal(m[9 * W + 9], 255);     // somewhere along the diagonal
});

test('dilate grows the selection', () => {
  const m = blockMask();
  const grown = core.dilate(m, W, H, 2);
  const count = (a) => a.reduce((n, v) => n + (v ? 1 : 0), 0);
  assert.ok(count(grown) > count(m));
});

test('outside mask is byte-for-byte identical; alpha preserved', () => {
  const rgba = fixture();
  const mask = blockMask();
  const out = core.cleanRGBA(rgba, mask, W, H, { method: 'telea' }, fakeInpaint);
  for (let i = 0; i < W * H; i++) {
    if (!mask[i]) {
      assert.equal(out[i * 4], rgba[i * 4]);
      assert.equal(out[i * 4 + 1], rgba[i * 4 + 1]);
      assert.equal(out[i * 4 + 2], rgba[i * 4 + 2]);
    }
    assert.equal(out[i * 4 + 3], rgba[i * 4 + 3], 'alpha must be preserved');
  }
});

test('masked pixels are replaced by the inpaint output', () => {
  const rgba = fixture();
  const mask = blockMask();
  const out = core.cleanRGBA(rgba, mask, W, H, { method: 'telea' }, fakeInpaint);
  for (let i = 0; i < W * H; i++) {
    if (mask[i]) {
      assert.equal(out[i * 4], GREY);
      assert.equal(out[i * 4 + 1], GREY);
      assert.equal(out[i * 4 + 2], GREY);
    }
  }
});

test('empty mask leaves the image untouched', () => {
  const rgba = fixture();
  const out = core.cleanRGBA(rgba, core.emptyMask(W, H), W, H, {}, fakeInpaint);
  assert.deepEqual(out, Uint8ClampedArray.from(rgba));
});

test('dilate in cleanRGBA changes strictly more pixels', () => {
  const rgba = fixture();
  const mask = blockMask();
  const base = core.cleanRGBA(rgba, mask, W, H, { dilate: 0 }, fakeInpaint);
  const grown = core.cleanRGBA(rgba, mask, W, H, { dilate: 3 }, fakeInpaint);
  const changed = (o) => {
    let n = 0;
    for (let i = 0; i < W * H; i++)
      if (o[i * 4] !== rgba[i * 4] || o[i * 4 + 1] !== rgba[i * 4 + 1] || o[i * 4 + 2] !== rgba[i * 4 + 2]) n++;
    return n;
  };
  assert.ok(changed(grown) > changed(base));
});

test('palette-match only emits colours present outside the mask', () => {
  const rgba = fixture();
  const mask = blockMask();
  const out = core.cleanRGBA(rgba, mask, W, H,
    { method: 'telea', paletteMatch: true, maxColors: 8 }, fakeInpaint);
  const allowed = new Set();
  for (let i = 0; i < W * H; i++)
    if (!mask[i]) allowed.add(`${rgba[i * 4]},${rgba[i * 4 + 1]},${rgba[i * 4 + 2]}`);
  for (let i = 0; i < W * H; i++)
    if (mask[i]) {
      const key = `${out[i * 4]},${out[i * 4 + 1]},${out[i * 4 + 2]}`;
      assert.ok(allowed.has(key), `produced ${key} not in source`);
    }
});

test('buildPalette ignores masked pixels (never includes the watermark colour)', () => {
  const rgba = fixture();
  const mask = blockMask();
  const pal = core.buildPalette(rgba, mask, W, H, 16);
  assert.ok(!pal.some((c) => c[0] === 255 && c[1] === 0 && c[2] === 255));
});

test('overlay tints only masked pixels', () => {
  const rgba = fixture();
  const mask = blockMask();
  const vis = core.overlay(rgba, mask, W, H);
  // an unmasked pixel is unchanged; a masked one shifts toward red (its blue
  // channel drops -- the watermark is magenta, so red alone wouldn't change)
  assert.equal(vis[0], rgba[0]);
  const i = (H - 1) * W + (W - 1);
  assert.notEqual(vis[i * 4 + 2], rgba[i * 4 + 2]);
});
