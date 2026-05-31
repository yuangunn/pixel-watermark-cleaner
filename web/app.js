/**
 * UI controller for the pixel-watermark-cleaner PWA.
 *
 * Thin layer over core.js (pure, tested) and engine.js (OpenCV.js). Handles
 * file loading, canvas painting (pointer events -> works with touch on mobile),
 * a preview on the reference image, and batch cleaning of many same-size images
 * with one shared mask -> ZIP download. Visual design is deliberately minimal
 * (see docs/design-handoff.md).
 */
import * as core from './core.js';
import { loadOpenCv, inpaintFactory } from './engine.js';

const JSZIP_URL = 'https://cdn.jsdelivr.net/npm/jszip@3.10.1/dist/jszip.min.js';

const $ = (id) => document.getElementById(id);
const el = {
  toolbar: $('toolbar'), files: $('files'), files2: $('files2'),
  size: $('size'), method: $('method'), palette: $('palette'), grow: $('grow'),
  preview: $('preview'), undo: $('undo'), clear: $('clear'), run: $('run'),
  stage: $('stage'), dropzone: $('dropzone'), view: $('view'), status: $('status'),
};

const state = {
  files: [],            // [{ name, rgba: Uint8ClampedArray, w, h }]
  w: 0, h: 0,
  mask: null,           // Uint8Array(w*h)
  history: [],          // mask snapshots for undo (cap 20)
  tool: 'brush',
  brush: 14,
  scale: 1,
  drawing: false,
  last: null,           // last brush point (image coords)
  box: null,            // { x0, y0, x1, y1 } while dragging the Box tool
  previewing: false,    // showing a cleaned preview of the reference
  previewRGBA: null,
  cv: null,             // cached OpenCV runtime
};

const ctx = el.view.getContext('2d', { willReadFrequently: true });

// --------------------------------------------------------------------------- //
// status / options
// --------------------------------------------------------------------------- //
function setStatus(msg) {
  const dims = state.w ? `  ·  ${state.w}×${state.h}` : '';
  const n = state.files.length;
  const count = n ? `  ·  ${n} image${n > 1 ? 's' : ''}` : '';
  el.status.textContent = `${msg}${dims}${count}`;
}

function opts() {
  return {
    method: el.method.value,
    palette: el.palette.checked,        // (kept for readability)
    paletteMatch: el.palette.checked,
    grow: Number(el.grow.value) || 0,
    dilate: Number(el.grow.value) || 0,
    radius: 3,
  };
}

// --------------------------------------------------------------------------- //
// file loading
// --------------------------------------------------------------------------- //
async function decode(file) {
  const bmp = await createImageBitmap(file);
  const c = document.createElement('canvas');
  c.width = bmp.width; c.height = bmp.height;
  const cx = c.getContext('2d');
  cx.drawImage(bmp, 0, 0);
  const id = cx.getImageData(0, 0, bmp.width, bmp.height);
  bmp.close?.();
  return { name: file.name, rgba: id.data, w: bmp.width, h: bmp.height };
}

async function loadFiles(fileList) {
  const incoming = [...fileList].filter((f) => f.type.startsWith('image/'));
  if (!incoming.length) return;
  setStatus('Decoding…');
  const decoded = [];
  for (const f of incoming) {
    try { decoded.push(await decode(f)); }
    catch { /* skip unreadable */ }
  }
  if (!decoded.length) { setStatus('No readable images.'); return; }

  // The first image sets the reference size; others must match (same-size batch).
  const ref = decoded[0];
  const kept = decoded.filter((d) => d.w === ref.w && d.h === ref.h);
  const skipped = decoded.length - kept.length;

  state.files = kept;
  state.w = ref.w; state.h = ref.h;
  state.mask = core.emptyMask(ref.w, ref.h);
  state.history = [];
  state.previewing = false; state.previewRGBA = null;

  el.dropzone.hidden = true;
  el.view.hidden = false;
  el.toolbar.hidden = false;
  fitView();
  redraw();
  setStatus(skipped
    ? `Loaded. Skipped ${skipped} image(s) of a different size.`
    : 'Paint over the watermark, then Clean.');
}

// --------------------------------------------------------------------------- //
// rendering
// --------------------------------------------------------------------------- //
function fitView() {
  const maxW = Math.max(320, el.stage.clientWidth - 32);
  const maxH = Math.max(320, el.stage.clientHeight - 32);
  state.scale = Math.min(maxW / state.w, maxH / state.h, 8);
  if (!isFinite(state.scale) || state.scale <= 0) state.scale = 1;
  el.view.width = Math.round(state.w * state.scale);
  el.view.height = Math.round(state.h * state.scale);
  el.view.style.width = el.view.width + 'px';
  el.view.style.height = el.view.height + 'px';
}

function refRGBA() { return state.files[0].rgba; }

function redraw() {
  const display = state.previewing
    ? state.previewRGBA
    : core.overlay(refRGBA(), state.mask, state.w, state.h);
  const buf = new ImageData(Uint8ClampedArray.from(display), state.w, state.h);
  const off = document.createElement('canvas');
  off.width = state.w; off.height = state.h;
  off.getContext('2d').putImageData(buf, 0, 0);

  ctx.imageSmoothingEnabled = false;
  ctx.clearRect(0, 0, el.view.width, el.view.height);
  ctx.drawImage(off, 0, 0, el.view.width, el.view.height);

  if (state.box) {                         // live Box-tool rectangle
    const s = state.scale;
    ctx.strokeStyle = '#23d18b'; ctx.lineWidth = 2; ctx.setLineDash([5, 3]);
    ctx.strokeRect(state.box.x0 * s, state.box.y0 * s,
      (state.box.x1 - state.box.x0) * s, (state.box.y1 - state.box.y0) * s);
    ctx.setLineDash([]);
  }
}

// --------------------------------------------------------------------------- //
// painting (pointer events: mouse + touch + pen)
// --------------------------------------------------------------------------- //
function toImage(ev) {
  const r = el.view.getBoundingClientRect();
  return {
    x: (ev.clientX - r.left) / state.scale,
    y: (ev.clientY - r.top) / state.scale,
  };
}

function pushHistory() {
  state.history.push(state.mask.slice());
  if (state.history.length > 20) state.history.shift();
}

function exitPreview() {
  if (state.previewing) { state.previewing = false; state.previewRGBA = null; }
}

function onDown(ev) {
  if (!state.files.length) return;
  el.view.setPointerCapture?.(ev.pointerId);
  ev.preventDefault();
  exitPreview();
  const p = toImage(ev);
  if (state.tool === 'box') {
    pushHistory();
    state.box = { x0: p.x, y0: p.y, x1: p.x, y1: p.y };
  } else {
    pushHistory();
    state.drawing = true;
    state.last = p;
    const val = state.tool === 'erase' ? 0 : 255;
    core.paintCircle(state.mask, state.w, state.h, p.x, p.y, state.brush, val);
    redraw();
  }
}

function onMove(ev) {
  if (state.box) {
    const p = toImage(ev);
    state.box.x1 = p.x; state.box.y1 = p.y;
    redraw();
    return;
  }
  if (!state.drawing) return;
  const p = toImage(ev);
  const val = state.tool === 'erase' ? 0 : 255;
  core.paintLine(state.mask, state.w, state.h, state.last.x, state.last.y, p.x, p.y, state.brush, val);
  state.last = p;
  redraw();
}

function onUp() {
  if (state.box) {
    core.paintRect(state.mask, state.w, state.h, state.box.x0, state.box.y0, state.box.x1, state.box.y1);
    state.box = null;
    redraw();
  }
  state.drawing = false;
  state.last = null;
}

// --------------------------------------------------------------------------- //
// engine helpers
// --------------------------------------------------------------------------- //
function loadScript(url, globalName) {
  return new Promise((resolve, reject) => {
    if (globalThis[globalName]) return resolve(globalThis[globalName]);
    const s = document.createElement('script');
    s.src = url; s.async = true;
    s.onload = () => resolve(globalThis[globalName]);
    s.onerror = () => reject(new Error(`Could not load ${url}`));
    document.head.appendChild(s);
  });
}

async function ensureCv() {
  if (state.cv) return state.cv;
  setStatus('Loading inpainting engine (one-time)…');
  state.cv = await loadOpenCv();
  return state.cv;
}

function rgbaToBlob(rgba, w, h) {
  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  c.getContext('2d').putImageData(new ImageData(Uint8ClampedArray.from(rgba), w, h), 0, 0);
  return new Promise((res) => c.toBlob(res, 'image/png'));
}

function download(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

function outName(name) {
  const dot = name.lastIndexOf('.');
  const base = dot > 0 ? name.slice(0, dot) : name;
  return `${base}_cleaned.png`;
}

// --------------------------------------------------------------------------- //
// actions
// --------------------------------------------------------------------------- //
async function doPreview() {
  if (!state.files.length || !core.hasMask(state.mask)) { setStatus('Paint over the watermark first.'); return; }
  try {
    const cv = await ensureCv();
    const inpaint = inpaintFactory(cv);
    state.previewRGBA = core.cleanRGBA(refRGBA(), state.mask, state.w, state.h, opts(), inpaint);
    state.previewing = true;
    redraw();
    setStatus('Preview (reference image). Edit the mask to go back.');
  } catch (e) { setStatus('Preview failed: ' + e.message); }
}

async function doRunAll() {
  if (!state.files.length || !core.hasMask(state.mask)) { setStatus('Paint over the watermark first.'); return; }
  let cv, inpaint;
  try { cv = await ensureCv(); inpaint = inpaintFactory(cv); }
  catch (e) { setStatus('Engine failed to load: ' + e.message); return; }

  const results = [];
  for (let i = 0; i < state.files.length; i++) {
    const f = state.files[i];
    setStatus(`Cleaning ${i + 1}/${state.files.length}…`);
    await new Promise((r) => setTimeout(r));      // let the status paint
    const out = core.cleanRGBA(f.rgba, state.mask, f.w, f.h, opts(), inpaint);
    results.push({ name: outName(f.name), blob: await rgbaToBlob(out, f.w, f.h) });
  }

  if (results.length === 1) {
    download(results[0].blob, results[0].name);
    setStatus('Done — saved 1 image.');
    return;
  }
  try {
    const JSZip = await loadScript(JSZIP_URL, 'JSZip');
    const zip = new JSZip();
    for (const r of results) zip.file(r.name, r.blob);
    const blob = await zip.generateAsync({ type: 'blob' });
    download(blob, 'cleaned.zip');
    setStatus(`Done — ${results.length} images in cleaned.zip.`);
  } catch (e) {
    // fallback: download individually
    for (const r of results) download(r.blob, r.name);
    setStatus(`Done — ${results.length} downloads (zip unavailable: ${e.message}).`);
  }
}

function doUndo() {
  if (!state.history.length) return;
  state.mask = state.history.pop();
  exitPreview();
  redraw();
  setStatus('Undo.');
}

function doClear() {
  if (!state.files.length) return;
  pushHistory();
  state.mask = core.emptyMask(state.w, state.h);
  exitPreview();
  redraw();
  setStatus('Selection cleared.');
}

// --------------------------------------------------------------------------- //
// wiring
// --------------------------------------------------------------------------- //
function bind() {
  el.files.addEventListener('change', (e) => loadFiles(e.target.files));
  el.files2.addEventListener('change', (e) => loadFiles(e.target.files));

  for (const radio of document.querySelectorAll('input[name="tool"]'))
    radio.addEventListener('change', (e) => { state.tool = e.target.value; });

  el.size.addEventListener('input', (e) => { state.brush = Number(e.target.value); });
  el.preview.addEventListener('click', doPreview);
  el.run.addEventListener('click', doRunAll);
  el.undo.addEventListener('click', doUndo);
  el.clear.addEventListener('click', doClear);

  el.view.addEventListener('pointerdown', onDown);
  el.view.addEventListener('pointermove', onMove);
  el.view.addEventListener('pointerup', onUp);
  el.view.addEventListener('pointercancel', onUp);
  el.view.addEventListener('contextmenu', (e) => e.preventDefault());

  // drag & drop onto the dropzone
  for (const evt of ['dragenter', 'dragover'])
    el.dropzone.addEventListener(evt, (e) => { e.preventDefault(); el.dropzone.classList.add('drag'); });
  for (const evt of ['dragleave', 'drop'])
    el.dropzone.addEventListener(evt, (e) => { e.preventDefault(); el.dropzone.classList.remove('drag'); });
  el.dropzone.addEventListener('drop', (e) => loadFiles(e.dataTransfer.files));

  window.addEventListener('resize', () => { if (state.files.length) { fitView(); redraw(); } });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'z' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); doUndo(); }
    else if (e.key === '[') state.brush = Math.max(2, state.brush - 2);
    else if (e.key === ']') state.brush = Math.min(80, state.brush + 2);
    el.size.value = String(state.brush);
  });
}

if ('serviceWorker' in navigator)
  window.addEventListener('load', () => navigator.serviceWorker.register('sw.js').catch(() => {}));

bind();
setStatus('Ready — open images to start.');
