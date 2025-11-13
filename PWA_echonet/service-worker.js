self.addEventListener("install", event => {
    self.skipWaiting();
});

self.addEventListener("activate", event => {
    event.waitUntil(clients.claim());
});

self.addEventListener("fetch", event => {
    const url = new URL(event.request.url);

    // Always fetch dynamic API routes from network
    if (url.pathname === "/info" || url.pathname === "/nodes") {
        event.respondWith(fetch(event.request));
        return;
    }

    // For everything else → network first, fallback to cache
    event.respondWith(
        fetch(event.request)
            .then(response => response)
            .catch(() => caches.match(event.request))
    );
});
