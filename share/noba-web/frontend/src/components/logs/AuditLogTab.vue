<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, computed } from 'vue'
import { useApi } from '../../composables/useApi'
import { useNotificationsStore } from '../../stores/notifications'

const { get, post } = useApi()
const notif         = useNotificationsStore()

const auditLog       = ref([])
const auditLoading   = ref(false)
const auditPage      = ref(1)
const auditPageSize  = ref(50)
const auditTotal     = ref(0)
const auditSortField = ref('time')
const auditSortDir   = ref('desc')

const auditSorted = computed(() => {
  const log = [...auditLog.value]
  const field = auditSortField.value
  const dir   = auditSortDir.value === 'asc' ? 1 : -1
  return log.sort((a, b) => {
    const va = a[field] ?? ''
    const vb = b[field] ?? ''
    if (typeof va === 'number') return (va - vb) * dir
    return String(va).localeCompare(String(vb)) * dir
  })
})

function toggleAuditSort(field) {
  if (auditSortField.value === field) {
    auditSortDir.value = auditSortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    auditSortField.value = field
    auditSortDir.value   = 'desc'
  }
}

async function fetchAuditLog(page) {
  if (page !== undefined) auditPage.value = page
  auditLoading.value = true
  try {
    const offset = (auditPage.value - 1) * auditPageSize.value
    const data = await get(
      `/api/audit?limit=${auditPageSize.value}&offset=${offset}&sort=${auditSortField.value}&dir=${auditSortDir.value}`
    )
    if (Array.isArray(data)) {
      auditLog.value   = data
      auditTotal.value = data.length < auditPageSize.value
        ? (auditPage.value - 1) * auditPageSize.value + data.length
        : auditTotal.value || data.length
    }
  } catch (e) { notif.addToast('Failed to load audit log: ' + e.message, 'danger') }
  finally { auditLoading.value = false }
}

async function exportAuditCsv() {
  try {
    const res = await post('/api/audit/export', {
      sort: auditSortField.value,
      dir:  auditSortDir.value,
    })
    const blob = new Blob([typeof res === 'string' ? res : JSON.stringify(res)], { type: 'text/csv' })
    const url  = URL.createObjectURL(blob)
    const a    = document.createElement('a')
    a.href = url; a.download = 'noba-audit.csv'; a.click()
    URL.revokeObjectURL(url)
  } catch {
    const header = 'timestamp,username,action,details,ip'
    const lines  = auditLog.value.map(r => {
      const ts      = new Date((r.time || r.timestamp || 0) * 1000).toISOString()
      const details = (r.detail || r.details || '').replace(/"/g, '""')
      return `${ts},"${r.username || r.user || ''}","${r.action || ''}","${details}","${r.ip || ''}"`
    })
    const csv = [header, ...lines].join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url  = URL.createObjectURL(blob)
    const a    = document.createElement('a')
    a.href = url; a.download = 'noba-audit.csv'; a.click()
    URL.revokeObjectURL(url)
  }
}

defineExpose({ fetchAuditLog })
</script>

<template>
  <div>
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.5rem;flex-wrap:wrap;gap:.4rem">
      <span style="font-size:.75rem;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:.08em">
        <i class="fas fa-clipboard-list" style="margin-right:.3rem"></i>Audit Log
      </span>
      <div style="display:flex;gap:.3rem">
        <button class="btn btn-xs" :disabled="auditLoading" @click="fetchAuditLog()">
          <i class="fas" :class="auditLoading ? 'fa-spinner fa-spin' : 'fa-sync-alt'"></i> Refresh
        </button>
        <button class="btn btn-xs" @click="exportAuditCsv">
          <i class="fas fa-download"></i> CSV
        </button>
      </div>
    </div>

    <div style="max-height:55vh;overflow-y:auto">
      <table style="width:100%;font-size:.8rem;border-collapse:collapse">
        <thead>
          <tr style="border-bottom:1px solid var(--border)">
            <th
              style="padding:.4rem;text-align:left;cursor:pointer;user-select:none;white-space:nowrap"
              @click="toggleAuditSort('time')"
            >
              Time
              <i v-if="auditSortField==='time'" class="fas" :class="auditSortDir==='asc'?'fa-sort-up':'fa-sort-down'" style="font-size:.6rem"></i>
            </th>
            <th
              style="padding:.4rem;text-align:left;cursor:pointer;user-select:none"
              @click="toggleAuditSort('action')"
            >
              Action
              <i v-if="auditSortField==='action'" class="fas" :class="auditSortDir==='asc'?'fa-sort-up':'fa-sort-down'" style="font-size:.6rem"></i>
            </th>
            <th
              style="padding:.4rem;text-align:left;cursor:pointer;user-select:none"
              @click="toggleAuditSort('username')"
            >
              User
              <i v-if="auditSortField==='username'" class="fas" :class="auditSortDir==='asc'?'fa-sort-up':'fa-sort-down'" style="font-size:.6rem"></i>
            </th>
            <th style="padding:.4rem;text-align:left">Detail</th>
            <th
              style="padding:.4rem;text-align:left;cursor:pointer;user-select:none"
              @click="toggleAuditSort('ip')"
            >
              IP
              <i v-if="auditSortField==='ip'" class="fas" :class="auditSortDir==='asc'?'fa-sort-up':'fa-sort-down'" style="font-size:.6rem"></i>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="e in auditSorted"
            :key="e.id || e.timestamp || e.time"
            style="border-bottom:1px solid var(--border)"
          >
            <td style="padding:.4rem;white-space:nowrap">
              {{ new Date((e.time || e.timestamp || 0) * 1000).toLocaleString() }}
            </td>
            <td style="padding:.4rem">
              <span class="badge ba" style="font-size:.55rem">{{ e.action }}</span>
            </td>
            <td style="padding:.4rem">{{ e.username || e.user }}</td>
            <td style="padding:.4rem;font-size:.7rem;max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
              {{ e.detail || e.details }}
            </td>
            <td style="padding:.4rem;font-size:.7rem;color:var(--text-muted)">{{ e.ip }}</td>
          </tr>
          <tr v-if="auditSorted.length === 0 && !auditLoading">
            <td colspan="5" style="text-align:center;padding:2rem;color:var(--text-muted)">No audit log entries.</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Pagination -->
    <div style="display:flex;gap:.3rem;align-items:center;margin-top:.5rem;font-size:.75rem">
      <button
        class="btn btn-xs"
        :disabled="auditPage <= 1"
        @click="fetchAuditLog(auditPage - 1)"
        aria-label="Previous page"
      >
        <i class="fas fa-chevron-left"></i>
      </button>
      <span>Page {{ auditPage }}</span>
      <button
        class="btn btn-xs"
        :disabled="auditLog.length < auditPageSize"
        @click="fetchAuditLog(auditPage + 1)"
        aria-label="Next page"
      >
        <i class="fas fa-chevron-right"></i>
      </button>
    </div>
  </div>
</template>
