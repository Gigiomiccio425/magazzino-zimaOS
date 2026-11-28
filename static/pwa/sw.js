// Service worker: sempre prima la rete (aggiornamenti immediati), cache solo come riserva offline.
// Senza rete si possono CONSULTARE le pagine già aperte (ultima versione vista); le modifiche no:
// l'app blocca i form finché la rete non torna.
const CACHE = "magazzino-v2.5.0";
const PAGES = "magazzino-pagine";
const MAX_PAGES = 120;
const PRECACHE = ["/offline", "/static/css/style.css", "/static/js/app.js", "/static/favicon.svg",
  "/static/pwa/icon-192.png"];
// pagine da non conservare: azioni, fogli di stampa, export
const NO_CACHE = [/^\/print\/sheets/, /^\/backups/, /^\/sign/, /\.csv$/, /^\/scan\//];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE && k !== PAGES).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

async function trimPages() {
  const cache = await caches.open(PAGES);
  const keys = await cache.keys();
  for (let i = 0; i < keys.length - MAX_PAGES; i++) await cache.delete(keys[i]);
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  if (url.pathname.startsWith("/static/")) {
    event.respondWith(
      fetch(req).then((res) => {
        if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(req, copy)); }
        return res;
      }).catch(() => caches.match(req))
    );
    return;
  }
  if (req.mode === "navigate") {
    const cacheable = !NO_CACHE.some((re) => re.test(url.pathname));
    event.respondWith(
      fetch(req).then((res) => {
        if (cacheable && res.ok && res.type === "basic") {
          const copy = res.clone();
          caches.open(PAGES).then((c) => c.delete(req).then(() => c.put(req, copy))).then(trimPages);
        }
        return res;
      }).catch(() => caches.open(PAGES).then((c) => c.match(req)).then((hit) => hit || caches.match("/offline")))
    );
  }
});
