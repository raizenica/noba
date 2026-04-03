// Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved.
// NOBA Command Center — Licensed under Apache 2.0.
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('noba-token') || '')
  const username = ref('')
  const userRole = ref('viewer')
  const authenticated = ref(!!token.value)

  const isAdmin = computed(() => userRole.value === 'admin')
  const isOperator = computed(() => userRole.value === 'operator' || isAdmin.value)

  function setToken(t) {
    token.value = t
    localStorage.setItem('noba-token', t)
    authenticated.value = true
  }

  function clearAuth() {
    token.value = ''
    username.value = ''
    userRole.value = 'viewer'
    authenticated.value = false
    localStorage.removeItem('noba-token')
  }

  async function login(user, pass) {
    const res = await fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: user, password: pass }),
    })
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      throw new Error(data.detail || 'Login failed')
    }
    const data = await res.json()
    setToken(data.token)
    await fetchUserInfo()
  }

  async function logout() {
    try {
      await fetch('/api/logout', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token.value}` },
      })
    } catch { /* ignore */ }
    clearAuth()
    if (navigator.serviceWorker?.controller) {
      navigator.serviceWorker.controller.postMessage({ type: 'LOGOUT' })
    }
  }

  async function fetchUserInfo() {
    if (!token.value) return
    try {
      const res = await fetch('/api/me', {
        headers: { Authorization: `Bearer ${token.value}` },
      })
      if (res.ok) {
        const data = await res.json()
        username.value = data.username || ''
        userRole.value = data.role || 'viewer'
      } else {
        clearAuth()
      }
    } catch {
      clearAuth()
    }
  }

  return {
    token, username, userRole, authenticated,
    isAdmin, isOperator,
    setToken, clearAuth, login, logout, fetchUserInfo,
  }
})
