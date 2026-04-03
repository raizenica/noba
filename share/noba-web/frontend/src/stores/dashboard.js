// Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
// NOBA Command Center — Licensed under Apache 2.0.
import { defineStore } from 'pinia'
import { ref, shallowReactive } from 'vue'
import { useAuthStore } from './auth'
import { SSE_HEARTBEAT_TIMEOUT_MS, POLLING_INTERVAL_MS } from '../constants'

export const useDashboardStore = defineStore('dashboard', () => {
  const connStatus = ref('offline')
  const offlineMode = ref(false)

  const live = shallowReactive({
    timestamp: 0, uptime: '', loadavg: [], memory: {},
    cpuPercent: 0, cpuTemp: null, gpuTemp: null,
    disks: [], services: [], zfs: {},
    containers: [], alerts: [], diskIo: [],
    // System info (from collect_system + collect_hardware)
    osName: '', kernel: '', hostname: '', defaultIp: '',
    hwCpu: '', hwGpu: '',
    memPercent: 0, battery: null,
    cpuHistory: [], netHealth: null,
    topCpu: [], topMem: [], topIo: [],
    // Network
    radar: [], certExpiry: [], domainExpiry: [],
    devicePresence: [], dockerUpdates: [],
    // Integrations
    pihole: null, adguard: null, plex: null, radarr: null,
    sonarr: null, qbit: null, truenas: null, proxmox: null,
    unifi: null, jellyfin: null, hass: null, speedtest: null,
    k8s: null, agents: [], weather: null,
    lidarr: null, readarr: null, bazarr: null, overseerr: null,
    prowlarr: null, tautulli: null, nextcloud: null,
    traefik: null, npm: null, authentik: null, cloudflare: null,
    omv: null, xcpng: null, homebridge: null, z2m: null,
    esphome: null, pikvm: null, piKvm: null, gitea: null, gitlab: null,
    github: null, paperless: null, vaultwarden: null,
    unifiProtect: null, scrutiny: null, plugins: null,
    tailscale: null, frigate: null, vpn: null, n8n: null,
    energy: [], cameraFeeds: [], kuma: [],
    radarrExtended: null, sonarrExtended: null,
    radarrCalendar: [], sonarrCalendar: [],
    // Managed integration instances (keyed by instance ID)
    instances: {},
    // Background health
    collector_pulse: 0, collector_status: 'healthy',
    })

  let _es = null
  let _pollInterval = null
  let _heartbeatTimer = null

  function mergeLiveData(payload) {
    for (const [key, val] of Object.entries(payload)) {
      if (key in live) live[key] = val
    }
  }

  function connectSse() {
    disconnectSse()
    const auth = useAuthStore()
    if (!auth.token) return

    const url = `/api/stream?token=${encodeURIComponent(auth.token)}`
    _es = new EventSource(url)

    _es.onopen = () => {
      connStatus.value = 'sse'
      offlineMode.value = false
      _resetHeartbeat()
    }

    _es.onmessage = (event) => {
      _resetHeartbeat()
      try { mergeLiveData(JSON.parse(event.data)) } catch { /* ignore */ }
    }

    _es.onerror = () => {
      if (_es) _es.close()
      _es = null
      connStatus.value = 'polling'
      _startPolling()
    }
  }

  function _resetHeartbeat() {
    clearTimeout(_heartbeatTimer)
    _heartbeatTimer = setTimeout(() => {
      if (_es) _es.close()
      _es = null
      connStatus.value = 'polling'
      _startPolling()
    }, SSE_HEARTBEAT_TIMEOUT_MS)
  }

  function _startPolling() {
    if (_pollInterval) return
    _pollInterval = setInterval(() => refreshStats(), POLLING_INTERVAL_MS)
  }

  async function refreshStats() {
    const auth = useAuthStore()
    try {
      const res = await fetch('/api/stats', {
        headers: { Authorization: `Bearer ${auth.token}` },
      })
      if (res.ok) {
        const data = await res.json()
        mergeLiveData(data)
        offlineMode.value = false
        if (connStatus.value !== 'sse') connectSse()
      }
    } catch {
      offlineMode.value = true
      connStatus.value = 'offline'
    }
  }

  function disconnectSse() {
    if (_es) { _es.close(); _es = null }
    if (_pollInterval) { clearInterval(_pollInterval); _pollInterval = null }
    if (_heartbeatTimer) { clearTimeout(_heartbeatTimer); _heartbeatTimer = null }
    connStatus.value = 'offline'
  }

  return {
    connStatus, offlineMode, live,
    connectSse, disconnectSse, refreshStats, mergeLiveData,
  }
})
