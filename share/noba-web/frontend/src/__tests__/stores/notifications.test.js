// Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
// NOBA Command Center — Licensed under Apache 2.0.
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useNotificationsStore } from '../../stores/notifications'

describe('Notifications Store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  // --- Initial state ---

  it('starts with empty toasts array', () => {
    const store = useNotificationsStore()
    expect(store.toasts).toEqual([])
  })

  // --- addToast ---

  it('addToast() creates toast with id, message, type', () => {
    const store = useNotificationsStore()
    store.addToast('Hello', 'success', 0)
    expect(store.toasts).toHaveLength(1)
    expect(store.toasts[0]).toMatchObject({ message: 'Hello', type: 'success' })
    expect(typeof store.toasts[0].id).toBe('number')
  })

  it('addToast() uses info as default type', () => {
    const store = useNotificationsStore()
    store.addToast('Info message', undefined, 0)
    expect(store.toasts[0].type).toBe('info')
  })

  it('multiple toasts accumulate', () => {
    const store = useNotificationsStore()
    store.addToast('First', 'info', 0)
    store.addToast('Second', 'warning', 0)
    store.addToast('Third', 'error', 0)
    expect(store.toasts).toHaveLength(3)
    expect(store.toasts[0].message).toBe('First')
    expect(store.toasts[1].message).toBe('Second')
    expect(store.toasts[2].message).toBe('Third')
  })

  it('each toast gets a unique id', () => {
    const store = useNotificationsStore()
    store.addToast('A', 'info', 0)
    store.addToast('B', 'info', 0)
    const ids = store.toasts.map(t => t.id)
    expect(new Set(ids).size).toBe(2)
  })

  // --- removeToast ---

  it('removeToast() removes by id, leaves others', () => {
    const store = useNotificationsStore()
    store.addToast('Keep me', 'info', 0)
    store.addToast('Remove me', 'error', 0)
    const removeId = store.toasts[1].id
    store.removeToast(removeId)
    expect(store.toasts).toHaveLength(1)
    expect(store.toasts[0].message).toBe('Keep me')
  })

  it('removeToast() with unknown id changes nothing', () => {
    const store = useNotificationsStore()
    store.addToast('Stay', 'info', 0)
    store.removeToast(99999)
    expect(store.toasts).toHaveLength(1)
  })

  // --- Auto-dismiss ---

  it('toast is removed after its duration', () => {
    const store = useNotificationsStore()
    store.addToast('Temporary', 'info', 3000)
    expect(store.toasts).toHaveLength(1)
    vi.advanceTimersByTime(3000)
    expect(store.toasts).toHaveLength(0)
  })

  it('toast is not removed before duration elapses', () => {
    const store = useNotificationsStore()
    store.addToast('Still here', 'info', 3000)
    vi.advanceTimersByTime(2999)
    expect(store.toasts).toHaveLength(1)
  })

  it('duration=0 means no auto-dismiss', () => {
    const store = useNotificationsStore()
    store.addToast('Sticky', 'info', 0)
    vi.advanceTimersByTime(60000)
    expect(store.toasts).toHaveLength(1)
  })

  it('each toast auto-dismisses independently', () => {
    const store = useNotificationsStore()
    store.addToast('Short', 'info', 1000)
    store.addToast('Long', 'info', 5000)
    vi.advanceTimersByTime(1000)
    expect(store.toasts).toHaveLength(1)
    expect(store.toasts[0].message).toBe('Long')
    vi.advanceTimersByTime(4000)
    expect(store.toasts).toHaveLength(0)
  })
})
