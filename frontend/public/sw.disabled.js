const CACHE_NAME = "radioflix-pwa-v2";

const APP_ASSETS = [
  "/",
  "/radioflix.webmanifest",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/maskable-512.png",
];

self.addEventListener("install", (event) => {
  self.skipWaiting();

  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(APP_ASSETS).catch(() => {
        return Promise.resolve();
      });
    })
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((cacheName) => cacheName !== CACHE_NAME)
          .map((cacheName) => caches.delete(cacheName))
      );
    })
  );

  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") {
    return;
  }

  const url = new URL(event.request.url);

  // APIや音声ファイルはキャッシュしない
  if (
    url.pathname.startsWith("/api/") ||
    url.pathname.startsWith("/programs/") ||
    url.pathname.startsWith("/audio/")
  ) {
    return;
  }

  // Next.jsの開発用ファイルはキャッシュしない
  if (
    url.pathname.startsWith("/_next/") ||
    url.pathname.includes("webpack-hmr")
  ) {
    return;
  }

  // RadioFlix本体とアイコンだけ軽くキャッシュ
  if (url.origin === self.location.origin) {
    event.respondWith(
      caches.match(event.request).then((cachedResponse) => {
        if (cachedResponse) {
          return cachedResponse;
        }

        return fetch(event.request).then((response) => {
          const responseClone = response.clone();

          caches.open(CACHE_NAME).then((cache) => {
            cache.put(event.request, responseClone).catch(() => {});
          });

          return response;
        });
      })
    );
  }
});