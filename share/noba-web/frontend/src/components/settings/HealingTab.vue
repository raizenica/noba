<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useSettingsStore } from '../../stores/settings'

const settingsStore = useSettingsStore()

const saving = ref(false)
const saveMsg = ref('')

const cfg = reactive({
  // General
  enabled: true,
  cooldown_s: 300,
  circuit_breaker_threshold: 5,
  stale_data_multiplier: 2,
  // Approval Policy
  approval_stage1_m: 15,
  approval_stage2_m: 60,
  max_defers: 3,
  single_admin_cooldown_m: 5,
  // Predictive Healing
  predictive_enabled: false,
  predictive_interval_m: 15,
  horizon_24h: true,
  horizon_72h: false,
  // Notification Routing
  heal_channel: '',
  low_risk_notify: 'digest',
  medium_risk_immediate: true,
  high_risk_immediate: true,
  high_risk_alert: true,
})

onMounted(async () => {
  if (!settingsStore.loaded) await settingsStore.fetchSettings()
  const h = settingsStore.data.healing || {}
  Object.assign(cfg, h)
})

async function save() {
  saving.value = true
  saveMsg.value = ''
  try {
    settingsStore.data.healing = { ...cfg }
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
    <!-- General -->
    <div class="s-section">
      <span class="s-label">General</span>
      <div style="display:flex;flex-direction:column;gap:.7rem">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:1rem">
          <label class="field-label" style="margin:0">Pipeline Enabled</label>
          <label style="display:flex;align-items:center;gap:.5rem;cursor:pointer">
            <input type="checkbox" v-model="cfg.enabled" />
            <span style="font-size:.82rem;color:var(--text-muted)">
              {{ cfg.enabled ? 'Active' : 'Disabled' }}
            </span>
          </label>
        </div>
        <div class="field-2">
          <div>
            <label class="field-label">Global Cooldown (seconds)</label>
            <input type="number" v-model.number="cfg.cooldown_s" class="field-input" min="0" placeholder="300" />
          </div>
          <div>
            <label class="field-label">Circuit Breaker Threshold</label>
            <input type="number" v-model.number="cfg.circuit_breaker_threshold" class="field-input" min="1" max="20" placeholder="5" />
          </div>
        </div>
        <div>
          <label class="field-label">Stale Data Timeout Multiplier</label>
          <input type="number" v-model.number="cfg.stale_data_multiplier" class="field-input" min="1" max="10" step="0.5" placeholder="2" style="max-width:12rem" />
          <p style="font-size:.72rem;color:var(--text-muted);margin-top:.25rem">
            How many times the poll interval to wait before marking data stale (default: 2x).
          </p>
        </div>
      </div>
    </div>

    <!-- Approval Policy -->
    <div class="s-section">
      <span class="s-label">Approval Policy</span>
      <div class="field-2">
        <div>
          <label class="field-label">Stage 1 Timeout (minutes)</label>
          <input type="number" v-model.number="cfg.approval_stage1_m" class="field-input" min="1" placeholder="15" />
        </div>
        <div>
          <label class="field-label">Stage 2 Timeout (minutes)</label>
          <input type="number" v-model.number="cfg.approval_stage2_m" class="field-input" min="1" placeholder="60" />
        </div>
        <div>
          <label class="field-label">Max Defers</label>
          <input type="number" v-model.number="cfg.max_defers" class="field-input" min="0" max="10" placeholder="3" />
        </div>
        <div>
          <label class="field-label">Single-Admin Cooldown (minutes)</label>
          <input type="number" v-model.number="cfg.single_admin_cooldown_m" class="field-input" min="1" placeholder="5" />
          <p style="font-size:.72rem;color:var(--text-muted);margin-top:.25rem">
            Confirmation delay when only one admin is available to approve.
          </p>
        </div>
      </div>
    </div>

    <!-- Predictive Healing -->
    <div class="s-section">
      <span class="s-label">Predictive Healing</span>
      <div style="display:flex;flex-direction:column;gap:.7rem">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:1rem">
          <label class="field-label" style="margin:0">Enabled</label>
          <label style="display:flex;align-items:center;gap:.5rem;cursor:pointer">
            <input type="checkbox" v-model="cfg.predictive_enabled" />
            <span style="font-size:.82rem;color:var(--text-muted)">
              {{ cfg.predictive_enabled ? 'Active' : 'Disabled' }}
            </span>
          </label>
        </div>
        <div>
          <label class="field-label">Evaluation Interval (minutes)</label>
          <input type="number" v-model.number="cfg.predictive_interval_m" class="field-input" min="5" max="60" placeholder="15" style="max-width:12rem" />
        </div>
        <div style="display:flex;flex-direction:column;gap:.4rem">
          <label class="field-label">Prediction Horizons</label>
          <label style="display:flex;align-items:center;gap:.5rem;cursor:pointer;font-size:.82rem">
            <input type="checkbox" v-model="cfg.horizon_24h" />
            24-hour horizon
          </label>
          <label style="display:flex;align-items:center;gap:.5rem;cursor:pointer;font-size:.82rem">
            <input type="checkbox" v-model="cfg.horizon_72h" />
            72-hour horizon
          </label>
        </div>
      </div>
    </div>

    <!-- Notification Routing -->
    <div class="s-section">
      <span class="s-label">Notification Routing</span>
      <div style="display:flex;flex-direction:column;gap:.7rem">
        <div>
          <label class="field-label">Healing Channel</label>
          <input v-model="cfg.heal_channel" class="field-input" placeholder="e.g., heal-ops" style="max-width:20rem" />
          <p style="font-size:.72rem;color:var(--text-muted);margin-top:.25rem">
            Channel name used for healing-specific notifications (Slack, Discord, etc.).
          </p>
        </div>
        <div>
          <label class="field-label">Low-Risk Notifications</label>
          <select v-model="cfg.low_risk_notify" class="form-select" style="max-width:14rem">
            <option value="digest">Hourly Digest</option>
            <option value="immediate">Immediate</option>
            <option value="none">None</option>
          </select>
        </div>
        <div style="display:flex;flex-direction:column;gap:.4rem">
          <label class="field-label">Medium-Risk</label>
          <label style="display:flex;align-items:center;gap:.5rem;cursor:pointer;font-size:.82rem">
            <input type="checkbox" v-model="cfg.medium_risk_immediate" />
            Immediate notification
          </label>
        </div>
        <div style="display:flex;flex-direction:column;gap:.4rem">
          <label class="field-label">High-Risk</label>
          <label style="display:flex;align-items:center;gap:.5rem;cursor:pointer;font-size:.82rem">
            <input type="checkbox" v-model="cfg.high_risk_immediate" />
            Immediate notification
          </label>
          <label style="display:flex;align-items:center;gap:.5rem;cursor:pointer;font-size:.82rem">
            <input type="checkbox" v-model="cfg.high_risk_alert" />
            Escalate to alert
          </label>
        </div>
      </div>
    </div>

    <!-- Save -->
    <div style="margin-top:1.25rem;display:flex;gap:.75rem;align-items:center">
      <button class="btn btn-primary" :disabled="saving" @click="save">
        <i class="fas" :class="saving ? 'fa-spinner fa-spin' : 'fa-check'"></i>
        {{ saving ? 'Saving...' : 'Save Healing Settings' }}
      </button>
      <span v-if="saveMsg" style="font-size:.8rem;color:var(--text-muted)">{{ saveMsg }}</span>
    </div>
  </div>
</template>
