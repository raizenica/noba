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
        <input
          v-model="password"
          class="field-input"
          type="password"
          autocomplete="current-password"
        >
      </div>

      <!-- Error -->
      <div v-if="error" style="color:var(--danger);font-size:.8rem;margin-bottom:1rem">{{ error }}</div>

      <!-- Submit -->
      <button class="btn btn-primary" type="submit" :disabled="loading" style="width:100%">
        <i class="fas" :class="loading ? 'fa-spinner fa-spin' : 'fa-sign-in-alt'"></i>
        {{ loading ? 'Authenticating...' : 'Login' }}
      </button>

      <!-- SSO -->
      <div style="text-align:center;margin-top:12px">
        <div style="color:var(--text-dim);font-size:.75rem;margin-bottom:8px">— or —</div>
        <a href="/api/auth/oidc/login" class="btn btn-sm">
          <i class="fas fa-sign-in-alt"></i> Sign in with SSO
        </a>
      </div>
    </form>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { useDashboardStore } from '../stores/dashboard'
import { useSettingsStore } from '../stores/settings'

const router = useRouter()
const auth = useAuthStore()
const dashboard = useDashboardStore()
const settings = useSettingsStore()

const username = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)

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
