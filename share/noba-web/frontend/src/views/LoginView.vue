<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<template>
  <div class="modal-overlay login-fullscreen">
    <form
      style="background:var(--surface);padding:2rem;border-radius:8px;border:1px solid var(--border);border-top:3px solid var(--accent);width:95%;max-width:400px;margin:auto"
      @submit.prevent="handleLogin"
    >
      <!-- Logo -->
      <div style="display:flex;align-items:center;gap:.75rem;margin-bottom:1.5rem">
        <div style="width:42px;height:42px;background:var(--accent-dim);border:1px solid var(--accent);display:flex;align-items:center;justify-content:center;color:var(--accent);border-radius:6px">
          <i class="fas fa-terminal"></i>
        </div>
        <div>
          <div style="font-weight:700;font-size:1.2rem;letter-spacing:.1em">NOBA <span style="color:var(--accent)">//</span> CMD</div>
          <div style="font-size:.65rem;color:var(--text-muted);letter-spacing:.2em;text-transform:uppercase">Command Center</div>
        </div>
      </div>

      <!-- Username -->
      <div style="margin-bottom:1rem">
        <label class="field-label">Username</label>
        <input
          v-model="username"
          class="field-input"
          type="text"
          autofocus
          autocomplete="username"
        >
      </div>

      <!-- Password -->
      <div style="margin-bottom:1rem">
        <label class="field-label">Password</label>
        <div style="position:relative">
          <input
            v-model="password"
            class="field-input"
            :type="showPassword ? 'text' : 'password'"
            autocomplete="current-password"
            style="padding-right:2.5rem"
          >
          <button type="button" class="pw-toggle" @click="showPassword = !showPassword"
            :title="showPassword ? 'Hide password' : 'Show password'">
            <i class="fas" :class="showPassword ? 'fa-eye-slash' : 'fa-eye'"></i>
          </button>
        </div>
      </div>

      <!-- Error -->
      <div v-if="error" style="color:var(--danger);font-size:.8rem;margin-bottom:1rem">{{ error }}</div>

      <!-- Submit -->
      <button class="btn btn-primary" type="submit" :disabled="loading" style="width:100%">
        <i class="fas" :class="loading ? 'fa-spinner fa-spin' : 'fa-sign-in-alt'"></i>
        {{ loading ? 'Authenticating...' : 'Login' }}
      </button>

      <!-- Social / SSO login -->
      <div style="text-align:center;margin-top:12px">
        <div style="color:var(--text-dim);font-size:.75rem;margin-bottom:8px">— or sign in with —</div>
        <div style="display:flex;flex-wrap:wrap;gap:8px;justify-content:center">
          <!-- Configured providers (clickable) -->
          <a v-for="p in providers" :key="p.id" :href="p.url" class="btn btn-sm social-btn">
            <i :class="['fab', providerIcon(p.id)]" v-if="isFab(p.id)"></i>
            <i :class="['fas', providerIcon(p.id)]" v-else></i>
            {{ p.name }}
          </a>
          <!-- Unconfigured providers (greyed out, show what's possible) -->
          <template v-if="!providers.length">
            <span v-for="p in availableProviders" :key="p.id"
              class="btn btn-sm social-btn social-disabled" :title="`Configure ${p.name} in Settings → Auth`">
              <i :class="['fab', providerIcon(p.id)]"></i>
              {{ p.name }}
            </span>
          </template>
        </div>
        <div v-if="!providers.length" style="color:var(--text-dim);font-size:.65rem;margin-top:6px">
          Configure in Settings → Auth &amp; Security
        </div>
      </div>
    </form>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { useDashboardStore } from '../stores/dashboard'
import { useSettingsStore } from '../stores/settings'
import { useApi } from '../composables/useApi'

const router = useRouter()
const auth = useAuthStore()
const dashboard = useDashboardStore()
const settings = useSettingsStore()
const { get } = useApi()

const username = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)
const showPassword = ref(false)
const providers = ref([])

onMounted(async () => {
  try {
    const data = await get('/api/auth/providers')
    if (data && Array.isArray(data)) providers.value = data
  } catch { /* no providers configured — that's fine */ }
})

function providerIcon(id) {
  const icons = { google: 'fa-google', facebook: 'fa-facebook', github: 'fa-github', microsoft: 'fa-microsoft' }
  return icons[id] || 'fa-sign-in-alt'
}
function isFab(id) {
  return ['google', 'facebook', 'github', 'microsoft'].includes(id)
}

const availableProviders = [
  { id: 'google', name: 'Google' },
  { id: 'facebook', name: 'Facebook' },
  { id: 'github', name: 'GitHub' },
  { id: 'microsoft', name: 'Microsoft' },
]

async function handleLogin() {
  if (loading.value) return
  error.value = ''
  loading.value = true
  try {
    await auth.login(username.value, password.value)
    // Bootstrap app data after successful login
    await Promise.all([
      settings.fetchSettings(),
      settings.fetchPreferences(),
    ])
    dashboard.connectSse()
    router.push('/dashboard')
  } catch (err) {
    error.value = err.message || 'Login failed'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.social-btn {
  display: inline-flex;
  align-items: center;
  gap: .4rem;
  min-width: 100px;
  justify-content: center;
}
.social-disabled {
  opacity: .35;
  cursor: not-allowed;
  pointer-events: none;
}
.pw-toggle {
  position: absolute;
  right: .5rem;
  top: 50%;
  transform: translateY(-50%);
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  padding: .25rem;
  font-size: .85rem;
}
.pw-toggle:hover { color: var(--accent); }
</style>
