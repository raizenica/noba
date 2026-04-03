// Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
// NOBA Command Center — Licensed under Apache 2.0.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useDashboardStore } from '../../stores/dashboard'

// EventSource is not provided by jsdom; stub it to prevent ReferenceError
// in case any code path references it at module level.
if (typeof global.EventSource === 'undefined') {
  global.EventSource = class {
    constructor() {}
    close() {}
  }
}

describe('Dashboard Store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.restoreAllMocks()
  })

  // --- Initial state ---

  it('initializes with connStatus="offline"', () => {
    const store = useDashboardStore()
    expect(store.connStatus).toBe('offline')
  })

  it('initializes with offlineMode=false', () => {
    const store = useDashboardStore()
    expect(store.offlineMode).toBe(false)
  })

  it('live reactive object has expected numeric defaults of 0', () => {
    const store = useDashboardStore()
    expect(store.live.cpuPercent).toBe(0)
    expect(store.live.timestamp).toBe(0)
  })

  it('live reactive object has expected null defaults', () => {
    const store = useDashboardStore()
    expect(store.live.cpuTemp).toBeNull()
    expect(store.live.gpuTemp).toBeNull()
    expect(store.live.pihole).toBeNull()
    expect(store.live.unifi).toBeNull()
    expect(store.live.weather).toBeNull()
  })

  it('live reactive object has expected empty array defaults', () => {
    const store = useDashboardStore()
    expect(store.live.loadavg).toEqual([])
    expect(store.live.disks).toEqual([])
    expect(store.live.services).toEqual([])
    expect(store.live.containers).toEqual([])
    expect(store.live.alerts).toEqual([])
    expect(store.live.agents).toEqual([])
    expect(store.live.energy).toEqual([])
    expect(store.live.cameraFeeds).toEqual([])
    expect(store.live.kuma).toEqual([])
  })

  it('live reactive object has expected empty object defaults', () => {
    const store = useDashboardStore()
    expect(store.live.memory).toEqual({})
    expect(store.live.zfs).toEqual({})
  })

  // --- mergeLiveData ---

  it('mergeLiveData() updates known keys', () => {
    const store = useDashboardStore()
    store.mergeLiveData({ cpuPercent: 42, timestamp: 1234567890 })
    expect(store.live.cpuPercent).toBe(42)
    expect(store.live.timestamp).toBe(1234567890)
  })

  it('mergeLiveData() ignores unknown keys', () => {
    const store = useDashboardStore()
    store.mergeLiveData({ unknownKey: 'should-be-ignored', cpuPercent: 10 })
    expect(store.live.unknownKey).toBeUndefined()
    expect(store.live.cpuPercent).toBe(10)
  })

  it('mergeLiveData() handles partial updates (only some keys)', () => {
    const store = useDashboardStore()
    // Set initial known values
    store.mergeLiveData({ cpuPercent: 50, timestamp: 100 })
    // Partial update — only cpuPercent changes
    store.mergeLiveData({ cpuPercent: 75 })
    expect(store.live.cpuPercent).toBe(75)
    expect(store.live.timestamp).toBe(100)
  })

  it('mergeLiveData() updates memory object', () => {
    const store = useDashboardStore()
    const memData = { total: 16000, used: 8000, percent: 50 }
    store.mergeLiveData({ memory: memData })
    expect(store.live.memory).toEqual(memData)
  })

  it('mergeLiveData() updates array fields', () => {
    const store = useDashboardStore()
    const disks = [{ path: '/', used: 100, total: 500 }]
    store.mergeLiveData({ disks })
    expect(store.live.disks).toEqual(disks)
  })

  it('mergeLiveData() updates integration fields (null -> object)', () => {
    const store = useDashboardStore()
    const piholeData = { status: 'enabled', blocked: 1234 }
    store.mergeLiveData({ pihole: piholeData })
    expect(store.live.pihole).toEqual(piholeData)
  })

  it('mergeLiveData() handles empty payload gracefully', () => {
    const store = useDashboardStore()
    const before = store.live.cpuPercent
    store.mergeLiveData({})
    expect(store.live.cpuPercent).toBe(before)
  })

  // --- disconnectSse ---

  it('disconnectSse() sets connStatus to "offline"', () => {
    const store = useDashboardStore()
    // Manually set a non-offline status to verify the change
    store.connStatus = 'sse'
    store.disconnectSse()
    expect(store.connStatus).toBe('offline')
  })

  it('disconnectSse() is idempotent — safe to call multiple times', () => {
    const store = useDashboardStore()
    store.disconnectSse()
    store.disconnectSse()
    expect(store.connStatus).toBe('offline')
  })
})
