const CACHE_NAME = 'manga-tracker-v5';
const ASSETS = [
  '/',
  '/index.html',
  '/styles.css',
  '/script.js?v=5',
  '/descargas.html',
  '/descargas.js?v=2',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS))
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) =>
      Promise.all(
        cacheNames
          .filter((name) => name !== CACHE_NAME)
          .map((name) => caches.delete(name))
      )
    )
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;

  if (
    request.mode === 'navigate' ||
    request.destination === 'document'
  ) {
    event.respondWith(
      (async () => {
        try {
          const networkResponse = await fetch(request);
          return networkResponse;
        } catch (error) {
          const cached = await caches.match('/index.html');
          if (cached) return cached;
          throw error;
        }
      })()
    );
    return;
  }

  if (request.method !== 'GET') {
    event.respondWith(fetch(request));
    return;
  }

  event.respondWith(
    caches.match(request).then(
      (cachedResponse) => cachedResponse || fetch(request)
    )
  );
});
