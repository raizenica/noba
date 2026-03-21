import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useAuthStore } from '../../stores/auth'

describe('Auth Store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.restoreAllMocks()
  })

  // --- Initialization ---

  it('initializes unauthenticated when no token in localStorage', () => {
    const store = useAuthStore()
    expect(store.authenticated).toBe(false)
    expect(store.token).toBe('')
    expect(store.username).toBe('')
    expect(store.userRole).toBe('viewer')
  })

  it('initializes authenticated when token exists in localStorage', () => {
    localStorage.setItem('noba-token', 'existing-token')
    setActivePinia(createPinia())
    const store = useAuthStore()
    expect(store.authenticated).toBe(true)
    expect(store.token).toBe('existing-token')
  })

  // --- setToken ---

  it('setToken() stores token in localStorage and sets authenticated=true', () => {
    const store = useAuthStore()
    store.setToken('my-token')
    expect(store.token).toBe('my-token')
    expect(localStorage.getItem('noba-token')).toBe('my-token')
    expect(store.authenticated).toBe(true)
  })

  // --- clearAuth ---

  it('clearAuth() resets all state and removes localStorage token', () => {
    const store = useAuthStore()
    store.setToken('some-token')
    store.username = 'alice'
    store.userRole = 'admin'
    store.clearAuth()
    expect(store.token).toBe('')
    expect(store.username).toBe('')
    expect(store.userRole).toBe('viewer')
    expect(store.authenticated).toBe(false)
    expect(localStorage.getItem('noba-token')).toBeNull()
  })

  // --- Computed: isAdmin ---

  it('isAdmin is true only for admin role', () => {
    const store = useAuthStore()
    store.userRole = 'admin'
    expect(store.isAdmin).toBe(true)
    store.userRole = 'operator'
    expect(store.isAdmin).toBe(false)
    store.userRole = 'viewer'
    expect(store.isAdmin).toBe(false)
  })

  // --- Computed: isOperator ---

  it('isOperator is true for operator role', () => {
    const store = useAuthStore()
    store.userRole = 'operator'
    expect(store.isOperator).toBe(true)
  })

  it('isOperator is true for admin role', () => {
    const store = useAuthStore()
    store.userRole = 'admin'
    expect(store.isOperator).toBe(true)
  })

  it('viewer has no elevated permissions', () => {
    const store = useAuthStore()
    store.userRole = 'viewer'
    expect(store.isAdmin).toBe(false)
    expect(store.isOperator).toBe(false)
  })

  // --- login() ---

  it('login() calls fetch, stores token on success', async () => {
    const store = useAuthStore()
    global.fetch = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ token: 'new-token' }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ username: 'alice', role: 'operator' }),
      })

    await store.login('alice', 'secret')

    expect(global.fetch).toHaveBeenCalledTimes(2)
    expect(global.fetch).toHaveBeenNthCalledWith(1, '/api/login', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ username: 'alice', password: 'secret' }),
    }))
    expect(store.token).toBe('new-token')
    expect(store.authenticated).toBe(true)
    expect(localStorage.getItem('noba-token')).toBe('new-token')
  })

  it('login() throws on failure with error message', async () => {
    const store = useAuthStore()
    global.fetch = vi.fn().mockResolvedValueOnce({
      ok: false,
      json: async () => ({ detail: 'Invalid credentials' }),
    })

    await expect(store.login('alice', 'wrong')).rejects.toThrow('Invalid credentials')
    expect(store.authenticated).toBe(false)
  })

  it('login() throws generic message when response has no detail', async () => {
    const store = useAuthStore()
    global.fetch = vi.fn().mockResolvedValueOnce({
      ok: false,
      json: async () => ({}),
    })

    await expect(store.login('alice', 'wrong')).rejects.toThrow('Login failed')
  })

  // --- logout() ---

  it('logout() calls fetch and clears auth', async () => {
    const store = useAuthStore()
    store.setToken('tok')
    store.username = 'alice'
    store.userRole = 'operator'

    global.fetch = vi.fn().mockResolvedValueOnce({ ok: true })

    await store.logout()

    expect(global.fetch).toHaveBeenCalledWith('/api/logout', expect.objectContaining({
      method: 'POST',
      headers: expect.objectContaining({ Authorization: 'Bearer tok' }),
    }))
    expect(store.authenticated).toBe(false)
    expect(store.token).toBe('')
    expect(localStorage.getItem('noba-token')).toBeNull()
  })

  it('logout() clears auth even when fetch throws', async () => {
    const store = useAuthStore()
    store.setToken('tok')
    global.fetch = vi.fn().mockRejectedValueOnce(new Error('network error'))

    await store.logout()

    expect(store.authenticated).toBe(false)
    expect(store.token).toBe('')
  })

  // --- fetchUserInfo() ---

  it('fetchUserInfo() populates username and role on success', async () => {
    const store = useAuthStore()
    store.setToken('tok')
    global.fetch = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => ({ username: 'bob', role: 'admin' }),
    })

    await store.fetchUserInfo()

    expect(store.username).toBe('bob')
    expect(store.userRole).toBe('admin')
  })

  it('fetchUserInfo() calls clearAuth on 401', async () => {
    const store = useAuthStore()
    store.setToken('expired-tok')
    global.fetch = vi.fn().mockResolvedValueOnce({ ok: false })

    await store.fetchUserInfo()

    expect(store.authenticated).toBe(false)
    expect(store.token).toBe('')
  })

  it('fetchUserInfo() does nothing when no token', async () => {
    const store = useAuthStore()
    global.fetch = vi.fn()

    await store.fetchUserInfo()

    expect(global.fetch).not.toHaveBeenCalled()
  })
})
