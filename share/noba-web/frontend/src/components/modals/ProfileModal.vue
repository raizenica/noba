<script setup>
import { ref, watch } from 'vue'
import AppModal from '../ui/AppModal.vue'
import { useModalsStore } from '../../stores/modals'
import { useAuthStore } from '../../stores/auth'
import { useApi } from '../../composables/useApi'
import { useNotificationsStore } from '../../stores/notifications'

const modals = useModalsStore()
const auth = useAuthStore()
const notif = useNotificationsStore()
const { get, post, del } = useApi()

const activeSection = ref('profile')

// ── Profile ───────────────────────────────────────────────────────────────────
const profile = ref(null)

async function fetchProfile() {
  try {
    profile.value = await get('/api/profile')
  } catch { /* silent */ }
}

// ── Password ──────────────────────────────────────────────────────────────────
const pwCurrent = ref('')
const pwNew = ref('')
const pwConfirm = ref('')
const pwLoading = ref(false)

async function changePassword() {
  if (pwNew.value !== pwConfirm.value) {
    notif.addToast('Passwords do not match', 'error')
    return
  }
  pwLoading.value = true
  try {
    await post('/api/profile/password', { current: pwCurrent.value, new: pwNew.value })
    notif.addToast('Password changed', 'success')
    pwCurrent.value = ''
    pwNew.value = ''
    pwConfirm.value = ''
  } catch (e) {
    notif.addToast(e.message || 'Failed to change password', 'error')
  } finally {
    pwLoading.value = false
  }
}

// ── TOTP ──────────────────────────────────────────────────────────────────────
const totpSecret = ref('')
const totpUri = ref('')
const totpCode = ref('')
const totpSetupActive = ref(false)
const totpLoading = ref(false)

async function setupTotp() {
  totpLoading.value = true
  try {
    const d = await post('/api/auth/totp/setup', {})
    totpSecret.value = d.secret
    totpUri.value = d.provisioning_uri
    totpSetupActive.value = true
  } catch (e) {
    notif.addToast('TOTP setup failed: ' + e.message, 'error')
  } finally {
    totpLoading.value = false
  }
}

async function enableTotp() {
  totpLoading.value = true
  try {
    await post('/api/auth/totp/enable', { secret: totpSecret.value, code: totpCode.value })
    notif.addToast('2FA enabled', 'success')
    totpSetupActive.value = false
    totpCode.value = ''
  } catch {
    notif.addToast('Invalid code', 'error')
  } finally {
    totpLoading.value = false
  }
}

// ── API Keys ──────────────────────────────────────────────────────────────────
const apiKeys = ref([])
const newKeyName = ref('')
const newKeyRole = ref('viewer')
const lastCreatedKey = ref('')
const keysLoading = ref(false)

async function fetchApiKeys() {
  try {
    apiKeys.value = await get('/api/admin/api-keys') || []
  } catch { /* silent */ }
}

async function createApiKey() {
  if (!newKeyName.value.trim()) return
  keysLoading.value = true
  try {
    const d = await post('/api/admin/api-keys', { name: newKeyName.value, role: newKeyRole.value })
    lastCreatedKey.value = d.key || ''
    notif.addToast("API key created — copy it now, it won't be shown again", 'success')
    newKeyName.value = ''
    await fetchApiKeys()
  } catch (e) {
    notif.addToast(e.message || 'Failed to create key', 'error')
  } finally {
    keysLoading.value = false
  }
}

async function deleteApiKey(keyId) {
  if (!confirm('Delete this API key?')) return
  try {
    await del(`/api/admin/api-keys/${keyId}`)
    notif.addToast('API key deleted', 'success')
    await fetchApiKeys()
  } catch (e) {
    notif.addToast(e.message || 'Delete failed', 'error')
  }
}

// ── Lifecycle ─────────────────────────────────────────────────────────────────
watch(() => modals.profileModal, (val) => {
  if (val) {
    fetchProfile()
    if (auth.isAdmin) fetchApiKeys()
  }
})
</script>

<template>
  <AppModal
    :show="modals.profileModal"
    title="User Profile"
    width="600px"
    @close="modals.profileModal = false"
  >
    <div style="padding: 0 1rem 1rem">
      <!-- Section tabs -->
      <div style="display:flex;gap:0.25rem;margin-bottom:1rem;border-bottom:1px solid var(--border);padding-bottom:0.5rem">
        <button
          v-for="s in [
            { id: 'profile', label: 'Profile', icon: 'fa-user' },
            { id: 'password', label: 'Password', icon: 'fa-lock' },
            { id: 'totp', label: '2FA / TOTP', icon: 'fa-shield-alt' },
            { id: 'apikeys', label: 'API Keys', icon: 'fa-key' },
          ]"
          :key="s.id"
          class="btn btn-sm"
          :class="activeSection === s.id ? 'btn-primary' : ''"
          @click="activeSection = s.id"
        >
          <i class="fas" :class="s.icon" style="margin-right:4px"></i>{{ s.label }}
        </button>
      </div>

      <!-- Profile section -->
      <div v-if="activeSection === 'profile'">
        <div v-if="profile" style="display:grid;gap:.75rem">
          <div>
            <div style="font-size:.7rem;opacity:.5;text-transform:uppercase;letter-spacing:.05em;margin-bottom:2px">Username</div>
            <div style="font-weight:500">{{ profile.username }}</div>
          </div>
          <div>
            <div style="font-size:.7rem;opacity:.5;text-transform:uppercase;letter-spacing:.05em;margin-bottom:2px">Role</div>
            <span class="badge bs">{{ profile.role }}</span>
          </div>
          <div v-if="profile.totp_enabled != null">
            <div style="font-size:.7rem;opacity:.5;text-transform:uppercase;letter-spacing:.05em;margin-bottom:2px">2FA</div>
            <span class="badge" :class="profile.totp_enabled ? 'bs' : 'bn'">
              {{ profile.totp_enabled ? 'Enabled' : 'Disabled' }}
            </span>
          </div>
        </div>
        <div v-else style="opacity:.4;font-size:.85rem">Loading profile...</div>
      </div>

      <!-- Password section -->
      <div v-if="activeSection === 'password'" style="display:grid;gap:.75rem">
        <div>
          <label class="field-label">Current Password</label>
          <input v-model="pwCurrent" type="password" class="field-input" placeholder="Current password" />
        </div>
        <div>
          <label class="field-label">New Password</label>
          <input v-model="pwNew" type="password" class="field-input" placeholder="New password" />
        </div>
        <div>
          <label class="field-label">Confirm New Password</label>
          <input v-model="pwConfirm" type="password" class="field-input" placeholder="Confirm new password" />
        </div>
        <button class="btn btn-primary" :disabled="pwLoading || !pwCurrent || !pwNew || !pwConfirm" @click="changePassword">
          {{ pwLoading ? 'Saving...' : 'Change Password' }}
        </button>
      </div>

      <!-- TOTP section -->
      <div v-if="activeSection === 'totp'">
        <div v-if="!totpSetupActive">
          <p style="font-size:.85rem;opacity:.7;margin-bottom:1rem">
            Enable two-factor authentication using an authenticator app (Google Authenticator, Authy, etc.)
          </p>
          <button class="btn btn-primary" :disabled="totpLoading" @click="setupTotp">
            {{ totpLoading ? 'Setting up...' : 'Set Up 2FA' }}
          </button>
        </div>
        <div v-else style="display:grid;gap:.75rem">
          <div style="background:var(--surface-2);padding:.75rem;border-radius:6px;font-size:.85rem">
            <div style="margin-bottom:.5rem;font-weight:500">Scan QR code or enter the secret</div>
            <code style="display:block;word-break:break-all;font-size:.75rem;opacity:.8">{{ totpSecret }}</code>
          </div>
          <div>
            <label class="field-label">Verification Code</label>
            <input v-model="totpCode" type="text" class="field-input" placeholder="6-digit code from app" maxlength="6" />
          </div>
          <div style="display:flex;gap:.5rem">
            <button class="btn btn-primary" :disabled="totpLoading || totpCode.length !== 6" @click="enableTotp">
              {{ totpLoading ? 'Verifying...' : 'Enable 2FA' }}
            </button>
            <button class="btn" @click="totpSetupActive = false">Cancel</button>
          </div>
        </div>
      </div>

      <!-- API Keys section -->
      <div v-if="activeSection === 'apikeys'">
        <div v-if="lastCreatedKey" style="background:var(--surface-2);padding:.75rem;border-radius:6px;margin-bottom:1rem;font-size:.8rem">
          <div style="font-weight:500;color:var(--success);margin-bottom:.25rem">New key created — copy it now:</div>
          <code style="word-break:break-all">{{ lastCreatedKey }}</code>
          <button class="btn btn-sm" style="margin-top:.5rem" @click="lastCreatedKey = ''">Dismiss</button>
        </div>

        <!-- Create key -->
        <div style="display:flex;gap:.5rem;margin-bottom:1rem;align-items:flex-end" v-if="auth.isAdmin">
          <div style="flex:1">
            <label class="field-label">Key Name</label>
            <input v-model="newKeyName" type="text" class="field-input" placeholder="e.g. monitoring-bot" />
          </div>
          <div>
            <label class="field-label">Role</label>
            <select v-model="newKeyRole" class="field-select">
              <option value="viewer">Viewer</option>
              <option value="operator">Operator</option>
              <option value="admin">Admin</option>
            </select>
          </div>
          <button class="btn btn-primary" :disabled="keysLoading || !newKeyName.trim()" @click="createApiKey">
            Create
          </button>
        </div>

        <!-- Keys table -->
        <table class="data-table" style="width:100%" v-if="apiKeys.length">
          <thead>
            <tr>
              <th>Name</th>
              <th>Role</th>
              <th>Created</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="k in apiKeys" :key="k.id">
              <td>{{ k.name }}</td>
              <td><span class="badge bn">{{ k.role }}</span></td>
              <td style="font-size:.8rem;opacity:.7">{{ k.created_at ? new Date(k.created_at * 1000).toLocaleDateString() : '—' }}</td>
              <td>
                <button class="btn btn-sm bd" @click="deleteApiKey(k.id)">
                  <i class="fas fa-trash"></i>
                </button>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-else-if="!auth.isAdmin" style="opacity:.4;font-size:.85rem">Admin access required</div>
        <div v-else style="opacity:.4;font-size:.85rem;margin-top:.5rem">No API keys yet</div>
      </div>
    </div>
  </AppModal>
</template>
