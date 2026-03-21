<script setup>
import { computed } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import { useAuthStore } from '../../stores/auth'
import { useApi } from '../../composables/useApi'
import DashboardCard from './DashboardCard.vue'

const dashboard  = useDashboardStore()
const auth       = useAuthStore()
const { post }   = useApi()

const containers = computed(() => dashboard.live.containers || [])
const isOperator = computed(() => auth.isOperator)

async function containerAction(name, action) {
  try {
    await post('/api/container-control', { name, action })
  } catch { /* silent */ }
}
</script>

<template>
  <DashboardCard title="Containers" icon="fas fa-boxes" card-id="containers">
    <template #header-actions>
      <span
        v-if="containers.length > 0"
        class="card-count"
      >{{ containers.length }} total</span>
    </template>

    <div v-if="containers.length > 0" class="ct-list">
      <div
        v-for="c in containers"
        :key="c.name"
        class="ct-row"
      >
        <div
          class="status-dot"
          :class="c.state === 'running' ? 'dot-up' : 'dot-down'"
          :aria-label="c.state"
        ></div>
        <span class="ct-name">{{ c.name }}</span>
        <span class="ct-img">{{ c.image }}</span>
        <span
          class="badge"
          :class="c.state === 'running' ? 'bs' : c.state === 'exited' ? 'bw' : 'bn'"
        >{{ c.state }}</span>
        <div v-if="isOperator" class="svc-actions">
          <button
            class="svc-btn"
            title="Start"
            :disabled="c.state === 'running'"
            aria-label="Start container"
            @click.stop="containerAction(c.name, 'start')"
          ><i class="fas fa-play" aria-hidden="true"></i></button>
          <button
            class="svc-btn"
            title="Stop"
            :disabled="c.state !== 'running'"
            aria-label="Stop container"
            @click.stop="containerAction(c.name, 'stop')"
          ><i class="fas fa-stop" aria-hidden="true"></i></button>
          <button
            class="svc-btn"
            title="Restart"
            :disabled="c.state !== 'running'"
            aria-label="Restart container"
            @click.stop="containerAction(c.name, 'restart')"
          ><i class="fas fa-sync" aria-hidden="true"></i></button>
        </div>
      </div>
    </div>
    <div v-else class="empty-msg">No containers running.</div>
  </DashboardCard>
</template>
