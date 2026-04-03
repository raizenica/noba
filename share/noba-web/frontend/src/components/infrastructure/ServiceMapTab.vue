<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, onMounted } from 'vue'
import { useApi } from '../../composables/useApi'

const { get } = useApi()

const serviceMap        = ref(null)
const serviceMapLoading = ref(false)

async function fetchServiceMap() {
  serviceMapLoading.value = true
  try {
    const data = await get('/api/services/map')
    serviceMap.value = data
  } catch { serviceMap.value = null }
  finally { serviceMapLoading.value = false }
}

function nodeStatusClass(status) {
  if (status === 'online' || status === 'active') return 'bs'
  if (status === 'configured') return 'bn'
  if (status === 'inactive')   return 'bw'
  return 'bd'
}

onMounted(() => fetchServiceMap())

defineExpose({ fetchServiceMap })
</script>

<template>
  <div>
    <div v-if="serviceMapLoading" class="empty-msg">Loading service map...</div>
    <template v-else-if="serviceMap && serviceMap.nodes && serviceMap.nodes.length">
      <div style="display:flex;flex-wrap:wrap;gap:12px;justify-content:center">
        <div
          v-for="node in serviceMap.nodes"
          :key="node.id"
          style="background:var(--surface-2);border:1px solid var(--border);border-radius:8px;padding:10px 16px;text-align:center;min-width:120px"
          :style="node.id === 'noba' ? 'border-color:var(--accent);box-shadow:0 0 12px var(--accent-dim)' : ''"
        >
          <div style="font-weight:600;font-size:.85rem">{{ node.label || node.id }}</div>
          <span
            class="badge"
            :class="nodeStatusClass(node.status)"
            style="font-size:.6rem;margin-top:4px"
          >{{ node.status }}</span>
          <div v-if="node.cpu != null || node.mem != null" style="font-size:.6rem;color:var(--text-muted);margin-top:4px;display:flex;gap:6px;justify-content:center">
            <span v-if="node.cpu != null">CPU {{ node.cpu }}%</span>
            <span v-if="node.mem != null">RAM {{ node.mem }}%</span>
          </div>
          <div v-if="node.uptime" style="font-size:.55rem;color:var(--text-dim);margin-top:2px">up {{ node.uptime }}</div>
          <div v-else style="font-size:.6rem;color:var(--text-dim);margin-top:2px">{{ node.type }}</div>
        </div>
      </div>
    </template>
    <div v-else class="empty-msg">No service map data. Configure integrations to populate.</div>
  </div>
</template>
