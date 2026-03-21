<script setup>
import { ref, onMounted } from 'vue'
import { useSettingsStore } from '../../stores/settings'
import { useAuthStore } from '../../stores/auth'
import { useApi } from '../../composables/useApi'

const settingsStore = useSettingsStore()
const authStore = useAuthStore()
const { post } = useApi()

const saving = ref(false)
const saveMsg = ref('')

onMounted(async () => {
  if (!settingsStore.loaded) await settingsStore.fetchSettings()
})

async function save() {
  saving.value = true
  saveMsg.value = ''
  try {
    await settingsStore.saveSettings()
    saveMsg.value = 'Saved.'
    setTimeout(() => { saveMsg.value = '' }, 2500)
  } catch {
    saveMsg.value = 'Save failed.'
  } finally {
    saving.value = false
  }
}

async function downloadConfigBackup() {
  try {
    const res = await fetch('/api/settings/backup', {
      headers: { Authorization: `Bearer ${authStore.token}` },
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = 'config.yaml'; a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    alert('Download failed: ' + e.message)
  }
}

async function uploadConfigRestore(evt) {
  const file = evt.target.files[0]
  if (!file) return
  const formData = new FormData()
  formData.append('file', file)
  try {
    const res = await fetch('/api/settings/restore', {
      method: 'POST',
      headers: { Authorization: `Bearer ${authStore.token}` },
      body: formData,
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    alert('Config restored. Reload to apply.')
  } catch (e) {
    alert('Restore failed: ' + e.message)
  }
}

async function resetLayout() {
  if (!confirm('Reset your dashboard layout to the factory defaults?')) return
  try {
    const res = await fetch('/api/user/preferences', {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${authStore.token}` },
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    saveMsg.value = 'Layout reset to defaults.'
    setTimeout(() => { saveMsg.value = '' }, 2500)
  } catch (e) {
    saveMsg.value = 'Reset failed: ' + e.message
  }
}
</script>

<template>
  <div>
    <!-- Data Sources -->
    <div class="s-section">
      <span class="s-label">Data Sources</span>
      <div style="display:flex;flex-direction:column;gap:.7rem">
        <div>
          <label class="field-label" for="s-services">Services to Monitor</label>
          <input id="s-services" class="field-input" type="text"
            v-model="settingsStore.data.monitoredServices"
            placeholder="nginx,sshd,docker">
        </div>
        <div>
          <label class="field-label" for="s-radar">Radar IPs (Native Ping)</label>
          <input id="s-radar" class="field-input" type="text"
            v-model="settingsStore.data.radarIps"
            placeholder="192.168.1.1,10.0.0.1">
        </div>
        <div>
          <label class="field-label" for="s-bookmarks">Homelab Bookmarks</label>
          <textarea id="s-bookmarks" class="field-input"
            v-model="settingsStore.data.bookmarksStr"
            style="height:72px;resize:vertical"
            placeholder="Label|https://url.local"></textarea>
        </div>
      </div>
    </div>

    <!-- Network Watchdog -->
    <div class="s-section">
      <span class="s-label">Network Watchdog</span>
      <p class="help-text" style="margin-bottom:.6rem">Alerts if WAN is down but Local DNS survives.</p>
      <div class="field-2">
        <div>
          <label class="field-label" for="s-wan-ip">WAN Test IP (e.g. 8.8.8.8)</label>
          <input id="s-wan-ip" class="field-input" type="text"
            v-model="settingsStore.data.wanTestIp" placeholder="8.8.8.8">
        </div>
        <div>
          <label class="field-label" for="s-lan-ip">LAN DNS IP</label>
          <input id="s-lan-ip" class="field-input" type="text"
            v-model="settingsStore.data.lanTestIp" placeholder="192.168.100.111">
        </div>
      </div>
    </div>

    <!-- Public Status Page -->
    <div class="s-section">
      <span class="s-label">Public Status Page</span>
      <div>
        <label class="field-label" for="s-status-svcs">Services to show (comma-separated keys)</label>
        <input id="s-status-svcs" class="field-input" type="text"
          v-model="settingsStore.data.statusPageServices"
          placeholder="scrutiny,tailscale,pihole,frigate">
      </div>
    </div>

    <!-- Hostname -->
    <div class="s-section">
      <span class="s-label">Host Settings</span>
      <div>
        <label class="field-label" for="s-hostname">Hostname Override</label>
        <input id="s-hostname" class="field-input" type="text"
          v-model="settingsStore.data.hostname"
          placeholder="Leave blank to auto-detect">
      </div>
    </div>

    <!-- Config Backup & Restore (admin only) -->
    <div v-if="authStore.isAdmin" class="s-section">
      <span class="s-label">Configuration Backup &amp; Restore</span>
      <p class="help-text" style="margin-bottom:.6rem">
        Download the current config.yaml or restore from a previous backup. Admin only.
      </p>
      <div style="display:flex;gap:.6rem;flex-wrap:wrap;align-items:center">
        <button class="btn btn-sm" @click="downloadConfigBackup">
          <i class="fas fa-download"></i> Download config.yaml
        </button>
        <label class="btn btn-sm btn-secondary" style="cursor:pointer">
          <i class="fas fa-upload"></i> Restore config.yaml
          <input type="file" accept=".yaml,.yml" style="display:none" @change="uploadConfigRestore">
        </label>
      </div>
    </div>

    <!-- Dashboard Layout Reset -->
    <div class="s-section">
      <span class="s-label">Dashboard Layout Sync</span>
      <p class="help-text" style="margin-bottom:.6rem">
        Your dashboard layout (card visibility, collapsed state, sidebar, and theme) is synced to your account.
      </p>
      <div style="display:flex;gap:.6rem;flex-wrap:wrap;align-items:center">
        <button class="btn btn-sm" style="color:var(--danger)" @click="resetLayout">
          <i class="fas fa-undo"></i> Reset to Default Layout
        </button>
      </div>
    </div>

    <!-- Save -->
    <div style="margin-top:1.25rem;display:flex;gap:.75rem;align-items:center">
      <button class="btn btn-primary" :disabled="saving" @click="save">
        <i class="fas" :class="saving ? 'fa-spinner fa-spin' : 'fa-check'"></i>
        {{ saving ? 'Saving…' : 'Save & Apply' }}
      </button>
      <span v-if="saveMsg" style="font-size:.8rem;color:var(--text-muted)">{{ saveMsg }}</span>
    </div>
  </div>
</template>
