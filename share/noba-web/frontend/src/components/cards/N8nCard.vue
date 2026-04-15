<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { computed } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import DashboardCard from './DashboardCard.vue'

const dashboard = useDashboardStore()
const n8n = computed(() => dashboard.live.n8n)

const health = computed(() => {
  if (!n8n.value) return ''
  if (n8n.value.status === 'error') return 'fail'
  if (n8n.value.failure_rate > 10) return 'warn'
  return 'ok'
})
</script>

<template>
  <DashboardCard title="n8n Automation" icon="fas fa-robot" card-id="n8n" :health="health">
    <template v-if="n8n && n8n.status === 'online'">
      <div class="row">
        <span class="row-label">Workflows</span>
        <span class="row-val" style="color:var(--success)">{{ n8n.active_workflows }}/{{ n8n.workflows }} active</span>
      </div>
      <div class="row">
        <span class="row-label">Executions</span>
        <span class="row-val">{{ n8n.recent_executions }} recent</span>
      </div>
      <div v-if="n8n.failed_executions > 0" class="row">
        <span class="row-label">Failed</span>
        <span class="row-val" style="color:var(--danger)">{{ n8n.failed_executions }} ({{ n8n.failure_rate }}%)</span>
      </div>
      <div v-if="n8n.last_execution" class="row">
        <span class="row-label">Last Run</span>
        <span class="row-val" style="font-size:.7rem;color:var(--text-muted)">{{ new Date(n8n.last_execution).toLocaleString() }}</span>
      </div>
      <div v-if="n8n.workflow_names && n8n.workflow_names.length" style="margin-top:.5rem;font-size:.7rem;color:var(--text-muted)">
        <div v-for="name in n8n.workflow_names.slice(0, 5)" :key="name" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">
          <i class="fas fa-play" style="font-size:.4rem;margin-right:4px;color:var(--success)"></i>{{ name }}
        </div>
      </div>
    </template>
    <template v-else-if="n8n && n8n.status === 'error'">
      <div style="text-align:center;padding:.5rem 0">
        <span class="badge bd" style="font-size:.7rem">Connection Error</span>
        <p style="font-size:.72rem;color:var(--text-muted);margin:.6rem 0 0">
          <router-link to="/settings/integrations" class="empty-link">Check Settings → Integrations</router-link>
        </p>
      </div>
    </template>
    <div v-else class="empty-msg">n8n not configured — <router-link to="/settings/general" class="empty-link">add URL in Settings</router-link>.</div>
  </DashboardCard>
</template>
