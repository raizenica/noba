<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { computed } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import DashboardCard from './DashboardCard.vue'

const dashboard = useDashboardStore()

const topCpu = computed(() => dashboard.live.topCpu || [])
const topMem = computed(() => dashboard.live.topMem || [])
const topIo  = computed(() => dashboard.live.topIo  || [])
</script>

<template>
  <DashboardCard title="Resource Hogs" icon="fas fa-chart-bar" card-id="procs">
    <div class="proc-grid">
      <div>
        <div class="proc-hdr">Top CPU</div>
        <div
          v-for="(p, i) in topCpu"
          :key="'cpu-' + i"
          class="proc-row"
        >
          <span class="proc-n">{{ p.name }}</span>
          <span class="cpu-col">{{ p.val }}</span>
        </div>
      </div>
      <div>
        <div class="proc-hdr">Top Memory</div>
        <div
          v-for="(p, i) in topMem"
          :key="'mem-' + i"
          class="proc-row"
        >
          <span class="proc-n">{{ p.name }}</span>
          <span class="mem-col">{{ p.val }}</span>
        </div>
      </div>
      <div>
        <div class="proc-hdr">Top I/O</div>
        <div
          v-for="(p, i) in topIo"
          :key="'io-' + i"
          class="proc-row"
        >
          <span class="proc-n">{{ p.name }}</span>
          <span class="cpu-col">{{ p.val }}</span>
        </div>
      </div>
    </div>
  </DashboardCard>
</template>
