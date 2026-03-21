<script setup>
import { computed } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import DashboardCard from './DashboardCard.vue'

const dashboard = useDashboardStore()

const disks    = computed(() => dashboard.live.disks || [])
const zfs      = computed(() => dashboard.live.zfs || {})
const zfsPools = computed(() => (zfs.value && zfs.value.pools) ? zfs.value.pools : [])
</script>

<template>
  <DashboardCard title="Storage" icon="fas fa-hdd" card-id="storage">
    <!-- ZFS pools -->
    <div
      v-for="pool in zfsPools"
      :key="pool.name"
      class="row"
    >
      <span class="row-label">ZFS: {{ pool.name }}</span>
      <span
        class="badge"
        :class="pool.health === 'ONLINE' ? 'bs' : pool.health === 'DEGRADED' ? 'bw' : 'bd'"
      >{{ pool.health }}</span>
    </div>

    <!-- Disk mounts -->
    <div :style="zfsPools.length ? 'margin-top:.6rem' : ''">
      <div
        v-for="d in disks"
        :key="d.mount"
        class="prog"
      >
        <div class="prog-meta">
          <span>{{ d.mount }}</span>
          <span>{{ d.used }} / {{ d.size }}</span>
        </div>
        <div
          class="prog-track"
          role="progressbar"
          :aria-valuenow="d.percent"
          aria-valuemin="0"
          aria-valuemax="100"
          :aria-label="d.mount + ' ' + d.percent + '% full'"
        >
          <div
            class="prog-fill"
            :class="'f-' + (d.barClass || 'accent')"
            :style="'width:' + d.percent + '%'"
          ></div>
        </div>
      </div>
    </div>

    <div v-if="disks.length === 0 && zfsPools.length === 0" class="empty-msg">
      No storage data available.
    </div>
  </DashboardCard>
</template>
