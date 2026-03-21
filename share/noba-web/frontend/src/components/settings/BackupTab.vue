<script setup>
import { ref, onMounted } from 'vue'
import { useSettingsStore } from '../../stores/settings'
import { useApi } from '../../composables/useApi'

const settingsStore = useSettingsStore()
const { get, post } = useApi()

const saving = ref(false)
const saveMsg = ref('')

// Backup 3-2-1 status
const backup321Status = ref([])
const backup321Loading = ref(false)

// Backup verifications
const backupVerifications = ref([])
const backupVerifLoading = ref(false)

// Cloud remotes
const cloudRemotes = ref([])
const cloudRemotesLoading = ref(false)
const rcloneAvailable = ref(null)

// Verify form
const verifyForm = ref({ hostname: '', verification_type: 'checksum', path: '' })
const verifyLoading = ref(false)

// Organize custom rules
const newOrgExt = ref('')
const newOrgCat = ref('')

// New backup source input
const newBackupSource = ref('')

onMounted(async () => {
  if (!settingsStore.loaded) await settingsStore.fetchSettings()
  fetchBackup321Status()
  fetchBackupVerifications()
  fetchCloudRemotes()
})

async function fetchBackup321Status() {
  backup321Loading.value = true
  try {
    const d = await get('/api/backup/321-status')
    backup321Status.value = Array.isArray(d) ? d : []
  } catch { /* silent */ }
  finally { backup321Loading.value = false }
}

async function fetchBackupVerifications() {
  backupVerifLoading.value = true
  try {
    const d = await get('/api/backup/verifications')
    backupVerifications.value = Array.isArray(d) ? d : []
  } catch { /* silent */ }
  finally { backupVerifLoading.value = false }
}

async function fetchCloudRemotes() {
  cloudRemotesLoading.value = true
  try {
    const d = await get('/api/cloud-remotes')
    rcloneAvailable.value = d.available ?? true
    cloudRemotes.value = d.remotes ?? (Array.isArray(d) ? d : [])
  } catch { /* silent */ }
  finally { cloudRemotesLoading.value = false }
}

async function triggerBackupVerify() {
  verifyLoading.value = true
  try {
    await post('/api/backup/verify', { ...verifyForm.value })
    await fetchBackupVerifications()
  } catch { /* silent */ }
  finally { verifyLoading.value = false }
}

function addBackupSource() {
  const src = (newBackupSource.value || '').trim()
  if (!src) return
  if (!Array.isArray(settingsStore.data.backupSources)) settingsStore.data.backupSources = []
  if (!settingsStore.data.backupSources.includes(src)) {
    settingsStore.data.backupSources.push(src)
  }
  newBackupSource.value = ''
}

function removeBackupSource(idx) {
  if (Array.isArray(settingsStore.data.backupSources)) {
    settingsStore.data.backupSources.splice(idx, 1)
  }
}

function addOrgRule() {
  const ext = (newOrgExt.value || '').replace(/^\./, '').trim()
  const cat = (newOrgCat.value || '').trim()
  if (!ext || !cat) return
  const rule = ext + ':' + cat
  if (!Array.isArray(settingsStore.data.organizeCustomRules)) settingsStore.data.organizeCustomRules = []
  if (!settingsStore.data.organizeCustomRules.includes(rule)) {
    settingsStore.data.organizeCustomRules.push(rule)
  }
  newOrgExt.value = ''
  newOrgCat.value = ''
}

function removeOrgRule(idx) {
  if (Array.isArray(settingsStore.data.organizeCustomRules)) {
    settingsStore.data.organizeCustomRules.splice(idx, 1)
  }
}

function backupFreshnessClass(ts) {
  if (!ts) return 'bd'
  const ageH = (Date.now() / 1000 - ts) / 3600
  if (ageH < 25) return 'bs'
  if (ageH < 73) return 'bw'
  return 'bd'
}

function backupFreshnessLabel(ts) {
  if (!ts) return 'Never'
  const ageH = (Date.now() / 1000 - ts) / 3600
  if (ageH < 1) return 'Just now'
  if (ageH < 25) return Math.floor(ageH) + 'h ago'
  return Math.floor(ageH / 24) + 'd ago'
}

function humanBytes(b) {
  if (!b) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  let v = b
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++ }
  return v.toFixed(1) + ' ' + units[i]
}

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
</script>

<template>
  <div>
    <!-- Backup Sources -->
    <div class="s-section">
      <span class="s-label">Backup Sources</span>
      <p class="help-text" style="margin-bottom:.6rem">Directories to include in NAS backups. One path per entry.</p>
      <div style="display:flex;flex-direction:column;gap:.4rem;margin-bottom:.6rem">
        <div
          v-for="(src, idx) in (settingsStore.data.backupSources || [])"
          :key="idx"
          style="display:flex;align-items:center;gap:.4rem"
        >
          <code style="flex:1;padding:.35rem .5rem;background:var(--surface-2);border-radius:4px;font-size:.78rem;overflow:hidden;text-overflow:ellipsis">{{ src }}</code>
          <button class="btn btn-sm" style="padding:.25rem .5rem;flex-shrink:0" @click="removeBackupSource(idx)" title="Remove">
            <i class="fas fa-times"></i>
          </button>
        </div>
        <div v-if="!settingsStore.data.backupSources || settingsStore.data.backupSources.length === 0" style="color:var(--text-muted);font-size:.78rem">
          No sources configured.
        </div>
      </div>
      <div style="display:flex;gap:.4rem">
        <input class="field-input" type="text" v-model="newBackupSource" placeholder="/path/to/directory"
          @keydown.enter.prevent="addBackupSource" style="flex:1">
        <button class="btn btn-sm" @click="addBackupSource"><i class="fas fa-plus"></i> Add</button>
      </div>
    </div>

    <!-- Destination -->
    <div class="s-section">
      <span class="s-label">Backup Destination</span>
      <p class="help-text" style="margin-bottom:.6rem">NAS mount point or local path where backups are stored.</p>
      <input class="field-input" type="text" v-model="settingsStore.data.backupDest" placeholder="/mnt/nas/backups">
    </div>

    <!-- Retention & Safety -->
    <div class="s-section">
      <span class="s-label">Retention &amp; Safety</span>
      <div class="field-2">
        <div>
          <label class="field-label">Retention Days</label>
          <input class="field-input" type="number" min="1" v-model.number="settingsStore.data.backupRetentionDays" placeholder="7">
        </div>
        <div>
          <label class="field-label">Keep Count (min snapshots)</label>
          <input class="field-input" type="number" min="0" v-model.number="settingsStore.data.backupKeepCount" placeholder="0">
        </div>
      </div>
      <div class="field-2" style="margin-top:.6rem">
        <div>
          <label class="field-label">Verify Sample Size</label>
          <input class="field-input" type="number" min="0" v-model.number="settingsStore.data.backupVerifySample" placeholder="20">
        </div>
        <div>
          <label class="field-label">Max Delete (rsync safety)</label>
          <input class="field-input" type="text" v-model="settingsStore.data.backupMaxDelete" placeholder="Empty = no limit">
        </div>
      </div>
    </div>

    <!-- Email Reports -->
    <div class="s-section">
      <span class="s-label">Backup Email Reports</span>
      <p class="help-text" style="margin-bottom:.6rem">Email address for backup completion reports.</p>
      <input class="field-input" type="email" v-model="settingsStore.data.backupEmail" placeholder="admin@example.com">
    </div>

    <!-- 3-2-1 Backup Compliance -->
    <div class="s-section">
      <span class="s-label">3-2-1 Backup Compliance</span>
      <p class="help-text" style="margin-bottom:.6rem">Track that your backups follow the 3-2-1 rule: 3 copies, 2 media types, 1 offsite.</p>
      <div v-if="backup321Status.length === 0 && !backup321Loading" style="color:var(--text-muted);font-size:.78rem;margin-bottom:.5rem">
        No backups tracked yet.
      </div>
      <div style="display:flex;flex-direction:column;gap:.5rem;margin-bottom:.6rem">
        <div
          v-for="entry in backup321Status"
          :key="entry.id"
          style="padding:.5rem .65rem;background:var(--surface-2);border-radius:4px;font-size:.78rem"
        >
          <div style="display:flex;align-items:center;gap:.5rem;margin-bottom:.3rem">
            <strong style="flex:1">{{ entry.backup_name }}</strong>
            <span class="badge" :class="backupFreshnessClass(entry.last_verified)" style="font-size:.65rem">
              {{ backupFreshnessLabel(entry.last_verified) }}
            </span>
          </div>
          <div style="display:flex;gap:.8rem;align-items:center;flex-wrap:wrap">
            <span :style="'color:' + (entry.copies >= 3 ? 'var(--success)' : 'var(--danger)')">
              <i class="fas" :class="entry.copies >= 3 ? 'fa-check-circle' : 'fa-times-circle'"></i>
              {{ entry.copies }} copies
            </span>
            <span :style="'color:' + ((entry.media_types && entry.media_types.length >= 2) ? 'var(--success)' : 'var(--danger)')">
              <i class="fas" :class="(entry.media_types && entry.media_types.length >= 2) ? 'fa-check-circle' : 'fa-times-circle'"></i>
              {{ entry.media_types ? entry.media_types.length : 0 }} media
            </span>
            <span :style="'color:' + (entry.has_offsite ? 'var(--success)' : 'var(--danger)')">
              <i class="fas" :class="entry.has_offsite ? 'fa-check-circle' : 'fa-times-circle'"></i>
              {{ entry.has_offsite ? 'Offsite' : 'No offsite' }}
            </span>
          </div>
        </div>
      </div>
      <button class="btn btn-sm" @click="fetchBackup321Status">
        <i class="fas fa-sync" :class="backup321Loading ? 'fa-spin' : ''"></i> Refresh
      </button>
    </div>

    <!-- Verify Now -->
    <div class="s-section">
      <span class="s-label">Verify Backup</span>
      <p class="help-text" style="margin-bottom:.6rem">Run a verification check on a backup file via an agent.</p>
      <div style="display:flex;flex-direction:column;gap:.5rem">
        <div class="field-2">
          <div>
            <label class="field-label">Agent Hostname</label>
            <input class="field-input" type="text" v-model="verifyForm.hostname" placeholder="server01">
          </div>
          <div>
            <label class="field-label">Verification Type</label>
            <select class="field-input field-select" v-model="verifyForm.verification_type">
              <option value="checksum">Checksum (SHA-256)</option>
              <option value="restore_test">Restore Test (tar/gz)</option>
              <option value="db_integrity">DB Integrity (SQLite)</option>
            </select>
          </div>
        </div>
        <div>
          <label class="field-label">Backup Path</label>
          <input class="field-input" type="text" v-model="verifyForm.path" placeholder="/mnt/nas/backups/latest.tar.gz">
        </div>
        <button class="btn btn-sm" @click="triggerBackupVerify" :disabled="verifyLoading">
          <i class="fas" :class="verifyLoading ? 'fa-spinner fa-spin' : 'fa-shield-alt'"></i>
          {{ verifyLoading ? 'Verifying...' : 'Verify Now' }}
        </button>
      </div>
    </div>

    <!-- Verification History -->
    <div class="s-section">
      <span class="s-label">Verification History</span>
      <p class="help-text" style="margin-bottom:.6rem">Recent backup integrity checks across all agents.</p>
      <div v-if="backupVerifLoading" style="color:var(--text-muted);font-size:.78rem">Loading...</div>
      <div v-else-if="backupVerifications.length === 0" style="color:var(--text-muted);font-size:.78rem">No verifications recorded yet.</div>
      <div v-else style="overflow-x:auto">
        <table style="width:100%;font-size:.75rem;border-collapse:collapse">
          <thead>
            <tr style="border-bottom:1px solid var(--border);text-align:left">
              <th style="padding:.25rem .4rem">Path</th>
              <th style="padding:.25rem .4rem">Agent</th>
              <th style="padding:.25rem .4rem">Type</th>
              <th style="padding:.25rem .4rem">Status</th>
              <th style="padding:.25rem .4rem">Date</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="v in backupVerifications" :key="v.id" style="border-bottom:1px solid var(--border)">
              <td style="padding:.25rem .4rem;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" :title="v.backup_path">{{ v.backup_path }}</td>
              <td style="padding:.25rem .4rem">{{ v.hostname }}</td>
              <td style="padding:.25rem .4rem"><span class="badge bn" style="font-size:.6rem">{{ v.verification_type }}</span></td>
              <td style="padding:.25rem .4rem">
                <span :class="v.status === 'ok' ? 'badge bs' : 'badge bd'" style="font-size:.6rem">{{ v.status === 'ok' ? 'PASS' : 'FAIL' }}</span>
              </td>
              <td style="padding:.25rem .4rem;white-space:nowrap">{{ v.verified_at ? new Date(v.verified_at * 1000).toLocaleString() : '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <button class="btn btn-sm" style="margin-top:.5rem" @click="fetchBackupVerifications">
        <i class="fas fa-sync" :class="backupVerifLoading ? 'fa-spin' : ''"></i> Refresh
      </button>
    </div>

    <!-- Organize Downloads -->
    <div class="s-section">
      <span class="s-label">Organize Downloads</span>
      <p class="help-text" style="margin-bottom:.6rem">Configure how the Organize Downloads job sorts files into category folders.</p>
      <div style="display:flex;flex-direction:column;gap:.7rem">
        <div>
          <label class="field-label">Target Directory</label>
          <input class="field-input" type="text" v-model="settingsStore.data.downloadsDir" placeholder="/home/user/Downloads">
        </div>
        <div class="field-2">
          <div>
            <label class="field-label">Scan Depth</label>
            <select class="field-input field-select" v-model.number="settingsStore.data.organizeMaxDepth">
              <option :value="1">1 — Top level only</option>
              <option :value="2">2 — One subfolder deep</option>
              <option :value="3">3 — Two subfolders deep</option>
              <option :value="5">5 — Deep scan</option>
            </select>
          </div>
          <div>
            <label class="field-label">Exclude Patterns</label>
            <input class="field-input" type="text" v-model="settingsStore.data.organizeExclude" placeholder="*.part, *.crdownload">
            <p class="help-text">Comma-separated globs to skip.</p>
          </div>
        </div>
        <!-- Custom Rules -->
        <div>
          <label class="field-label">Custom Rules</label>
          <p class="help-text" style="margin-bottom:.4rem">Add new file extensions or create your own categories.</p>
          <div v-if="settingsStore.data.organizeCustomRules && settingsStore.data.organizeCustomRules.length > 0" style="margin-bottom:.5rem">
            <table style="width:100%;font-size:.78rem;border-collapse:collapse">
              <thead>
                <tr style="border-bottom:1px solid var(--border);text-align:left">
                  <th style="padding:.25rem .4rem">Extension</th>
                  <th style="padding:.25rem .4rem">Category</th>
                  <th style="padding:.25rem .4rem;width:2rem"></th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(rule, idx) in settingsStore.data.organizeCustomRules" :key="idx" style="border-bottom:1px solid var(--border)">
                  <td style="padding:.25rem .4rem;font-family:var(--font-data)">{{ rule.split(':')[0] || '' }}</td>
                  <td style="padding:.25rem .4rem">{{ rule.split(':')[1] || '' }}</td>
                  <td style="padding:.25rem .4rem;text-align:center">
                    <button style="background:none;border:none;color:var(--danger);cursor:pointer" @click="removeOrgRule(idx)">&times;</button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div style="display:flex;gap:.4rem;align-items:flex-end">
            <div style="flex:1">
              <label class="field-label" style="font-size:.65rem">Extension</label>
              <input class="field-input" type="text" v-model="newOrgExt" placeholder="blend" style="font-size:.78rem">
            </div>
            <div style="flex:1">
              <label class="field-label" style="font-size:.65rem">Category</label>
              <input class="field-input" type="text" v-model="newOrgCat" placeholder="3DModels" style="font-size:.78rem" list="org-cat-list">
              <datalist id="org-cat-list">
                <option value="Images"></option>
                <option value="Video"></option>
                <option value="Audio"></option>
                <option value="Documents"></option>
                <option value="Archives"></option>
                <option value="DiskImages"></option>
                <option value="Executables"></option>
                <option value="Code"></option>
                <option value="Fonts"></option>
                <option value="Torrents"></option>
                <option value="Other"></option>
              </datalist>
            </div>
            <button class="btn btn-sm" style="margin-bottom:1px" @click="addOrgRule">
              <i class="fas fa-plus"></i> Add
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Cloud Remotes -->
    <div class="s-section">
      <span class="s-label">Cloud Remotes</span>
      <div v-if="rcloneAvailable === false" style="color:var(--danger);font-size:.82rem;margin-bottom:.5rem">
        <i class="fas fa-times-circle"></i> rclone is not installed.
      </div>
      <div v-else-if="cloudRemotes.length > 0">
        <p class="help-text" style="margin-bottom:.5rem">Remotes detected from rclone config.</p>
        <div style="display:flex;flex-direction:column;gap:.4rem;margin-bottom:.5rem">
          <div
            v-for="r in cloudRemotes" :key="r.name"
            style="display:flex;align-items:center;gap:.5rem;padding:.4rem .6rem;background:var(--surface-2);border-radius:4px;border-left:3px solid"
            :style="'border-color:' + (r.color || 'var(--accent)')"
          >
            <i :class="r.icon" :style="'color:' + (r.color || 'var(--accent)')" style="width:1rem;text-align:center"></i>
            <span style="font-size:.82rem;font-weight:600">{{ r.name }}</span>
            <span class="badge" style="font-size:.6rem" :style="'background:' + (r.color||'var(--accent)') + '22;color:' + (r.color||'var(--accent)')">{{ r.label }}</span>
            <div v-if="r.quota" style="margin-left:auto;font-size:.65rem;color:var(--text-muted)">
              {{ humanBytes(r.quota.used) }} / {{ humanBytes(r.quota.total) }}
            </div>
          </div>
        </div>
      </div>
      <div v-else-if="rcloneAvailable !== false" style="color:var(--warning);font-size:.82rem;margin-bottom:.5rem">
        <i class="fas fa-exclamation-triangle"></i> No remotes configured. Run <code>rclone config</code>.
      </div>
      <button class="btn btn-sm" @click="fetchCloudRemotes">
        <i class="fas fa-sync" :class="cloudRemotesLoading ? 'fa-spin' : ''"></i> Refresh Remotes
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
