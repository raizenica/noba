const CACHE_NAME = 'noba-v2';
const STATS_CACHE = 'noba-stats';

const STATIC_ASSETS = [
    '/',
    '/index.html',
    '/static/style.css',
    '/static/app.js',
    '/static/auth-mixin.js',
    '/static/actions-mixin.js',
    '/static/favicon.ico',
    '/manifest.json',
];

// ── Install: cache static assets ────────────────────────────────────────────
self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => cache.addAll(STATIC_ASSETS))
            .then(() => self.skipWaiting())
    );
});

// ── Activate: purge old caches ──────────────────────────────────────────────
self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(keys =>
            Promise.all(
                keys.filter(k => k !== CACHE_NAME && k !== STATS_CACHE)
                    .map(k => caches.delete(k))
            )
        ).then(() => self.clients.claim())
    );
});

// ── Message: handle logout cache clear ──────────────────────────────────────
self.addEventListener('message', event => {
    if (event.data && event.data.type === 'LOGOUT') {
        caches.delete(STATS_CACHE);
    }
});

// ── Fetch: network-first for API, cache-first for static ────────────────────
self.addEventListener('fetch', event => {
    const url = new URL(event.request.url);

    // Bypass non-GET and extensions
    if (event.request.method !== 'GET') return;
    if (url.protocol === 'chrome-extension:') return;

    // SSE streams — always bypass
    if (url.pathname === '/api/stream') return;

    // API calls: network-first, cache last-seen stats for offline
    if (url.pathname.startsWith('/api/')) {
        if (url.pathname === '/api/stats') {
            event.respondWith(
                fetch(event.request).then(res => {
                    const clone = res.clone();
                    caches.open(STATS_CACHE).then(c => c.put('/api/stats', clone));
                    return res;
                }).catch(() =>
                    caches.match('/api/stats').then(r => r || new Response('{}', { status: 503 }))
                )
            );
            return;
        }
        // Other API — bypass, no caching
        return;
    }

    // Static assets: cache-first with network fallback
    event.respondWith(
        caches.match(event.request).then(cached => {
            if (cached) return cached;
            return fetch(event.request).then(res => {
                // Cache CDN resources dynamically
                if (res.ok && (url.hostname === 'cdn.jsdelivr.net' ||
                               url.hostname === 'fonts.googleapis.com' ||
                               url.hostname === 'cdnjs.cloudflare.com' ||
                               url.hostname === 'fonts.gstatic.com')) {
                    const clone = res.clone();
                    caches.open(CACHE_NAME).then(c => c.put(event.request, clone));
                }
                return res;
            }).catch(() => {
                // Offline fallback — return cached index for navigation requests
                if (event.request.mode === 'navigate') {
                    return caches.match('/index.html');
                }
                return new Response('', { status: 503, statusText: 'Offline' });
            });
        })
    );
});

// ── Push notifications ──────────────────────────────────────────────────────
self.addEventListener('push', event => {
    if (!event.data) return;
    let payload;
    try {
        payload = event.data.json();
    } catch {
        payload = { title: 'NOBA Alert', body: event.data.text() };
    }
    const options = {
        body: payload.body || payload.msg || '',
        icon: '/static/favicon.ico',
        badge: '/static/favicon.ico',
        tag: payload.tag || 'noba-alert',
        data: { url: payload.url || '/' },
        vibrate: [200, 100, 200],
    };
    event.waitUntil(
        self.registration.showNotification(payload.title || 'NOBA', options)
    );
});

self.addEventListener('notificationclick', event => {
    event.notification.close();
    const url = event.notification.data?.url || '/';
    event.waitUntil(
        clients.matchAll({ type: 'window' }).then(list => {
            for (const client of list) {
                if (client.url.includes(url) && 'focus' in client) return client.focus();
            }
            return clients.openWindow(url);
        })
    );
});
