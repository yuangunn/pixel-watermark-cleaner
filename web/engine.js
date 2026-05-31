/**
 * Browser glue between the pure core and OpenCV.js.
 *
 * OpenCV.js (WebAssembly) runs the same Telea / Navier-Stokes inpainting the
 * desktop app uses -- entirely client-side, so the PWA works offline once the
 * wasm has been cached. The heavier LaMa backend is desktop/server-only and is
 * intentionally not part of the offline web build.
 *
 * Node never imports this file (it touches the DOM); only core.js is unit
 * tested. app.js wires loadOpenCv() + inpaintFactory() into core.cleanRGBA().
 */

// Swap to a vendored copy for guaranteed offline first-load; CDN is cached by
// the service worker after the first successful fetch.
export const OPENCV_URL = 'https://docs.opencv.org/4.x/opencv.js';

export function loadOpenCv(url = OPENCV_URL) {
  return new Promise((resolve, reject) => {
    const g = globalThis;
    if (g.cv && g.cv.Mat) return resolve(g.cv);
    const script = document.createElement('script');
    script.src = url;
    script.async = true;
    script.onerror = () => reject(new Error('Could not load OpenCV.js (offline and not yet cached?)'));
    script.onload = () => {
      const ready = () => resolve(g.cv);
      if (g.cv && g.cv.Mat) return ready();
      if (g.cv && !g.cv.Mat) { g.cv.onRuntimeInitialized = ready; return; }
      // Fallback: poll until the runtime is initialised.
      const started = Date.now();
      const timer = setInterval(() => {
        if (g.cv && g.cv.Mat) { clearInterval(timer); ready(); }
        else if (Date.now() - started > 20000) { clearInterval(timer); reject(new Error('OpenCV.js init timed out')); }
      }, 50);
    };
    document.head.appendChild(script);
  });
}

/**
 * Returns an inpaint function compatible with core.cleanRGBA:
 *   inpaint(rgba, w, h, mask, opts) -> Uint8Array(w*h*3)
 * It runs a full-image OpenCV inpaint; core composites only the masked region
 * back over the untouched original, so the invariants hold regardless.
 */
export function inpaintFactory(cv) {
  return function inpaint(rgba, w, h, mask, opts = {}) {
    const src = cv.matFromImageData(new ImageData(Uint8ClampedArray.from(rgba), w, h));
    const rgb = new cv.Mat();
    const maskMat = cv.Mat.zeros(h, w, cv.CV_8UC1);
    const dst = new cv.Mat();
    try {
      cv.cvtColor(src, rgb, cv.COLOR_RGBA2RGB);
      maskMat.data.set(mask);
      const flag = opts.method === 'ns' ? cv.INPAINT_NS : cv.INPAINT_TELEA;
      cv.inpaint(rgb, maskMat, dst, opts.radius || 3, flag);
      return new Uint8Array(dst.data);          // RGB, length w*h*3
    } finally {
      src.delete(); rgb.delete(); maskMat.delete(); dst.delete();
    }
  };
}
