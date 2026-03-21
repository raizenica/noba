<script setup>
import { ref, onMounted } from 'vue'
import { useApi } from '../../composables/useApi'

const { get } = useApi()

const slaData    = ref(null)
const slaLoading = ref(false)
const slaPeriod  = ref(720)

async function fetchSla(hours) {
  const h = hours || slaPeriod.value
  slaPeriod.value = h
  slaLoading.value = true
  try {
    slaData.value = await get(`/api/sla/summary?hours=${h}`)
  } catch { /* silent */ }
  finally { slaLoading.value = false }
}

function uptimeColor(pct) {
  if (pct >= 99.9) return 'var(--success)'
  if (pct >= 99)   return 'var(--warning)'
  return 'var(--danger)'
}

onMounted(() => fetchSla())
</script>

<template>
  <div>
    <!-- Period selector -->
    <div style="display:flex;gap:.4rem;margin-bottom:1rem">
      <button
        class="btn btn-xs"
        :class="slaPeriod === 168 ? 'btn-primary' : ''"
        @click="fetchSla(168)"
      >7d</button>
      <button
        class="btn btn-xs"
        :class="slaPeriod === 720 ? 'btn-primary' : ''"
        @click="fetchSla(720)"
      >30d</button>
      <button
        class="btn btn-xs"
        :class="slaPeriod === 2160 ? 'btn-primary' : ''"
        @click="fetchSla(2160)"
      >90d</button>
      <button
        class="btn btn-xs"
        style="margin-left:auto"
        :disabled="slaLoading"
        @click="fetchSla()"
      >
        <i class="fas" :class="slaLoading ? 'fa-spinner fa-spin' : 'fa-sync-alt'"></i>
      </button>
    </div>

    <div v-if="slaLoading" class="empty-msg">Calculating...</div>

    <template v-else-if="slaData">
      <div v-if="(slaData.sla || []).length === 0" class="empty-msg">
        No SLA data yet. Incidents will populate this over time.
      </div>
      <div v-for="s in (slaData.sla || [])" :key="s.name">
        <div style="display:flex;align-items:center;gap:.6rem;padding:.5rem 0;border-bottom:1px solid var(--border)">
          <div style="flex:1">
            <div style="font-weight:600;font-size:.85rem">{{ s.name }}</div>
            <div style="font-size:.65rem;color:var(--text-muted)">
              {{ s.type }} &middot; {{ s.incidents }} incident(s)
              <span v-if="s.downtime_m > 0"> &middot; {{ s.downtime_m }}m downtime</span>
            </div>
          </div>
          <div style="text-align:right">
            <div
              style="font-size:1.1rem;font-weight:700;font-family:var(--font-data)"
              :style="`color:${uptimeColor(s.uptime_pct)}`"
            >{{ s.uptime_pct }}%</div>
            <div style="width:120px;height:4px;background:var(--surface-2);border-radius:2px;margin-top:3px">
              <div
                style="height:100%;border-radius:2px;transition:width .3s"
                :style="`width:${Math.min(s.uptime_pct, 100)}%;background:${uptimeColor(s.uptime_pct)}`"
              ></div>
            </div>
          </div>
        </div>
      </div>
    </template>

    <div v-else class="empty-msg">No SLA data available.</div>
  </div>
</template>
