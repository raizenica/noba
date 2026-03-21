<script setup>
import { computed } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import DashboardCard from './DashboardCard.vue'

const dashboard = useDashboardStore()

const agents = computed(() => dashboard.live.agents || [])
const onlineCount = computed(() => agents.value.filter(a => a.online).length)
</script>

<template>
  <DashboardCard title="Remote Agents" icon="fas fa-satellite" card-id="agents">
    <div v-if="agents.length > 0">
      <div style="font-size:.75rem;color:var(--text-muted);margin-bottom:.4rem">
        {{ onlineCount }}/{{ agents.length }} online
      </div>
      <div
        v-for="a in agents"
        :key="a.hostname"
        class="row"
        style="font-size:.75rem"
      >
        <span class="row-label">
          <i
            class="fas fa-circle"
            :class="a.online ? 'dot-up' : 'dot-down'"
            style="font-size:.35rem;margin-right:4px"
          ></i>
          {{ a.hostname }}
        </span>
        <span class="row-val">
          CPU {{ a.cpu_percent || 0 }}% &middot; RAM {{ a.mem_percent || 0 }}%
        </span>
      </div>
    </div>
    <div v-else class="empty-msg">No agents reporting.</div>
  </DashboardCard>
</template>
