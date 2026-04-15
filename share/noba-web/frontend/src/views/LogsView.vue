<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, computed } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useDashboardStore } from '../stores/dashboard'
import AppTabBar from '../components/ui/AppTabBar.vue'

import SystemLogTab      from '../components/logs/SystemLogTab.vue'
import CommandHistoryTab from '../components/logs/CommandHistoryTab.vue'
import AuditLogTab       from '../components/logs/AuditLogTab.vue'
import JournalTab        from '../components/logs/JournalTab.vue'
import LiveStreamTab     from '../components/logs/LiveStreamTab.vue'

const authStore = useAuthStore()
const dashStore = useDashboardStore()

const agents = computed(() => dashStore.live.agents || [])

const activeTab = ref('syslog')

const tabs = computed(() => {
  const t = [
    { key: 'syslog',  label: 'System Log',     icon: 'fa-scroll' },
    { key: 'history', label: 'Command History', icon: 'fa-history' },
    { key: 'audit',   label: 'Audit Log',       icon: 'fa-user-shield' },
    { key: 'journal', label: 'Journal',         icon: 'fa-book' },
  ]
  if (agents.value.length > 0 && authStore.isAdmin) {
    t.push({ key: 'stream', label: 'Live Stream', icon: 'fa-satellite-dish' })
  }
  return t
})

const syslogRef  = ref(null)
const historyRef = ref(null)
const auditRef   = ref(null)
const journalRef = ref(null)

function setTab(tab) {
  activeTab.value = tab
  if (tab === 'syslog')   syslogRef.value?.fetchLog()
  if (tab === 'history')  historyRef.value?.fetchCommandHistory()
  if (tab === 'audit')    auditRef.value?.fetchAuditLog()
  if (tab === 'journal')  { journalRef.value?.fetchJournalUnits(); journalRef.value?.fetchJournal() }
}
</script>

<template>
  <div>
    <!-- Page header -->
    <h2 style="margin-bottom:1rem">
      <i class="fas fa-scroll" style="margin-right:.5rem;color:var(--accent)"></i>
      Logs
    </h2>

    <!-- Tab bar -->
    <AppTabBar :tabs="tabs" :active="activeTab" @change="setTab" />

    <!-- Tab contents -->
    <div v-show="activeTab === 'syslog'">
      <SystemLogTab ref="syslogRef" />
    </div>

    <div v-show="activeTab === 'history'">
      <CommandHistoryTab ref="historyRef" />
    </div>

    <div v-show="activeTab === 'audit'">
      <AuditLogTab ref="auditRef" />
    </div>

    <div v-show="activeTab === 'journal'">
      <JournalTab ref="journalRef" />
    </div>

    <div v-show="activeTab === 'stream'">
      <LiveStreamTab />
    </div>
  </div>
</template>
