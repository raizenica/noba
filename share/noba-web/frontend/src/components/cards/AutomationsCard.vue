<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useApi } from '../../composables/useApi'
import { useAuthStore } from '../../stores/auth'
import DashboardCard from './DashboardCard.vue'

const { get, post } = useApi()
const auth = useAuthStore()

const autoList        = ref([])
const autoListLoading = ref(false)
const autoFilter      = ref('all')
const autoSearch      = ref('')
const runningAuto     = ref(false)
const autoStats       = ref({})

const isViewer   = computed(() => auth.userRole === 'viewer')
const isAdmin    = computed(() => auth.userRole === 'admin')
const isOperator = computed(() => auth.isOperator)

const filteredAutoList = computed(() => {
  let list = autoList.value
  if (autoFilter.value !== 'all') {
    list = list.filter(a => a.type === autoFilter.value)
  }
  if (autoSearch.value.trim()) {
    const q = autoSearch.value.toLowerCase()
    list = list.filter(a => a.name.toLowerCase().includes(q))
  }
  return list
})

async function fetchAutomations() {
  autoListLoading.value = true
  try {
    const data = await get('/api/automations')
    autoList.value = data.automations || data || []
    // build stats map
    const stats = {}
    for (const a of autoList.value) {
      if (a.stats) stats[a.id] = a.stats
    }
    autoStats.value = stats
  } catch { /* silent */ }
  finally { autoListLoading.value = false }
}

function getAutoStat(id) {
  return autoStats.value[id] || null
}

function fmtDuration(secs) {
  if (secs == null) return ''
  if (secs >= 60) return Math.floor(secs / 60) + 'm ' + (secs % 60) + 's'
  return secs + 's'
}

function fmtRunTime(ts) {
  if (!ts) return ''
  try { return new Date(ts * 1000).toLocaleTimeString() } catch { return '' }
}

async function runAutomation(auto) {
  if (runningAuto.value || !auto.enabled) return
  runningAuto.value = true
  try {
    await post(`/api/automations/${auto.id}/run`, {})
  } catch { /* silent */ }
  finally { runningAuto.value = false }
}

function autoTypeIcon(type) {
  if (type === 'webhook')  return 'fa-globe'
  if (type === 'service')  return 'fa-cog'
  if (type === 'workflow') return 'fa-project-diagram'
  return 'fa-terminal'
}

onMounted(() => fetchAutomations())
</script>

<template>
  <DashboardCard title="Automation Deck" icon="fas fa-robot" card-id="automations">
    <!-- Stats summary -->
    <div
      v-if="!autoListLoading && autoList.length > 0"
      style="margin-bottom:.5rem"
    >
      <div style="display:flex;gap:.5rem;margin-bottom:.5rem;font-size:.7rem;opacity:.7">
        <span>{{ autoList.length }} total</span>
        <span>{{ autoList.filter(a => a.enabled).length }} enabled</span>
        <span>{{ autoList.filter(a => a.schedule).length }} scheduled</span>
      </div>

      <!-- Type filter buttons -->
      <div style="display:flex;gap:.25rem;margin-bottom:.4rem;flex-wrap:wrap">
        <button
          v-for="f in ['all','script','webhook','service','workflow']"
          :key="f"
          class="btn btn-sm"
          style="font-size:.6rem;padding:.15rem .4rem;width:auto"
          :class="autoFilter === f ? 'btn-primary' : ''"
          @click="autoFilter = f"
        >{{ f === 'all' ? 'All' : f.charAt(0).toUpperCase() + f.slice(1) }}</button>
      </div>

      <input
        v-model="autoSearch"
        class="field-input"
        type="text"
        placeholder="Search automations..."
        style="font-size:.75rem;padding:.3rem .5rem;margin-bottom:.4rem"
      >
    </div>

    <div v-if="autoListLoading" style="text-align:center;padding:.5rem;opacity:.6">Loading...</div>
    <div v-else-if="autoList.length === 0" class="empty-msg">No automations defined.</div>
    <div v-else-if="filteredAutoList.length === 0" class="empty-msg">No matching automations.</div>

    <div
      v-for="auto in filteredAutoList"
      :key="auto.id"
      style="margin-bottom:.5rem"
    >
      <div style="display:flex;align-items:center;gap:.4rem">
        <!-- Run button (non-viewer) -->
        <button
          v-if="!isViewer"
          class="btn btn-primary"
          style="flex:1;text-align:left"
          :disabled="runningAuto || !auto.enabled"
          :style="!auto.enabled ? 'opacity:.5' : ''"
          @click="runAutomation(auto)"
        >
          <i class="fas" :class="autoTypeIcon(auto.type)" aria-hidden="true"></i>
          {{ auto.name }}
          <span
            v-if="auto.schedule"
            class="badge bi"
            style="font-size:.55rem;margin-left:.3rem"
            :title="'Schedule: ' + auto.schedule"
          ><i class="fas fa-clock" aria-hidden="true"></i></span>
          <span
            class="badge"
            :class="auto.enabled ? 'bs' : 'bw'"
            style="margin-left:auto;font-size:.6rem"
          >{{ auto.type }}</span>
        </button>
        <!-- Viewer: just show name -->
        <span v-else style="flex:1">{{ auto.name }}</span>
      </div>

      <!-- Run stats -->
      <div
        v-if="getAutoStat(auto.id)"
        style="display:flex;gap:.6rem;font-size:.6rem;opacity:.6;padding-left:.3rem;margin-top:.15rem"
      >
        <span v-if="getAutoStat(auto.id)?.total">
          {{ (getAutoStat(auto.id)?.ok || 0) }}/{{ (getAutoStat(auto.id)?.total || 0) }} ok
        </span>
        <span v-if="getAutoStat(auto.id)?.avg_duration">
          avg {{ fmtDuration(getAutoStat(auto.id)?.avg_duration || 0) }}
        </span>
        <span v-if="getAutoStat(auto.id)?.last_run">
          last {{ fmtRunTime(getAutoStat(auto.id)?.last_run) }}
        </span>
      </div>
    </div>
  </DashboardCard>
</template>
