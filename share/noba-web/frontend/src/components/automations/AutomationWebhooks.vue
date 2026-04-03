<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref } from 'vue'
import { useApi } from '../../composables/useApi'
import { useNotificationsStore } from '../../stores/notifications'
import { useModalsStore } from '../../stores/modals'
import AppModal from '../ui/AppModal.vue'

const props = defineProps({
  automations: Array, // full list for name lookup
})

const notify = useNotificationsStore()
const modals = useModalsStore()
const { get, post, del } = useApi()

const webhookList        = ref([])
const webhookListLoading = ref(false)
const showWebhookModal   = ref(false)
const lastCreatedWebhook = ref(null)
const newWebhookName     = ref('')
const newWebhookAutoId   = ref('')

async function fetchWebhooks() {
  webhookListLoading.value = true
  try { const data = await get('/api/webhooks'); webhookList.value = Array.isArray(data) ? data : [] }
  catch (e) { notify.addToast('Failed to load webhooks: ' + e.message, 'error') }
  finally { webhookListLoading.value = false }
}

async function createWebhook() {
  if (!newWebhookName.value.trim()) { notify.addToast('Name is required', 'error'); return }
  try {
    const data = await post('/api/webhooks', { name: newWebhookName.value.trim(), automation_id: newWebhookAutoId.value || null })
    lastCreatedWebhook.value = data; await fetchWebhooks(); notify.addToast('Webhook created', 'success')
  } catch (e) { notify.addToast('Create webhook failed: ' + e.message, 'error') }
}

async function deleteWebhook(wh) {
  if (!await modals.confirm(`Delete webhook "${wh.name}"?`)) return
  try { await del(`/api/webhooks/${wh.id}`); notify.addToast('Webhook deleted', 'success'); await fetchWebhooks() }
  catch (e) { notify.addToast('Delete webhook failed: ' + e.message, 'error') }
}

function webhookUrl(hookId) { return `${window.location.origin}/hooks/${hookId}` }

async function copyToClipboard(text) {
  try { await navigator.clipboard.writeText(text); notify.addToast('Copied to clipboard', 'success') }
  catch { notify.addToast('Copy failed', 'error') }
}

function openWebhookModal() {
  newWebhookName.value = ''; newWebhookAutoId.value = ''; lastCreatedWebhook.value = null
  showWebhookModal.value = true
}

function autoName(id) {
  return ((props.automations || []).find(a => a.id === id) || {}).name || id || ''
}

defineExpose({ fetchWebhooks })
</script>

<template>
  <div style="margin-top:.5rem">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:.6rem">
      <h3 style="margin:0;font-size:.9rem"><i class="fas fa-link" style="margin-right:.4rem"></i>Webhooks</h3>
      <div style="display:flex;gap:.4rem">
        <button class="btn btn-sm btn-primary" @click="openWebhookModal"><i class="fas fa-plus" style="margin-right:.3rem"></i>New Webhook</button>
        <button class="btn btn-sm" :disabled="webhookListLoading" @click="fetchWebhooks">
          <i class="fas" :class="webhookListLoading ? 'fa-spinner fa-spin' : 'fa-sync-alt'"></i>
        </button>
      </div>
    </div>

    <div v-if="webhookListLoading" class="empty-msg">Loading...</div>
    <div v-else-if="webhookList.length === 0" class="empty-msg">No webhooks configured. Create one to receive external triggers.</div>
    <div v-else style="overflow-x:auto">
      <table style="width:100%;font-size:.78rem;border-collapse:collapse">
        <thead>
          <tr style="border-bottom:1px solid var(--border)">
            <th style="padding:.4rem;text-align:left">Name</th>
            <th style="padding:.4rem;text-align:left">URL</th>
            <th style="padding:.4rem;text-align:left">Automation</th>
            <th style="padding:.4rem;text-align:center">Triggers</th>
            <th style="padding:.4rem;text-align:center">Last Triggered</th>
            <th style="padding:.4rem;text-align:center">Enabled</th>
            <th style="padding:.4rem;text-align:center">Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="wh in webhookList" :key="wh.id" style="border-bottom:1px solid var(--border)">
            <td style="padding:.4rem;font-weight:500">{{ wh.name }}</td>
            <td style="padding:.4rem">
              <code style="font-size:.65rem;background:var(--surface);padding:1px 4px;border-radius:3px;word-break:break-all">{{ webhookUrl(wh.hook_id) }}</code>
              <button class="btn btn-xs" style="margin-left:.3rem;padding:1px 4px" title="Copy URL" @click="copyToClipboard(webhookUrl(wh.hook_id))"><i class="fas fa-copy"></i></button>
            </td>
            <td style="padding:.4rem;font-size:.75rem">{{ wh.automation_id ? autoName(wh.automation_id) : '(none)' }}</td>
            <td style="padding:.4rem;text-align:center">{{ wh.trigger_count || 0 }}</td>
            <td style="padding:.4rem;text-align:center;font-size:.7rem">{{ wh.last_triggered ? new Date(wh.last_triggered * 1000).toLocaleString() : 'Never' }}</td>
            <td style="padding:.4rem;text-align:center">
              <span class="badge" :class="wh.enabled ? 'bs' : 'bw'" style="font-size:.55rem">{{ wh.enabled ? 'Yes' : 'No' }}</span>
            </td>
            <td style="padding:.4rem;text-align:center">
              <button class="btn btn-xs btn-danger" title="Delete" @click="deleteWebhook(wh)"><i class="fas fa-trash"></i></button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Webhook create modal -->
    <AppModal :show="showWebhookModal" title="Create Webhook" width="500px" @close="showWebhookModal = false">
      <div style="padding:1rem;display:flex;flex-direction:column;gap:.75rem">
        <div>
          <label class="field-label">Name</label>
          <input v-model="newWebhookName" type="text" class="field-input" placeholder="GitHub Deploy Hook" style="width:100%" />
        </div>
        <div>
          <label class="field-label">Linked Automation (optional)</label>
          <select v-model="newWebhookAutoId" class="field-input" style="width:100%">
            <option value="">None</option>
            <option v-for="a in automations" :key="a.id" :value="a.id">{{ a.name }} ({{ a.type }})</option>
          </select>
        </div>
        <div v-if="lastCreatedWebhook" style="padding:.6rem;background:var(--surface);border:1px solid var(--border);border-radius:6px">
          <div style="font-weight:600;font-size:.8rem;margin-bottom:.4rem;color:var(--success)"><i class="fas fa-check-circle"></i> Webhook Created</div>
          <label class="field-label">Webhook URL</label>
          <div style="display:flex;gap:.3rem;margin-bottom:.5rem">
            <code style="flex:1;font-size:.65rem;background:var(--surface-2);padding:4px 6px;border-radius:3px;word-break:break-all">{{ webhookUrl(lastCreatedWebhook.hook_id) }}</code>
            <button class="btn btn-xs" @click="copyToClipboard(webhookUrl(lastCreatedWebhook.hook_id))"><i class="fas fa-copy"></i></button>
          </div>
          <label class="field-label">Secret (for HMAC-SHA256 signing)</label>
          <div style="display:flex;gap:.3rem">
            <code style="flex:1;font-size:.65rem;background:var(--surface-2);padding:4px 6px;border-radius:3px;word-break:break-all">{{ lastCreatedWebhook.secret }}</code>
            <button class="btn btn-xs" @click="copyToClipboard(lastCreatedWebhook.secret)"><i class="fas fa-copy"></i></button>
          </div>
          <div style="font-size:.65rem;color:var(--text-muted);margin-top:.4rem"><i class="fas fa-info-circle"></i> Save the secret now. It will not be shown again.</div>
        </div>
      </div>
      <template #footer>
        <button class="btn" @click="showWebhookModal = false">Close</button>
        <button v-if="!lastCreatedWebhook" class="btn btn-primary" @click="createWebhook"><i class="fas fa-plus" style="margin-right:.3rem"></i>Create</button>
      </template>
    </AppModal>
  </div>
</template>

<style scoped>
.field-input {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text);
  padding: .4rem .5rem;
  font-size: .85rem;
  box-sizing: border-box;
}
.field-input:focus { outline: none; border-color: var(--accent); }
</style>
