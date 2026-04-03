<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, computed } from 'vue'
import { useApi } from '../../composables/useApi'
import { useNotificationsStore } from '../../stores/notifications'
import DataTable from '../ui/DataTable.vue'

const { get } = useApi()
const notify   = useNotificationsStore()

const auditRows          = ref([])
const auditLoading       = ref(false)
const auditFilterType    = ref('')
const auditFilterOutcome = ref('')

const auditColumns = [
  { key: 'time',        label: 'Time'       },
  { key: 'trigger',     label: 'Trigger'    },
  { key: 'action_type', label: 'Action'     },
  { key: 'target',      label: 'Target'     },
  { key: 'outcome',     label: 'Outcome',   sortable: false },
  { key: 'duration_s',  label: 'Duration'   },
  { key: 'approved_by', label: 'Approved By'},
]

const filteredAuditRows = computed(() => {
  let rows = auditRows.value
  if (auditFilterType.value)    rows = rows.filter(r => r.trigger_type === auditFilterType.value)
  if (auditFilterOutcome.value) rows = rows.filter(r => r.outcome === auditFilterOutcome.value)
  return rows
})

const auditTriggerTypes = computed(() => {
  const s = new Set(auditRows.value.map(r => r.trigger_type).filter(Boolean))
  return [...s]
})

async function fetchAudit() {
  auditLoading.value = true
  try {
    const data = await get('/api/action-audit?limit=100')
    auditRows.value = Array.isArray(data) ? data : (data.entries || [])
  } catch (e) {
    notify.addToast('Failed to load audit log: ' + e.message, 'error')
  } finally {
    auditLoading.value = false
  }
}

function auditOutcomeClass(outcome) {
  if (outcome === 'success') return 'bs'
  if (outcome === 'failure' || outcome === 'error') return 'bd'
  return 'bn'
}

function formatAuditTime(row) {
  const ts = row.created_at || row.timestamp || row.time
  if (!ts) return '\u2014'
  const d = typeof ts === 'number' ? new Date(ts * 1000) : new Date(ts)
  return d.toLocaleString()
}

function formatTrigger(row) {
  const parts = [row.trigger_type, row.trigger_id].filter(Boolean)
  return parts.join(' / ') || '\u2014'
}

function formatApprovedBy(row) {
  if (row.approved_by) return row.approved_by
  if (row.outcome === 'success' && !row.approved_by) return 'auto'
  return 'system'
}

defineExpose({ fetchAudit })
</script>

<template>
  <div>
    <!-- Toolbar -->
    <div style="display:flex;gap:.5rem;flex-wrap:wrap;align-items:center;margin-bottom:.8rem">
      <select
        v-model="auditFilterType"
        class="field-select"
        style="width:auto;font-size:.78rem;padding:.25rem .5rem"
      >
        <option value="">All triggers</option>
        <option v-for="t in auditTriggerTypes" :key="t" :value="t">{{ t }}</option>
      </select>
      <select
        v-model="auditFilterOutcome"
        class="field-select"
        style="width:auto;font-size:.78rem;padding:.25rem .5rem"
      >
        <option value="">All outcomes</option>
        <option value="success">success</option>
        <option value="failure">failure</option>
        <option value="error">error</option>
      </select>
      <button
        class="btn btn-sm"
        style="margin-left:auto"
        :disabled="auditLoading"
        @click="fetchAudit"
      >
        <i class="fas" :class="auditLoading ? 'fa-spinner fa-spin' : 'fa-sync-alt'"></i>
        Refresh
      </button>
    </div>

    <div v-if="auditLoading" class="empty-msg">Loading...</div>
    <div v-else-if="filteredAuditRows.length === 0" class="empty-msg">No audit entries found.</div>
    <div v-else style="overflow-x:auto">
      <DataTable :columns="auditColumns" :rows="filteredAuditRows" :page-size="50">
        <template #cell-time="{ row }">
          {{ formatAuditTime(row) }}
        </template>
        <template #cell-trigger="{ row }">
          {{ formatTrigger(row) }}
        </template>
        <template #cell-outcome="{ row }">
          <span class="badge" :class="auditOutcomeClass(row.outcome)" style="font-size:.58rem">
            {{ row.outcome || '\u2014' }}
          </span>
        </template>
        <template #cell-duration_s="{ row }">
          {{ row.duration_s != null ? row.duration_s + 's' : '\u2014' }}
        </template>
        <template #cell-approved_by="{ row }">
          {{ formatApprovedBy(row) }}
        </template>
      </DataTable>
    </div>
  </div>
</template>
