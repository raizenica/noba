<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, onMounted } from 'vue'
import { useSettingsStore } from '../../stores/settings'
import { useAuthStore } from '../../stores/auth'
import { useNotificationsStore } from '../../stores/notifications'
import { useApi } from '../../composables/useApi'
import { useModalsStore } from '../../stores/modals'
import { UPDATE_RELOAD_DELAY_MS } from '../../constants'

const settingsStore = useSettingsStore()
const authStore = useAuthStore()
const notify = useNotificationsStore()
const { get, post, del, download, request } = useApi()
const modals = useModalsStore()

const saving = ref(false)
const saveMsg = ref('')

// ── Self-update ──────────────────────────────────────────────────────────────
const updateInfo = ref(null)
const updateChecking = ref(false)
const updateApplying = ref(false)
const updateResult = ref(null)

async function checkForUpdates() {
  updateChecking.value = true
  updateResult.value = null
  try {
    const data = await get('/api/system/update/check')
    updateInfo.value = data
    if (!data.update_available && !data.error) {
      notify.addToast('You are running the latest version', 'success')
    }
  } catch (e) {
    notify.addToast('Update check failed: ' + e.message, 'danger')
  } finally {
    updateChecking.value = false
  }
}

async function applyUpdate() {
  if (!await modals.confirm(
    `Update NOBA to v${updateInfo.value.remote_version}? ` +
    `This will pull ${updateInfo.value.commits_behind} commit(s), rebuild, and restart the service.`
  )) return
  updateApplying.value = true
  updateResult.value = null
  try {
    const data = await post('/api/system/update/apply', {})
    updateResult.value = data
    notify.addToast('Update applied — restarting...', 'success')
    // Reload the page after the service restarts
    setTimeout(() => { window.location.reload() }, UPDATE_RELOAD_DELAY_MS)
  } catch (e) {
    notify.addToast('Update failed: ' + e.message, 'danger')
    updateResult.value = { status: 'error', message: e.message }
  } finally {
    updateApplying.value = false
  }
}

onMounted(async () => {
  if (!settingsStore.loaded) await settingsStore.fetchSettings()
  if (authStore.isAdmin) checkForUpdates()
})

async function save() {
  saving.value = true
  saveMsg.value = ''
  try {
    await settingsStore.saveSettings()
    notify.addToast('Settings saved', 'success')
  } catch (e) {
    notify.addToast('Save failed: ' + (e.message || 'Unknown error'), 'danger')
  } finally {
    saving.value = false
  }
}

async function downloadConfigBackup() {
  try {
    const res = await download('/api/settings/backup')
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = 'config.yaml'; a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    notify.addToast('Download failed: ' + e.message, 'danger')
  }
}

async function uploadConfigRestore(evt) {
  const file = evt.target.files[0]
  if (!file) return
  const formData = new FormData()
  formData.append('file', file)
  try {
    await request('/api/settings/restore', { method: 'POST', body: formData })
    notify.addToast('Config restored — reload to apply', 'success')
  } catch (e) {
    notify.addToast('Restore failed: ' + e.message, 'danger')
  }
}

function resetWelcome() {
  localStorage.removeItem('noba:welcome_dismissed')
  notify.addToast('Setup wizard will show on your next dashboard visit.', 'success')
}

async function resetLayout() {
  if (!await modals.confirm('Reset your dashboard layout to the factory defaults?')) return
  try {
    await del('/api/user/preferences')
    saveMsg.value = 'Layout reset to defaults.'
    setTimeout(() => { saveMsg.value = '' }, 2500)
  } catch (e) {
    saveMsg.value = 'Reset failed: ' + e.message
  }
}
</script>

<template>
  <div>
    <!-- System Update (admin only) -->
    <div v-if="authStore.isAdmin" class="s-section">
      <span class="s-label">System Update</span>
      <div style="display:flex;flex-direction:column;gap:.6rem">
        <div style="display:flex;align-items:center;gap:.75rem;flex-wrap:wrap">
          <span style="font-size:.85rem">
            Current: <strong>v{{ updateInfo?.current_version || '...' }}</strong>
          </span>
          <span
            v-if="updateInfo?.update_available"
            style="font-size:.85rem;color:var(--accent);font-weight:600"
          >
            <i class="fas fa-arrow-right" style="font-size:.6rem"></i>
            v{{ updateInfo.remote_version }} available
            <span v-if="updateInfo.commits_behind" style="opacity:.6;font-weight:400">({{ updateInfo.commits_behind }} commit{{ updateInfo.commits_behind === 1 ? '' : 's' }})</span>
          </span>
          <span v-else-if="updateInfo && !updateInfo.error" style="font-size:.8rem;color:var(--success)">
            <i class="fas fa-check"></i> Up to date
          </span>
          <span v-if="updateInfo?.error" style="font-size:.8rem;color:var(--danger)">
            <i class="fas fa-exclamation-triangle"></i> {{ updateInfo.error }}
          </span>
        </div>

        <!-- Changelog -->
        <div v-if="updateInfo?.changelog?.length" style="font-size:.75rem;max-height:120px;overflow-y:auto;background:var(--bg);border:1px solid var(--border);border-radius:4px;padding:.5rem .75rem;font-family:var(--font-data)">
          <div v-for="(line, i) in updateInfo.changelog" :key="i" style="padding:1px 0;opacity:.8">{{ line }}</div>
        </div>

        <!-- Docker update instructions -->
        <div v-if="updateInfo?.docker && updateInfo?.update_available" style="font-size:.8rem;background:var(--bg);border:1px solid var(--border);border-radius:4px;padding:.75rem 1rem">
          <div style="font-weight:600;margin-bottom:.5rem;color:var(--accent)">
            <i class="fas fa-docker"></i> Docker Update Instructions
          </div>
          <div style="font-family:var(--font-data);line-height:1.8">
            <div v-for="(cmd, i) in updateInfo.docker_instructions" :key="i" style="padding:2px 0;opacity:.9">
              <code style="background:var(--surface-2);padding:2px 6px;border-radius:3px">{{ cmd }}</code>
            </div>
          </div>
        </div>

        <div style="display:flex;gap:.5rem;flex-wrap:wrap">
          <button class="btn" @click="checkForUpdates" :disabled="updateChecking">
            <i class="fas" :class="updateChecking ? 'fa-spinner fa-spin' : 'fa-sync-alt'"></i>
            {{ updateChecking ? 'Checking...' : 'Check for Updates' }}
          </button>
          <button
            v-if="updateInfo?.update_available && !updateInfo?.docker"
            class="btn btn-primary"
            @click="applyUpdate"
            :disabled="updateApplying"
          >
            <i class="fas" :class="updateApplying ? 'fa-spinner fa-spin' : 'fa-download'"></i>
            {{ updateApplying ? 'Updating...' : 'Update Now' }}
          </button>
        </div>

        <!-- Update result -->
        <div v-if="updateApplying" style="font-size:.8rem;color:var(--text-muted)">
          <i class="fas fa-spinner fa-spin"></i>
          Pulling, rebuilding, and restarting — page will reload automatically...
        </div>
      </div>
    </div>

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
          <label class="field-label" for="s-bookmarks">Quick Links</label>
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
            v-model="settingsStore.data.lanTestIp" placeholder="192.168.1.1">
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

    <!-- Re-run onboarding -->
    <div class="s-section">
      <span class="s-label">Setup Wizard</span>
      <p class="help-text" style="margin-bottom:.6rem">
        Re-run the first-time onboarding checklist on the dashboard.
      </p>
      <button class="btn btn-sm" @click="resetWelcome">
        <i class="fas fa-magic"></i> Re-run Setup Wizard
      </button>
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
