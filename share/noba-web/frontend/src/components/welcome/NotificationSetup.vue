<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref } from 'vue'
import { useSettingsStore } from '../../stores/settings'
import { useApi } from '../../composables/useApi'

const emit = defineEmits(['done', 'cancel'])
const settingsStore = useSettingsStore()
const { post } = useApi()

const channel = ref('')
const testing = ref(false)
const testResult = ref(null)
const saving = ref(false)

// Pushover
const pushoverAppToken = ref(settingsStore.data.pushoverAppToken || '')
const pushoverUserKey = ref(settingsStore.data.pushoverUserKey || '')

// Gotify
const gotifyUrl = ref(settingsStore.data.gotifyUrl || '')
const gotifyAppToken = ref(settingsStore.data.gotifyAppToken || '')

const channels = [
  { key: 'pushover', label: 'Pushover', icon: 'fa-mobile-alt', desc: 'Push notifications to your phone. Requires a Pushover account.' },
  { key: 'gotify', label: 'Gotify', icon: 'fa-server', desc: 'Self-hosted push notifications. Requires a Gotify server.' },
]

const canSave = ref(false)

function selectChannel(ch) {
  channel.value = ch
  testResult.value = null
}

function checkCanSave() {
  if (channel.value === 'pushover') {
    canSave.value = !!(pushoverAppToken.value.trim() && pushoverUserKey.value.trim())
  } else if (channel.value === 'gotify') {
    canSave.value = !!(gotifyUrl.value.trim() && gotifyAppToken.value.trim())
  }
}

async function testNotification() {
  testing.value = true
  testResult.value = null
  try {
    await post('/api/notifications/test')
    testResult.value = { ok: true, msg: 'Test notification sent!' }
  } catch (e) {
    testResult.value = { ok: false, msg: 'Failed — check your credentials.' }
  } finally {
    testing.value = false
  }
}

async function save() {
  saving.value = true
  try {
    const updates = { ...settingsStore.data }
    if (channel.value === 'pushover') {
      updates.pushoverEnabled = true
      updates.pushoverAppToken = pushoverAppToken.value.trim()
      updates.pushoverUserKey = pushoverUserKey.value.trim()
    } else if (channel.value === 'gotify') {
      updates.gotifyEnabled = true
      updates.gotifyUrl = gotifyUrl.value.trim()
      updates.gotifyAppToken = gotifyAppToken.value.trim()
    }
    await settingsStore.saveSettings(updates)
    emit('done')
  } catch {
    testResult.value = { ok: false, msg: 'Failed to save.' }
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="notif-setup">
    <!-- Step 1: Pick channel -->
    <div v-if="!channel">
      <p class="setup-intro">Choose how you'd like to receive alerts when something needs attention:</p>
      <div class="channel-grid">
        <div
          v-for="ch in channels"
          :key="ch.key"
          class="channel-card"
          @click="selectChannel(ch.key)"
        >
          <i class="fas" :class="ch.icon" style="font-size:1.5rem;color:var(--accent)"></i>
          <div class="channel-name">{{ ch.label }}</div>
          <div class="channel-desc">{{ ch.desc }}</div>
        </div>
      </div>
      <div style="text-align:center;margin-top:1rem">
        <button class="btn btn-sm" @click="emit('cancel')">Skip for now</button>
      </div>
    </div>

    <!-- Step 2: Configure -->
    <div v-else>
      <button class="btn btn-xs" style="margin-bottom:1rem" @click="channel = ''; testResult = null">
        <i class="fas fa-arrow-left"></i> Back
      </button>

      <!-- Pushover -->
      <div v-if="channel === 'pushover'" class="config-form">
        <p class="setup-intro">
          Enter your Pushover credentials. Get them from
          <a href="https://pushover.net" target="_blank" rel="noopener">pushover.net</a>.
        </p>
        <label class="field-label">App Token</label>
        <input class="field-input" type="text" v-model="pushoverAppToken" placeholder="aTokenFromPushover" @input="checkCanSave" autocomplete="off">
        <label class="field-label" style="margin-top:.75rem">User Key</label>
        <input class="field-input" type="text" v-model="pushoverUserKey" placeholder="uKeyFromPushover" @input="checkCanSave" autocomplete="off">
      </div>

      <!-- Gotify -->
      <div v-if="channel === 'gotify'" class="config-form">
        <p class="setup-intro">
          Enter your Gotify server URL and an app token.
        </p>
        <label class="field-label">Server URL</label>
        <input class="field-input" type="url" v-model="gotifyUrl" placeholder="https://gotify.example.com" @input="checkCanSave" autocomplete="off">
        <label class="field-label" style="margin-top:.75rem">App Token</label>
        <input class="field-input" type="text" v-model="gotifyAppToken" placeholder="AbCdEf123456" @input="checkCanSave" autocomplete="off">
      </div>

      <!-- Test result -->
      <div v-if="testResult" class="test-result" :class="testResult.ok ? 'ok' : 'fail'" style="margin-top:.75rem">
        <i class="fas" :class="testResult.ok ? 'fa-check-circle' : 'fa-times-circle'"></i>
        {{ testResult.msg }}
      </div>

      <!-- Actions -->
      <div style="display:flex;gap:.5rem;margin-top:1.25rem;justify-content:flex-end">
        <button class="btn btn-sm" :disabled="!canSave || testing" @click="testNotification">
          <i class="fas fa-paper-plane"></i> {{ testing ? 'Testing...' : 'Test' }}
        </button>
        <button class="btn btn-sm btn-primary" :disabled="!canSave || saving" @click="save">
          <i class="fas fa-check"></i> {{ saving ? 'Saving...' : 'Save & Continue' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.notif-setup { padding: .5rem 0; }

.setup-intro {
  font-size: .85rem;
  color: var(--text-muted);
  line-height: 1.5;
  margin-bottom: 1rem;
}
.setup-intro a { color: var(--accent); }

.channel-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: .75rem;
}

.channel-card {
  padding: 1.25rem;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  cursor: pointer;
  text-align: center;
  transition: border-color .2s;
}
.channel-card:hover {
  border-color: var(--accent);
}

.channel-name {
  font-weight: 600;
  margin: .5rem 0 .25rem;
  color: var(--text);
}
.channel-desc {
  font-size: .75rem;
  color: var(--text-muted);
  line-height: 1.3;
}

.config-form { }

.test-result {
  padding: .5rem .75rem;
  border-radius: 4px;
  font-size: .85rem;
}
.test-result.ok { background: color-mix(in srgb, var(--success) 15%, var(--surface)); color: var(--success); }
.test-result.fail { background: color-mix(in srgb, var(--danger) 15%, var(--surface)); color: var(--danger); }
</style>
