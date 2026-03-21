<script setup>
import { ref, onMounted } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useApi } from '../../composables/useApi'

const authStore = useAuthStore()
const { get, post } = useApi()

const pluginList = ref([])
const pluginLoading = ref(false)

onMounted(() => {
  if (authStore.isAdmin) loadPlugins()
})

async function loadPlugins() {
  pluginLoading.value = true
  try {
    const d = await get('/api/plugins')
    pluginList.value = Array.isArray(d) ? d : (d.plugins || [])
  } catch { /* silent */ }
  finally { pluginLoading.value = false }
}

async function reloadPlugins() {
  pluginLoading.value = true
  try {
    await post('/api/plugins/reload', {})
    await loadPlugins()
  } catch { /* silent */ }
  finally { pluginLoading.value = false }
}

async function togglePlugin(id, enabled) {
  try {
    await post(`/api/plugins/${id}/toggle`, { enabled })
    const p = pluginList.value.find(x => x.id === id)
    if (p) p.enabled = enabled
  } catch { /* silent */ }
}
</script>

<template>
  <div>
    <!-- Admin gate -->
    <div v-if="!authStore.isAdmin" style="text-align:center;padding:3rem;color:var(--text-muted)">
      <i class="fas fa-lock" style="font-size:2rem;margin-bottom:.75rem;display:block;opacity:.4"></i>
      Admin role required to manage plugins.
    </div>

    <template v-else>
      <div class="s-section">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:.8rem">
          <span class="s-label" style="margin:0">
            <i class="fas fa-puzzle-piece" style="margin-right:.3rem"></i> Installed Plugins
          </span>
          <button class="btn btn-sm" @click="reloadPlugins" :disabled="pluginLoading">
            <i class="fas fa-sync" :class="pluginLoading ? 'fa-spin' : ''"></i> Reload Plugins
          </button>
        </div>

        <div v-if="pluginLoading" style="text-align:center;padding:1rem;color:var(--text-muted)">
          <i class="fas fa-spinner fa-spin"></i> Loading plugins...
        </div>

        <div v-else-if="pluginList.length === 0" class="empty-msg">
          No plugins installed. Place <code>.py</code> files in <code>~/.config/noba/plugins/</code> to get started.
        </div>

        <div style="display:flex;flex-direction:column;gap:.5rem">
          <div
            v-for="p in pluginList" :key="p.id"
            class="plugin-card"
            style="display:flex;align-items:center;gap:.75rem;padding:.6rem .75rem;background:var(--surface-2);border:1px solid var(--border);border-radius:6px"
          >
            <div class="plugin-icon" style="width:2rem;height:2rem;display:flex;align-items:center;justify-content:center;background:var(--surface);border-radius:4px;flex-shrink:0">
              <i class="fas" :class="p.icon || 'fa-puzzle-piece'" style="color:var(--accent)"></i>
            </div>
            <div style="flex:1;min-width:0">
              <div style="display:flex;align-items:center;gap:.4rem">
                <span style="font-weight:600;font-size:.85rem">{{ p.name }}</span>
                <span style="font-size:.65rem;color:var(--text-muted)">v{{ p.version || '?' }}</span>
              </div>
              <div style="font-size:.75rem;color:var(--text-muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">
                {{ p.description || 'No description' }}
              </div>
              <div style="font-size:.65rem;color:var(--text-dim);margin-top:2px">
                {{ p.id }}
                <span v-if="p.error" style="color:var(--danger);margin-left:.5rem">Error: {{ p.error }}</span>
              </div>
            </div>
            <div style="display:flex;align-items:center;gap:.5rem;flex-shrink:0">
              <span class="badge" :class="p.enabled ? 'bs' : 'bd'" style="font-size:.65rem">
                {{ p.enabled ? 'Enabled' : 'Disabled' }}
              </span>
              <button
                class="btn btn-sm"
                @click="togglePlugin(p.id, !p.enabled)"
                :title="p.enabled ? 'Disable plugin' : 'Enable plugin'"
                :style="p.enabled ? 'color:var(--danger)' : 'color:var(--success)'"
              >
                <i class="fas" :class="p.enabled ? 'fa-toggle-on' : 'fa-toggle-off'" style="font-size:1.2rem"></i>
              </button>
            </div>
          </div>
        </div>
      </div>

      <div class="s-section">
        <span class="s-label">Plugin Directory</span>
        <div style="font-size:.78rem;color:var(--text-muted)">
          Plugins are Python files placed in <code>~/.config/noba/plugins/</code>.<br>
          Each plugin must export <code>PLUGIN_NAME</code>, <code>PLUGIN_VERSION</code>, and a <code>register(app, db)</code> function.<br>
          Plugins can add API routes, dashboard cards, automation types, and metric collectors.
        </div>
      </div>
    </template>
  </div>
</template>
