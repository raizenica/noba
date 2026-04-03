// Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
// NOBA Command Center — Licensed under Apache 2.0.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

// Shared spy functions — same instances returned on every useApi() call
const mockGet = vi.fn()
const mockPost = vi.fn()

vi.mock('../../composables/useApi', () => ({
  useApi: () => ({ get: mockGet, post: mockPost }),
}))

// useAuthStore is pulled in transitively by useApi's module; mock it too
vi.mock('../../stores/auth', () => ({
  useAuthStore: () => ({ token: 'test-token', clearAuth: vi.fn() }),
}))

import { useApprovalsStore } from '../../stores/approvals'

describe('Approvals Store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockGet.mockReset()
    mockPost.mockReset()
  })

  // --- Initial state ---

  it('starts with empty pending array and count 0', () => {
    const store = useApprovalsStore()
    expect(store.pending).toEqual([])
    expect(store.count).toBe(0)
  })

  // --- fetchPending ---

  it('fetchPending() populates pending and updates count', async () => {
    const mockApprovals = [
      { id: 1, trigger_source: 'high-cpu', action_type: 'restart_service' },
      { id: 2, trigger_source: 'disk-full', action_type: 'cleanup_logs' },
    ]
    mockGet.mockResolvedValueOnce(mockApprovals)

    const store = useApprovalsStore()
    await store.fetchPending()

    expect(mockGet).toHaveBeenCalledWith('/api/approvals?status=pending')
    expect(store.pending).toEqual(mockApprovals)
    expect(store.count).toBe(2)
  })

  it('fetchPending() sets pending to [] when API returns null', async () => {
    mockGet.mockResolvedValueOnce(null)

    const store = useApprovalsStore()
    await store.fetchPending()

    expect(store.pending).toEqual([])
    expect(store.count).toBe(0)
  })

  it('fetchPending() silently ignores errors', async () => {
    mockGet.mockRejectedValueOnce(new Error('Network error'))

    const store = useApprovalsStore()
    await expect(store.fetchPending()).resolves.toBeUndefined()
    expect(store.pending).toEqual([])
    expect(store.count).toBe(0)
  })

  // --- fetchCount ---

  it('fetchCount() updates count from API response', async () => {
    mockGet.mockResolvedValueOnce({ count: 7 })

    const store = useApprovalsStore()
    await store.fetchCount()

    expect(mockGet).toHaveBeenCalledWith('/api/approvals/count')
    expect(store.count).toBe(7)
  })

  it('fetchCount() defaults count to 0 when response has no count field', async () => {
    mockGet.mockResolvedValueOnce({})

    const store = useApprovalsStore()
    await store.fetchCount()

    expect(store.count).toBe(0)
  })

  it('fetchCount() silently ignores errors', async () => {
    mockGet.mockRejectedValueOnce(new Error('Network error'))

    const store = useApprovalsStore()
    await expect(store.fetchCount()).resolves.toBeUndefined()
  })

  // --- decide ---

  it('decide() calls POST and re-fetches pending list', async () => {
    const mockApprovals = [{ id: 2, trigger_source: 'other', action_type: 'noop' }]
    mockPost.mockResolvedValueOnce({ ok: true })
    mockGet.mockResolvedValueOnce(mockApprovals)

    const store = useApprovalsStore()
    await store.decide(1, 'approve')

    expect(mockPost).toHaveBeenCalledWith('/api/approvals/1/decide', { decision: 'approve' })
    expect(mockGet).toHaveBeenCalledWith('/api/approvals?status=pending')
    expect(store.pending).toEqual(mockApprovals)
    expect(store.count).toBe(1)
  })

  it('decide() propagates POST errors', async () => {
    mockPost.mockRejectedValueOnce(new Error('Unauthorized'))

    const store = useApprovalsStore()
    await expect(store.decide(1, 'deny')).rejects.toThrow('Unauthorized')
  })

  it('decide() works with deny decision', async () => {
    mockPost.mockResolvedValueOnce({ ok: true })
    mockGet.mockResolvedValueOnce([])

    const store = useApprovalsStore()
    await store.decide(5, 'deny')

    expect(mockPost).toHaveBeenCalledWith('/api/approvals/5/decide', { decision: 'deny' })
    expect(store.pending).toEqual([])
    expect(store.count).toBe(0)
  })
})
