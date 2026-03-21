const CACHE_NAME = 'noba-v4'
const STATS_CACHE = 'noba-stats'

// Install — cache shell assets
self.addEventListener('install', (event) => {
  self.skipWaiting()
})

// Activate — clean old caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME && k !== STATS_CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  )
})

// Message handler (LOGOUT clears stats cache, SHOW_NOTIFICATION posts notification)
self.addEventListener('message', (event) => {
  if (event.data?.type === 'LOGOUT') {
    caches.delete(STATS_CACHE)
  }
  if (event.data?.type === 'SHOW_NOTIFICATION') {
    const { title, body, tag } = event.data
    self.registration.showNotification(title, {
      body, tag: tag || 'noba',
      icon: '/favicon.svg',
      badge: '/favicon.svg',
      vibrate: [200, 100, 200],
    })
  }
})

// Notification click — focus/open window
self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  event.waitUntil(
    self.clients.matchAll({ type: 'window' }).then((clients) => {
      for (const client of clients) {
        if (client.url.includes(self.location.origin)) {
          return client.focus()
        }
      }
      return self.clients.openWindow('/')
    })
  )
})

// Fetch handler
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url)

  // Skip non-GET
  if (event.request.method !== 'GET') return

  // Skip SSE streams
  if (url.pathname === '/api/stream') return

  // API stats/status — network first, cache fallback
  if (url.pathname === '/api/stats' || url.pathname.startsWith('/api/status/public')) {
    event.respondWith(
      fetch(event.request).then((res) => {
        const clone = res.clone()
        caches.open(STATS_CACHE).then((c) => c.put(event.request, clone))
        return res
      }).catch(() => caches.match(event.request))
    )
    return
  }

  // Other API calls — network only
  if (url.pathname.startsWith('/api/')) return

  // Static assets — cache first (Vite hashed filenames are immutable)
  if (url.pathname.startsWith('/assets/')) {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        if (cached) return cached
        return fetch(event.request).then((res) => {
          const clone = res.clone()
          caches.open(CACHE_NAME).then((c) => c.put(event.request, clone))
          return res
        })
      })
    )
    return
  }

  // CDN resources — cache first
  if (url.hostname.includes('cdn') || url.hostname.includes('fonts') || url.hostname.includes('cdnjs')) {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        if (cached) return cached
        return fetch(event.request).then((res) => {
          if (res.ok) {
            const clone = res.clone()
            caches.open(CACHE_NAME).then((c) => c.put(event.request, clone))
          }
          return res
        })
      })
    )
    return
  }

  // Navigation — serve index.html for SPA
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request).catch(() => caches.match('/index.html'))
    )
  }
})

// Push notifications
self.addEventListener('push', (event) => {
  const data = event.data?.json() || {}
  event.waitUntil(
    self.registration.showNotification(data.title || 'NOBA', {
      body: data.body || '',
      icon: '/favicon.svg',
      badge: '/favicon.svg',
      vibrate: [200, 100, 200],
    })
  )
})
