<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, computed } from 'vue'
import { useDashboardStore } from '../stores/dashboard'

const dashboardStore = useDashboardStore()

const agents = computed(() => dashboardStore.live.agents || [])

// ── Tab persistence ───────────────────────────────────────────────────────────
const LS_KEY = 'noba_remote_tabs'

function loadTabs() {
  try {
    const raw = localStorage.getItem(LS_KEY)
    if (raw) return JSON.parse(raw)
  } catch {}
  return []
}

function saveTabs() {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(tabs.value))
  } catch {}
}

// tabs: [{ id, name, hosts: [hostname, ...] }]
// "All" is synthetic (id='__all__'), never stored
const tabs = ref(loadTabs())
const activeTabId = ref('__all__')

// Persisted sort order for the "All" tab
const allOrder = ref((() => {
  try { return JSON.parse(localStorage.getItem('noba_remote_allorder') || '[]') } catch { return [] }
})())
function saveAllOrder() {
  try { localStorage.setItem('noba_remote_allorder', JSON.stringify(allOrder.value)) } catch {}
}

// ── Tab operations ────────────────────────────────────────────────────────────
const editingTabId = ref(null)
const editingName = ref('')

function addTab() {
  const id = Date.now().toString(36)
  tabs.value.push({ id, name: 'New group', hosts: [] })
  saveTabs()
  activeTabId.value = id
  startRename(id, 'New group')
}

function deleteTab(id) {
  const idx = tabs.value.findIndex(t => t.id === id)
  if (idx === -1) return
  tabs.value.splice(idx, 1)
  saveTabs()
  if (activeTabId.value === id) activeTabId.value = '__all__'
}

function startRename(id, name) {
  editingTabId.value = id
  editingName.value = name
  // focus handled via nextTick in template
}

function commitRename(id) {
  const tab = tabs.value.find(t => t.id === id)
  if (tab && editingName.value.trim()) {
    tab.name = editingName.value.trim()
    saveTabs()
  }
  editingTabId.value = null
}

// ── Host list for active tab ──────────────────────────────────────────────────
const allTab = computed(() => ({ id: '__all__', name: 'All', hosts: allOrder.value }))

const activeTab = computed(() => {
  if (activeTabId.value === '__all__') return allTab.value
  return tabs.value.find(t => t.id === activeTabId.value) || allTab.value
})

const visibleAgents = computed(() => {
  const order = activeTab.value.hosts
  const map = Object.fromEntries(agents.value.map(a => [a.hostname, a]))
  if (activeTabId.value === '__all__') {
    // All tab: show all agents; respect custom sort order if stored
    return order.map(h => map[h]).filter(Boolean)
      .concat(agents.value.filter(a => !order.includes(a.hostname)))
  }
  // Custom tab: only assigned hosts in stored order, skip missing agents
  return order.map(h => map[h]).filter(Boolean)
})

// ── Host assignment to active tab ─────────────────────────────────────────────
function isInActiveTab(hostname) {
  if (activeTabId.value === '__all__') return true
  return activeTab.value.hosts.includes(hostname)
}

function toggleHostInTab(hostname) {
  if (activeTabId.value === '__all__') return
  const tab = tabs.value.find(t => t.id === activeTabId.value)
  if (!tab) return
  const idx = tab.hosts.indexOf(hostname)
  if (idx === -1) {
    tab.hosts.push(hostname)
  } else {
    tab.hosts.splice(idx, 1)
  }
  saveTabs()
}

// ── Drag-to-reorder within tab ────────────────────────────────────────────────
const dragSrc = ref(null)

function onDragStart(hostname) {
  dragSrc.value = hostname
}

function onDragOver(e) {
  e.preventDefault()
}

function onDrop(targetHostname) {
  if (!dragSrc.value || dragSrc.value === targetHostname) return
  let list = activeTabId.value === '__all__'
    ? [...allOrder.value]
    : [...(tabs.value.find(t => t.id === activeTabId.value)?.hosts || [])]
  agents.value.forEach(a => { if (!list.includes(a.hostname)) list.push(a.hostname) })
  const srcIdx = list.indexOf(dragSrc.value)
  const dstIdx = list.indexOf(targetHostname)
  if (srcIdx === -1 || dstIdx === -1) return
  list.splice(srcIdx, 1)
  list.splice(dstIdx, 0, dragSrc.value)
  if (activeTabId.value === '__all__') {
    allOrder.value = list
    saveAllOrder()
  } else {
    const tab = tabs.value.find(t => t.id === activeTabId.value)
    if (tab) { tab.hosts = list; saveTabs() }
  }
  dragSrc.value = null
}

// ── Connect ───────────────────────────────────────────────────────────────────
function connect(hostname) {
  const url = window.location.origin + window.location.pathname + '#/remote/' + encodeURIComponent(hostname)
  window.open(url, `rdp_${hostname}`)
}

function platformIcon(platform) {
  if (!platform) return 'fa-server'
  const p = platform.toLowerCase()
  if (p.includes('win')) return 'fa-windows fab'
  if (p.includes('darwin') || p.includes('mac')) return 'fa-apple fab'
  return 'fa-linux fab'
}
</script>

<template>
  <div class="page-container">
    <div class="page-header">
      <h1 class="page-title"><i class="fas fa-desktop"></i> Remote Desktop</h1>
      <p class="page-subtitle">Connect to an agent's desktop. Drag rows to reorder. Use tabs to group hosts.</p>
    </div>

    <!-- Tab bar -->
    <div class="remote-tabs">
      <button
        class="remote-tab"
        :class="{ active: activeTabId === '__all__' }"
        @click="activeTabId = '__all__'"
      >All</button>

      <template v-for="tab in tabs" :key="tab.id">
        <div class="remote-tab" :class="{ active: activeTabId === tab.id }">
          <template v-if="editingTabId === tab.id">
            <input
              class="remote-tab-input"
              v-model="editingName"
              @keydown.enter="commitRename(tab.id)"
              @keydown.escape="editingTabId = null"
              @blur="commitRename(tab.id)"
              :ref="el => { if (el) el.focus() }"
            />
          </template>
          <template v-else>
            <span @click="activeTabId = tab.id" @dblclick.stop="startRename(tab.id, tab.name)">
              {{ tab.name }}
            </span>
            <button class="remote-tab-del" @click.stop="deleteTab(tab.id)" title="Delete group">×</button>
          </template>
        </div>
      </template>

      <button class="remote-tab remote-tab-add" @click="addTab" title="Add group">+</button>
    </div>

    <div class="card">
      <div class="card-body" style="padding:0">
        <table class="data-table" style="width:100%">
          <thead>
            <tr>
              <th style="width:20px"></th>
              <th style="width:12px"></th>
              <th>Host</th>
              <th>Platform</th>
              <th>IP</th>
              <th>Last seen</th>
              <th style="width:120px"></th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="visibleAgents.length === 0">
              <td colspan="7" style="text-align:center;padding:2rem;color:var(--text-muted)">
                <template v-if="activeTabId === '__all__'">No agents connected</template>
                <template v-else>
                  No hosts in this group —
                  <a href="#" @click.prevent="activeTabId = '__all__'" style="color:var(--accent)">view all</a>
                  and drag hosts here, or click
                  <strong>+ Add</strong> below.
                </template>
              </td>
            </tr>
            <tr
              v-for="a in visibleAgents"
              :key="a.hostname"
              draggable="true"
              @dragstart="onDragStart(a.hostname)"
              @dragover="onDragOver"
              @drop.prevent="onDrop(a.hostname)"
              :class="{ 'dragging': dragSrc === a.hostname }"
              style="cursor:grab"
            >
              <td style="color:var(--text-muted);cursor:grab;padding-left:.75rem">
                <i class="fas fa-grip-vertical" style="font-size:.75rem"></i>
              </td>
              <td>
                <span class="status-dot" :class="a.online ? 'status-dot--online' : 'status-dot--offline'"></span>
              </td>
              <td style="font-weight:500">{{ a.hostname }}</td>
              <td style="color:var(--text-muted)">
                <i :class="['nav-icon', platformIcon(a.platform)]" style="margin-right:.4rem"></i>
                {{ a.platform || '—' }}
              </td>
              <td style="color:var(--text-muted);font-size:.85rem">{{ a.ip || '—' }}</td>
              <td style="color:var(--text-muted);font-size:.8rem">
                {{ a.online ? 'online' : (a.last_seen_s ? `${a.last_seen_s}s ago` : '—') }}
              </td>
              <td style="display:flex;gap:.35rem;align-items:center;justify-content:flex-end;padding-right:.75rem">
                <button
                  v-if="activeTabId !== '__all__'"
                  class="btn btn-xs"
                  style="font-size:.7rem;padding:.2rem .45rem"
                  @click="toggleHostInTab(a.hostname)"
                  title="Remove from this group"
                >−</button>
                <button
                  class="btn btn-sm btn-primary"
                  :disabled="!a.online"
                  @click="connect(a.hostname)"
                >Connect</button>
              </td>
            </tr>

            <!-- Add hosts row for custom tabs -->
            <template v-if="activeTabId !== '__all__'">
              <tr
                v-for="a in agents.filter(a => !isInActiveTab(a.hostname))"
                :key="'add-' + a.hostname"
                style="opacity:.45"
              >
                <td style="padding-left:.75rem"><i class="fas fa-grip-vertical" style="font-size:.75rem;color:var(--text-muted)"></i></td>
                <td>
                  <span class="status-dot" :class="a.online ? 'status-dot--online' : 'status-dot--offline'"></span>
                </td>
                <td style="font-weight:500">{{ a.hostname }}</td>
                <td style="color:var(--text-muted)">
                  <i :class="['nav-icon', platformIcon(a.platform)]" style="margin-right:.4rem"></i>
                  {{ a.platform || '—' }}
                </td>
                <td style="color:var(--text-muted);font-size:.85rem">{{ a.ip || '—' }}</td>
                <td style="color:var(--text-muted);font-size:.8rem">
                  {{ a.online ? 'online' : (a.last_seen_s ? `${a.last_seen_s}s ago` : '—') }}
                </td>
                <td style="display:flex;gap:.35rem;align-items:center;justify-content:flex-end;padding-right:.75rem">
                  <button
                    class="btn btn-xs"
                    style="font-size:.7rem;padding:.2rem .45rem"
                    @click="toggleHostInTab(a.hostname)"
                    title="Add to this group"
                  >+ Add</button>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<style scoped>
.remote-tabs {
  display: flex;
  align-items: center;
  gap: .25rem;
  margin-bottom: .75rem;
  flex-wrap: wrap;
}

.remote-tab {
  display: flex;
  align-items: center;
  gap: .3rem;
  padding: .35rem .75rem;
  border-radius: 6px 6px 0 0;
  border: 1px solid var(--border);
  border-bottom: none;
  background: var(--surface);
  color: var(--text-muted);
  cursor: pointer;
  font-size: .85rem;
  white-space: nowrap;
  transition: background .15s, color .15s;
  user-select: none;
}

.remote-tab:hover {
  background: var(--surface-hover, var(--border));
  color: var(--text);
}

.remote-tab.active {
  background: var(--card-bg, var(--bg));
  color: var(--text);
  font-weight: 600;
  border-color: var(--accent);
  border-bottom-color: var(--card-bg, var(--bg));
  z-index: 1;
}

.remote-tab-add {
  font-size: 1.1rem;
  padding: .25rem .6rem;
  color: var(--accent);
  background: transparent;
}

.remote-tab-del {
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  font-size: .95rem;
  padding: 0 .1rem;
  line-height: 1;
  opacity: .6;
}

.remote-tab-del:hover {
  opacity: 1;
  color: var(--danger, #e55);
}

.remote-tab-input {
  background: transparent;
  border: none;
  border-bottom: 1px solid var(--accent);
  color: var(--text);
  font-size: .85rem;
  outline: none;
  width: 90px;
}

tr.dragging {
  opacity: .4;
}
</style>
