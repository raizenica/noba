<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { useHealingStore } from '../../stores/healing'

const store = useHealingStore()

// ── Formatters ────────────────────────────────────────────────────────────────
function fmtTs(ts) {
  if (!ts) return '\u2013'
  return new Date(ts * 1000).toLocaleString()
}
</script>

<template>
  <div>
    <div class="card">
      <div class="card-header">
        <h3 class="card-title"><i class="fas fa-check-circle mr-6"></i>Pending Approvals</h3>
      </div>
      <div class="card-body" style="padding:0;overflow-x:auto">
        <div v-if="store.loading && store.pendingApprovals.length === 0" style="padding:24px;text-align:center;color:var(--text-muted)">
          <i class="fas fa-spinner fa-spin"></i> Loading...
        </div>
        <p v-else-if="store.pendingApprovals.length === 0" class="empty-msg">No pending approvals. All heal actions are autonomous or completed.</p>
        <table v-else style="width:100%;border-collapse:collapse;font-size:13px">
          <thead>
            <tr style="background:var(--surface2);color:var(--text-muted);font-size:11px;text-transform:uppercase;letter-spacing:.5px">
              <th class="th-left">Timestamp</th>
              <th class="th-left">Rule ID</th>
              <th class="th-left">Target</th>
              <th class="th-left">Action</th>
              <th class="th-center">Step</th>
              <th class="th-left">Trigger</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in store.pendingApprovals"
              :key="row.id"
              class="border-b table-row-hover" style="transition:background .15s"
            >
              <td class="td-body" style="color:var(--text-muted);white-space:nowrap">{{ fmtTs(row.created_at) }}</td>
              <td class="td-body" style="font-family:monospace;font-size:12px">{{ row.automation_id || row.rule_id || '\u2013' }}</td>
              <td class="td-body" style="font-family:monospace;font-size:12px">{{ row.target || '\u2013' }}</td>
              <td class="td-body">
                <span class="badge ba">{{ row.action_type || '\u2013' }}</span>
              </td>
              <td class="td-body-center">{{ row.escalation_step ||0 }}</td>
              <td class="td-body">
                <span class="badge bw">{{ row.trigger || 'manual' }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
