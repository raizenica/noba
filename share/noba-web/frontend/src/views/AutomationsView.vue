<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref } from 'vue'
import { useApprovalsStore } from '../stores/approvals'

import AutomationListTab from '../components/automations/AutomationListTab.vue'
import ApprovalQueue     from '../components/automations/ApprovalQueue.vue'
import MaintenanceWindows from '../components/automations/MaintenanceWindows.vue'
import AuditTrailTab     from '../components/automations/AuditTrailTab.vue'
import PlaybookLibrary   from '../components/automations/PlaybookLibrary.vue'

const approvalsStore = useApprovalsStore()

const activeTab = ref('automations')

const auditRef = ref(null)
</script>

<template>
  <div>
    <!-- Page header -->
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:1rem">
      <h2 style="margin:0">
        <i class="fas fa-bolt" style="margin-right:.5rem;color:var(--accent)"></i>
        Automations
      </h2>
    </div>

    <!-- Tab bar -->
    <div style="display:flex;gap:.25rem;border-bottom:1px solid var(--border);margin-bottom:1rem">
      <button
        class="btn btn-xs"
        :class="activeTab === 'automations' ? 'btn-primary' : ''"
        style="border-radius:4px 4px 0 0;border-bottom:none"
        @click="activeTab = 'automations'"
      >
        <i class="fas fa-bolt" style="margin-right:.25rem"></i>Automations
      </button>
      <button
        class="btn btn-xs"
        :class="activeTab === 'approvals' ? 'btn-primary' : ''"
        style="border-radius:4px 4px 0 0;border-bottom:none;position:relative"
        @click="activeTab = 'approvals'; approvalsStore.fetchPending()"
      >
        <i class="fas fa-check-circle" style="margin-right:.25rem"></i>Approvals
        <span
          v-if="(approvalsStore.count || 0) > 0"
          style="
            position:absolute;top:-4px;right:-4px;
            background:var(--warning, #f0a500);
            color:#000;
            border-radius:50%;
            font-size:.55rem;
            min-width:14px;
            height:14px;
            display:flex;
            align-items:center;
            justify-content:center;
            padding:0 2px;
            font-weight:700;
          "
        >{{ approvalsStore.count }}</span>
      </button>
      <button
        class="btn btn-xs"
        :class="activeTab === 'maintenance' ? 'btn-primary' : ''"
        style="border-radius:4px 4px 0 0;border-bottom:none"
        @click="activeTab = 'maintenance'"
      >
        <i class="fas fa-wrench" style="margin-right:.25rem"></i>Maintenance
      </button>
      <button
        class="btn btn-xs"
        :class="activeTab === 'audit' ? 'btn-primary' : ''"
        style="border-radius:4px 4px 0 0;border-bottom:none"
        @click="activeTab = 'audit'; auditRef?.fetchAudit()"
      >
        <i class="fas fa-clipboard-list" style="margin-right:.25rem"></i>Audit Trail
      </button>
      <button
        class="btn btn-xs"
        :class="activeTab === 'playbooks' ? 'btn-primary' : ''"
        style="border-radius:4px 4px 0 0;border-bottom:none"
        @click="activeTab = 'playbooks'"
      >
        <i class="fas fa-book" style="margin-right:.25rem"></i>Playbooks
      </button>
    </div>

    <!-- Tab contents -->
    <div v-if="activeTab === 'automations'">
      <AutomationListTab />
    </div>

    <div v-if="activeTab === 'approvals'">
      <ApprovalQueue />
    </div>

    <div v-if="activeTab === 'maintenance'">
      <MaintenanceWindows />
    </div>

    <div v-if="activeTab === 'audit'">
      <AuditTrailTab ref="auditRef" />
    </div>

    <div v-if="activeTab === 'playbooks'">
      <PlaybookLibrary />
    </div>
  </div>
</template>
