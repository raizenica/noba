<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { onMounted } from 'vue'
import { useApprovalsStore } from '../../stores/approvals'
import { useNotificationsStore } from '../../stores/notifications'
import { useAuthStore } from '../../stores/auth'

const approvalsStore = useApprovalsStore()
const notify = useNotificationsStore()
const authStore = useAuthStore()

function relativeTime(ts) {
  if (!ts) return '—'
  const diffSec = Math.floor(Date.now() / 1000 - ts)
  if (diffSec < 60) return `${diffSec}s ago`
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`
  return `${Math.floor(diffSec / 86400)}d ago`
}

function formatParams(params) {
  if (!params || typeof params !== 'object') return ''
  return Object.entries(params)
    .map(([k, v]) => `${k}: ${v}`)
    .join(', ')
}

async function approve(approval) {
  try {
    await approvalsStore.decide(approval.id, 'approve')
    notify.addToast('Approval granted', 'success')
  } catch (e) {
    notify.addToast('Failed to approve: ' + e.message, 'error')
  }
}

async function deny(approval) {
  try {
    await approvalsStore.decide(approval.id, 'deny')
    notify.addToast('Approval denied', 'success')
  } catch (e) {
    notify.addToast('Failed to deny: ' + e.message, 'error')
  }
}

onMounted(() => {
  approvalsStore.fetchPending()
})
</script>

<template>
  <div>
    <!-- Header row -->
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:.8rem">
      <span style="font-size:.75rem;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:var(--text-muted)">
        <i class="fas fa-check-circle" style="margin-right:.3rem"></i>
        Pending Approvals
        <span
          v-if="approvalsStore.count > 0"
          class="badge ba"
          style="font-size:.6rem;margin-left:.4rem"
        >{{ approvalsStore.count }}</span>
      </span>
      <button class="btn btn-xs" @click="approvalsStore.fetchPending()">
        <i class="fas fa-sync-alt"></i>
      </button>
    </div>

    <!-- Empty state -->
    <div v-if="approvalsStore.pending.length === 0" class="empty-msg">
      No pending approvals.
    </div>

    <!-- Approval cards -->
    <div
      v-else
      style="display:flex;flex-direction:column;gap:.75rem"
    >
      <div
        v-for="item in approvalsStore.pending"
        :key="item.id"
        style="
          padding:.8rem;
          border:1px solid var(--border);
          border-left:3px solid var(--warning, #f0a500);
          border-radius:6px;
          background:var(--surface-2);
        "
      >
        <!-- Trigger source -->
        <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:.4rem">
          <div style="font-weight:600;font-size:.85rem">
            <i class="fas fa-bell" style="margin-right:.3rem;color:var(--warning, #f0a500)"></i>
            {{ item.trigger_source || item.rule_name || 'Unknown trigger' }}
          </div>
          <span style="font-size:.7rem;color:var(--text-muted)">{{ relativeTime(item.requested_at) }}</span>
        </div>

        <!-- Action type + parameters -->
        <div style="font-size:.8rem;margin-bottom:.25rem">
          <span style="color:var(--text-muted)">Action:</span>
          <span style="margin-left:.3rem;font-weight:500">{{ item.action_type || '—' }}</span>
          <span
            v-if="item.action_params && Object.keys(item.action_params).length"
            style="margin-left:.4rem;color:var(--text-muted);font-size:.75rem"
          >({{ formatParams(item.action_params) }})</span>
        </div>

        <!-- Target host / service -->
        <div v-if="item.target_host || item.target_service" style="font-size:.78rem;color:var(--text-muted);margin-bottom:.25rem">
          <i class="fas fa-server" style="margin-right:.3rem"></i>
          {{ item.target_host || item.target_service }}
        </div>

        <!-- Auto-approve countdown -->
        <div
          v-if="item.auto_approve_after"
          style="font-size:.72rem;color:var(--text-muted);margin-bottom:.35rem"
        >
          <i class="fas fa-clock" style="margin-right:.3rem"></i>
          Auto-approves in {{ item.auto_approve_after }}s
        </div>

        <!-- Approve / Deny buttons (operator+) -->
        <div
          v-if="authStore.isOperator"
          style="display:flex;gap:.4rem;margin-top:.5rem"
        >
          <button
            class="btn btn-xs"
            style="background:var(--success);border-color:var(--success);color:#fff"
            @click="approve(item)"
          >
            <i class="fas fa-check" style="margin-right:.25rem"></i>Approve
          </button>
          <button
            class="btn btn-xs btn-danger"
            @click="deny(item)"
          >
            <i class="fas fa-times" style="margin-right:.25rem"></i>Deny
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
