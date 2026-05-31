/* Service worker: makes the app work offline.
 *
 * - App shell (HTML/CSS/JS/icon) is precached on install.
 * - Heavy CDN deps (OpenCV.js wasm, JSZip) are cached on first use, so the app
 *   is fully offline after the first successful online session.
 * Bump CACHE when shipping changes to invalidate the old shell.
 */
const CACHE = 'pwc-v1';
const SHELL = [
  './', './index.html', './styles.css',
  './app.js', './core.js', './engine.js',
  './manifest.webmanifest', './icon.svg',
];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  e.respondWith(
    caches.match(req).then((hit) => {
      if (hit) return hit;
      return fetch(req).then((res) => {
        // Runtime-cache same-origin assets and the big CDN deps (incl. opaque).
        const url = req.url;
        const cacheable = res && (res.ok || res.type === 'opaque') &&
          (url.startsWith(self.location.origin) || /opencv\.js|jszip/i.test(url));
        if (cacheable) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
        }
        return res;
      }).catch(() => hit);
    })
  );
});
