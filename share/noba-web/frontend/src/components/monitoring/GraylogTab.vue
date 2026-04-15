<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref } from 'vue'
import { useApi } from '../../composables/useApi'
import { useSettingsStore } from '../../stores/settings'
import { useNotificationsStore } from '../../stores/notifications'

const { get } = useApi()
const settingsStore = useSettingsStore()
const notify = useNotificationsStore()

const graylogQuery   = ref('')
const graylogLoading = ref(false)
const graylogResults = ref(null)

async function searchGraylog() {
  graylogLoading.value = true
  try {
    const data = await get(
      `/api/graylog/search?q=${encodeURIComponent(graylogQuery.value)}&hours=1`
    )
    graylogResults.value = data
  } catch (e) {
    notify.addToast(e.message || 'Graylog search failed', 'error')
  } finally { graylogLoading.value = false }
}
</script>

<template>
  <div>
    <!-- If graylogUrl is configured, show link -->
    <div v-if="settingsStore.data.graylogUrl" style="margin-bottom:1rem;display:flex;align-items:center;gap:.5rem">
      <i class="fas fa-external-link-alt" style="color:var(--accent)"></i>
      <a
        :href="settingsStore.data.graylogUrl"
        target="_blank"
        rel="noopener"
        style="color:var(--accent);font-size:.85rem"
      >Open Graylog</a>
    </div>

    <!-- Search panel -->
    <div style="display:flex;gap:.5rem;margin-bottom:.5rem;flex-wrap:wrap">
      <span style="font-size:.7rem;color:var(--text-muted);align-self:center">Quick Queries:</span>
      <button class="btn btn-xs btn-secondary" @click="graylogQuery = 'level:3 OR level:4'">Errors & Warnings</button>
      <button class="btn btn-xs btn-secondary" @click="graylogQuery = 'message:&quot;Accepted publickey&quot; OR message:&quot;Failed password&quot;'">SSH Auth</button>
      <button class="btn btn-xs btn-secondary" @click="graylogQuery = 'message:&quot;Out of memory&quot; OR message:&quot;OOM&quot;'">OOM Kills</button>
    </div>
    <div style="display:flex;gap:.5rem;margin-bottom:1rem">
      <input
        v-model="graylogQuery"
        class="field-input"
        placeholder="Search query..."
        style="flex:1;font-size:.8rem"
        @keyup.enter="searchGraylog"
      >
      <button
        class="btn btn-primary btn-sm"
        :disabled="graylogLoading"
        @click="searchGraylog"
      >
        <i class="fas" :class="graylogLoading ? 'fa-spinner fa-spin' : 'fa-search'"></i>
      </button>
    </div>

    <div v-if="graylogLoading" class="empty-msg">Searching...</div>

    <template v-else-if="graylogResults">
      <div style="font-size:.7rem;color:var(--text-muted);margin-bottom:.5rem">
        {{ graylogResults.total || 0 }} results
      </div>
      <div style="max-height:400px;overflow-y:auto">
        <div
          v-for="(msg, i) in (graylogResults.messages || [])"
          :key="i"
          style="padding:.4rem;border-bottom:1px solid var(--border);font-size:.75rem"
        >
          <div style="display:flex;justify-content:space-between">
            <span style="color:var(--accent)">{{ msg.source }}</span>
            <span style="color:var(--text-muted);font-size:.65rem">{{ msg.timestamp }}</span>
          </div>
          <div style="margin-top:.2rem;word-break:break-word">{{ msg.message }}</div>
        </div>
        <div
          v-if="!(graylogResults.messages || []).length"
          class="empty-msg"
        >No results found.</div>
      </div>
    </template>

    <div v-else-if="!settingsStore.data.graylogUrl" class="empty-msg">
      Configure Graylog URL in Settings to enable integration, or use the search above.
    </div>
  </div>
</template>
