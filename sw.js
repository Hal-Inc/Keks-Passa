// Keks Passa Service Worker v1.1
// Lightweight progressive web app caching for instant loads and true underground offline resilience

const CACHE_NAME = 'keks-passa-v1.1';

const PRECACHE_ASSETS = [
  './',
  './index.html',
  './manifest.json',
  './events.json',
  './venues.json',
  './favicon.svg',
  './tent.svg',
  './beer-empty.mp3',
  './beer-empty2.mp3',
  './beer-empty3.mp3',
  './beer-empty4.mp3',
  './kosmicare.svg',
  './kosmicare.png',
  './Kosmicare.jfif'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(PRECACHE_ASSETS);
    }).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);

  // 1. events.json & venues.json: Network-first with canonical query-agnostic cache fallback
  // Ensures ?v=timestamp cache-busting works online AND falls back cleanly when offline in club basements.
  if (url.pathname.endsWith('events.json') || url.pathname.endsWith('venues.json')) {
    const canonicalKey = url.pathname.endsWith('events.json') ? './events.json' : './venues.json';
    event.respondWith(
      fetch(req)
        .then((response) => {
          if (response && response.status === 200) {
            const copyCanonical = response.clone();
            caches.open(CACHE_NAME).then((cache) => {
              cache.put(canonicalKey, copyCanonical);
            });
          }
          return response;
        })
        .catch(() =>
          caches.match(canonicalKey).then((hit) => hit || caches.match(req, { ignoreSearch: true }))
        )
    );
    return;
  }

  // 2. OpenStreetMap tiles & external Google Fonts: Cache-first with background revalidation
  if (url.hostname.includes('tile.openstreetmap.org') || url.hostname.includes('fonts.gstatic.com')) {
    event.respondWith(
      caches.match(req).then((cached) => {
        if (cached) return cached;
        return fetch(req).then((response) => {
          if (response && response.status === 200) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(req, copy));
          }
          return response;
        }).catch(() => cached);
      })
    );
    return;
  }

  // 3. App Shell & Static assets: Stale-while-revalidate with ignoreSearch fallback
  event.respondWith(
    caches.match(req, { ignoreSearch: true }).then((cached) => {
      const fetchPromise = fetch(req)
        .then((networkResponse) => {
          if (networkResponse && networkResponse.status === 200) {
            const copy = networkResponse.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(req, copy));
          }
          return networkResponse;
        })
        .catch(() => cached);

      return cached || fetchPromise;
    })
  );
});
