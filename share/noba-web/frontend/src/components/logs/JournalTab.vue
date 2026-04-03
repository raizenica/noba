<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref } from 'vue'
import { useApi } from '../../composables/useApi'
import { useNotificationsStore } from '../../stores/notifications'

const { get } = useApi()
const notif   = useNotificationsStore()

const journalUnit     = ref('')
const journalPriority = ref('')
const journalLines    = ref(100)
const journalGrep     = ref('')
const journalOutput   = ref('')
const journalLoading  = ref(false)
const journalUnits    = ref([])

async function fetchJournalUnits() {
  try {
    const data = await get('/api/journal/units')
    journalUnits.value = Array.isArray(data) ? data : []
  } catch (e) { notif.addToast('Failed to load journal units: ' + e.message, 'danger') }
}

async function fetchJournal() {
  journalLoading.value = true
  try {
    const params = new URLSearchParams({ lines: String(journalLines.value) })
    if (journalUnit.value)     params.set('unit',     journalUnit.value)
    if (journalPriority.value) params.set('priority', journalPriority.value)
    if (journalGrep.value)     params.set('grep',     journalGrep.value)
    const text = await get(`/api/journal?${params}`)
    journalOutput.value = typeof text === 'string' ? text : JSON.stringify(text, null, 2)
  } catch (e) {
    journalOutput.value = 'Error: ' + e.message
  } finally {
    journalLoading.value = false
  }
}

defineExpose({ fetchJournalUnits, fetchJournal })
</script>

<template>
  <div>
    <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:1rem;font-size:.8rem;align-items:flex-end">
      <select
        v-model="journalUnit"
        style="background:var(--surface-2);border:1px solid var(--border);color:var(--text);padding:3px 6px;border-radius:4px"
      >
        <option value="">All units</option>
        <option v-for="u in journalUnits" :key="u.name || u" :value="u.name || u">
          {{ u.name || u }}
        </option>
      </select>
      <select
        v-model="journalPriority"
        style="background:var(--surface-2);border:1px solid var(--border);color:var(--text);padding:3px 6px;border-radius:4px"
      >
        <option value="">All priorities</option>
        <option value="0">Emergency</option>
        <option value="1">Alert</option>
        <option value="2">Critical</option>
        <option value="3">Error</option>
        <option value="4">Warning</option>
        <option value="5">Notice</option>
        <option value="6">Info</option>
        <option value="7">Debug</option>
      </select>
      <input
        v-model="journalGrep"
        type="text"
        placeholder="grep..."
        style="width:120px;padding:3px 6px;background:var(--surface-2);border:1px solid var(--border);color:var(--text);border-radius:4px"
      >
      <select
        v-model.number="journalLines"
        style="background:var(--surface-2);border:1px solid var(--border);color:var(--text);padding:3px 6px;border-radius:4px"
      >
        <option :value="50">50 lines</option>
        <option :value="100">100</option>
        <option :value="200">200</option>
        <option :value="500">500</option>
      </select>
      <button class="btn btn-xs" :disabled="journalLoading" @click="fetchJournal">
        <i class="fas" :class="journalLoading ? 'fa-spinner fa-spin' : 'fa-search'"></i> Query
      </button>
    </div>
    <pre
      class="log-pre"
      style="max-height:50vh;overflow:auto;margin:0;padding:12px;font-size:.75rem;white-space:pre-wrap;word-break:break-all"
    >{{ journalOutput || 'No output. Press Query to fetch journal entries.' }}</pre>
  </div>
</template>
