<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref } from 'vue'
import { useApi } from '../../composables/useApi'

const emit = defineEmits(['done', 'cancel'])
const { post } = useApi()

const username = ref('')
const password = ref('')
const role = ref('viewer')
const saving = ref(false)
const error = ref('')

const roles = [
  { key: 'viewer', label: 'Viewer', desc: 'Read-only access to dashboards and monitoring.' },
  { key: 'operator', label: 'Operator', desc: 'Can control services, run commands, and manage automations.' },
  { key: 'admin', label: 'Admin', desc: 'Full access — settings, users, and system configuration.' },
]

async function addUser() {
  if (!username.value.trim() || !password.value.trim()) {
    error.value = 'Username and password are required.'
    return
  }
  saving.value = true
  error.value = ''
  try {
    await post('/api/admin/users', {
      action: 'add',
      username: username.value.trim(),
      password: password.value.trim(),
      role: role.value,
    })
    emit('done')
  } catch {
    error.value = 'Failed to create user. Username may already exist.'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="user-setup">
    <p class="setup-intro">
      Create an account for a team member. You can add more later in Settings.
    </p>

    <label class="field-label">Username</label>
    <input class="field-input" type="text" v-model="username" placeholder="jane" autocomplete="off" @keyup.enter="addUser">

    <label class="field-label" style="margin-top:.75rem">Password</label>
    <input class="field-input" type="password" v-model="password" placeholder="A strong password" autocomplete="new-password" @keyup.enter="addUser">

    <label class="field-label" style="margin-top:.75rem">Role</label>
    <div class="role-grid">
      <div
        v-for="r in roles"
        :key="r.key"
        class="role-card"
        :class="{ selected: role === r.key }"
        @click="role = r.key"
      >
        <div class="role-name">{{ r.label }}</div>
        <div class="role-desc">{{ r.desc }}</div>
      </div>
    </div>

    <div v-if="error" class="error-msg" style="margin-top:.75rem">
      <i class="fas fa-exclamation-circle"></i> {{ error }}
    </div>

    <div style="display:flex;gap:.5rem;margin-top:1.25rem;justify-content:flex-end">
      <button class="btn btn-sm" @click="emit('cancel')">Skip</button>
      <button class="btn btn-sm btn-primary" :disabled="saving" @click="addUser">
        <i class="fas fa-user-plus"></i> {{ saving ? 'Creating...' : 'Create User' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.user-setup { padding: .5rem 0; }

.setup-intro {
  font-size: .85rem;
  color: var(--text-muted);
  line-height: 1.5;
  margin-bottom: 1rem;
}

.role-grid {
  display: flex;
  flex-direction: column;
  gap: .4rem;
  margin-top: .4rem;
}

.role-card {
  padding: .6rem .8rem;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  cursor: pointer;
  transition: border-color .2s;
}
.role-card:hover { border-color: var(--accent); }
.role-card.selected { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 8%, var(--surface)); }

.role-name { font-weight: 600; font-size: .85rem; color: var(--text); }
.role-desc { font-size: .75rem; color: var(--text-muted); }

.error-msg {
  padding: .4rem .6rem;
  border-radius: 4px;
  font-size: .8rem;
  background: color-mix(in srgb, var(--danger) 15%, var(--surface));
  color: var(--danger);
}
</style>
