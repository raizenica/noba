import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { createRouter, createWebHashHistory } from 'vue-router'
import LoginView from '../../views/LoginView.vue'

// Minimal router so useRouter() works inside the component
function makeRouter() {
  return createRouter({
    history: createWebHashHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/login', component: { template: '<div />' } },
      { path: '/dashboard', component: { template: '<div />' } },
    ],
  })
}

describe('LoginView', () => {
  let router

  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.restoreAllMocks()
    router = makeRouter()

    // jsdom does not implement EventSource — stub it so connectSse() doesn't throw
    global.EventSource = class {
      constructor() {}
      close() {}
      set onopen(_f) {}
      set onmessage(_f) {}
      set onerror(_f) {}
    }

    // Default: fetch calls fail (not authenticated)
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ detail: 'Unauthorized' }),
    })
  })

  it('renders username input field', () => {
    const wrapper = mount(LoginView, {
      global: { plugins: [router] },
    })
    const input = wrapper.find('input[type="text"]')
    expect(input.exists()).toBe(true)
  })

  it('renders password input field', () => {
    const wrapper = mount(LoginView, {
      global: { plugins: [router] },
    })
    const input = wrapper.find('input[type="password"]')
    expect(input.exists()).toBe(true)
  })

  it('renders login button', () => {
    const wrapper = mount(LoginView, {
      global: { plugins: [router] },
    })
    const btn = wrapper.find('button[type="submit"]')
    expect(btn.exists()).toBe(true)
  })

  it('button shows "Login" text initially (not loading)', () => {
    const wrapper = mount(LoginView, {
      global: { plugins: [router] },
    })
    expect(wrapper.find('button[type="submit"]').text()).toContain('Login')
  })

  it('button is not disabled initially', () => {
    const wrapper = mount(LoginView, {
      global: { plugins: [router] },
    })
    const btn = wrapper.find('button[type="submit"]')
    expect(btn.attributes('disabled')).toBeUndefined()
  })

  it('does not show error message initially', () => {
    const wrapper = mount(LoginView, {
      global: { plugins: [router] },
    })
    // error div only renders with v-if="error"
    expect(wrapper.text()).not.toContain('Invalid')
  })

  it('shows error message when login fails', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ detail: 'Invalid credentials' }),
    })

    const wrapper = mount(LoginView, {
      global: { plugins: [router] },
    })

    await wrapper.find('input[type="text"]').setValue('alice')
    await wrapper.find('input[type="password"]').setValue('wrong')
    await wrapper.find('form').trigger('submit')

    // Wait for async handleLogin to settle
    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('Invalid credentials')
    })
  })

  it('shows generic error when server returns no detail', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      json: async () => ({}),
    })

    const wrapper = mount(LoginView, {
      global: { plugins: [router] },
    })

    await wrapper.find('form').trigger('submit')

    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('Login failed')
    })
  })

  it('redirects to /dashboard on successful login', async () => {
    // useApi checks res.headers.get('content-type') — provide a proper stub
    function mockJsonResponse(body) {
      return {
        ok: true,
        status: 200,
        headers: { get: (h) => (h === 'content-type' ? 'application/json' : null) },
        json: async () => body,
      }
    }

    // Call order: POST /api/login → GET /api/me → GET /api/settings + GET /api/user/preferences
    global.fetch = vi.fn()
      .mockResolvedValueOnce(mockJsonResponse({ token: 'tok123' }))
      .mockResolvedValueOnce(mockJsonResponse({ username: 'alice', role: 'operator' }))
      .mockResolvedValue(mockJsonResponse({}))

    const pushSpy = vi.spyOn(router, 'push').mockResolvedValue(undefined)

    const wrapper = mount(LoginView, {
      global: { plugins: [router] },
    })

    await wrapper.find('input[type="text"]').setValue('alice')
    await wrapper.find('input[type="password"]').setValue('secret')
    await wrapper.find('form').trigger('submit')

    await vi.waitFor(() => {
      expect(pushSpy).toHaveBeenCalledWith('/dashboard')
    }, { timeout: 2000 })
  })

  it('button is disabled while loading', async () => {
    // Use a promise we control so loading stays true during the check
    let resolveLogin
    const loginPromise = new Promise((res) => { resolveLogin = res })

    global.fetch = vi.fn().mockReturnValueOnce(loginPromise)

    const wrapper = mount(LoginView, {
      global: { plugins: [router] },
    })

    await wrapper.find('input[type="text"]').setValue('alice')
    await wrapper.find('input[type="password"]').setValue('secret')

    // Trigger form submit without awaiting the full async chain
    wrapper.find('form').trigger('submit')

    // Yield to let the synchronous part of handleLogin run (loading.value = true)
    await new Promise((r) => setTimeout(r, 0))

    expect(wrapper.find('button[type="submit"]').attributes('disabled')).toBeDefined()

    // Clean up — resolve the pending fetch so no uncaught rejection
    resolveLogin({ ok: false, json: async () => ({}) })
  })

  it('renders SSO link', () => {
    const wrapper = mount(LoginView, {
      global: { plugins: [router] },
    })
    const ssoLink = wrapper.find('a[href="/api/auth/oidc/login"]')
    expect(ssoLink.exists()).toBe(true)
  })
})
