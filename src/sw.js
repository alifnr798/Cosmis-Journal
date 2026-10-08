/* Service worker: membuat aplikasi tetap jalan tanpa internet.
 * Naikkan nomor versi SHELL setiap kali index.html / app.js diubah. */
const SHELL = "kjp-shell-v1";
const RUNTIME = "kjp-runtime-v1";
const ASSETS = ["./", "index.html", "app.js", "config.js", "data/journals.js", "manifest.webmanifest",
  "icons/icon.svg", "icons/icon-192.png", "icons/icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(ASSETS)));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== SHELL && k !== RUNTIME).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("message", (e) => { if (e.data === "skipWaiting") self.skipWaiting(); });

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  // Cek pembaruan database selalu lewat jaringan; aplikasi sendiri yang menangani kondisi offline.
  if (url.origin === location.origin && /\/data\/(version|journals)\.json$/.test(url.pathname)) return;
  if (url.hostname === "fonts.googleapis.com" || url.hostname === "fonts.gstatic.com") {
    e.respondWith(swr(e, RUNTIME));
    return;
  }
  if (url.origin === location.origin) e.respondWith(swr(e, SHELL));
});

async function swr(e, cacheName) {
  const req = e.request;
  const cache = await caches.open(cacheName);
  const cached = await cache.match(req, { ignoreSearch: true });
  const net = fetch(req).then((res) => {
    if (res && (res.ok || res.type === "opaque")) cache.put(req, res.clone());
    return res;
  }).catch(() => null);
  if (cached) { e.waitUntil(net); return cached; }
  const res = await net;
  if (res) return res;
  if (req.mode === "navigate") {
    const shell = await cache.match("index.html");
    if (shell) return shell;
  }
  return Response.error();
}
