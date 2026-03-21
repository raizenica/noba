<script setup>
import { ref, onMounted } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useApi } from '../../composables/useApi'

const authStore = useAuthStore()
const { get, post } = useApi()

const pluginList = ref([])
const pluginLoading = ref(false)
const catalogPlugins = ref([])
const catalogLoading = ref(false)
const catalogError = ref('')
const installingId = ref('')

onMounted(() => {
  if (authStore.isAdmin) {
    loadPlugins()
    loadCatalog()
  }
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

async function loadCatalog() {
  catalogLoading.value = true
  catalogError.value = ''
  try {
    const d = await get('/api/plugins/available')
    catalogPlugins.value = Array.isArray(d) ? d : []
  } catch (e) {
    catalogError.value = e.message || 'Failed to load catalog'
  } finally {
    catalogLoading.value = false
  }
}

async function installPlugin(plugin) {
  installingId.value = plugin.id || plugin.filename
  try {
    await post('/api/plugins/install', { url: plugin.url, filename: plugin.filename })
    await loadPlugins()
    // Mark as installed in catalog
    const idx = catalogPlugins.value.findIndex(p => (p.id || p.filename) === (plugin.id || plugin.filename))
    if (idx >= 0) catalogPlugins.value[idx]._installed = true
  } catch { /* silent */ }
  finally { installingId.value = '' }
}

function isInstalled(plugin) {
  const fname = (plugin.filename || '').replace('.py', '')
  return plugin._installed || pluginList.value.some(p => p.id === fname || p.id === plugin.id)
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

      <!-- Plugin Catalog -->
      <div class="s-section">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:.8rem">
          <span class="s-label" style="margin:0">
            <i class="fas fa-store" style="margin-right:.3rem"></i> Plugin Catalog
          </span>
          <button class="btn btn-sm" @click="loadCatalog" :disabled="catalogLoading">
            <i class="fas fa-sync" :class="catalogLoading ? 'fa-spin' : ''"></i> Refresh
          </button>
        </div>

        <div v-if="catalogLoading" style="text-align:center;padding:1rem;color:var(--text-muted)">
          <i class="fas fa-spinner fa-spin"></i> Loading catalog...
        </div>

        <div v-else-if="catalogError" style="padding:.75rem;font-size:.8rem;color:var(--warning);background:var(--warning-dim);border:1px solid var(--warning-border);border-radius:6px">
          <i class="fas fa-exclamation-triangle"></i> {{ catalogError }}
          <div style="font-size:.72rem;color:var(--text-muted);margin-top:.3rem">
            Set <code>pluginCatalogUrl</code> in Settings → General to enable the catalog.
          </div>
        </div>

        <div v-else-if="catalogPlugins.length === 0" class="empty-msg">
          No catalog configured. Set <code>pluginCatalogUrl</code> in Settings → General to browse available plugins.
        </div>

        <div v-else style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:.6rem">
          <div
            v-for="p in catalogPlugins" :key="p.id || p.filename"
            style="padding:.7rem .75rem;background:var(--surface-2);border:1px solid var(--border);border-radius:6px"
          >
            <div style="display:flex;align-items:center;gap:.5rem;margin-bottom:.4rem">
              <i class="fas" :class="p.icon || 'fa-puzzle-piece'" style="color:var(--accent)"></i>
              <span style="font-weight:600;font-size:.85rem;flex:1">{{ p.name || p.filename }}</span>
              <span style="font-size:.6rem;color:var(--text-dim)">v{{ p.version || '?' }}</span>
            </div>
            <div style="font-size:.75rem;color:var(--text-muted);margin-bottom:.5rem;min-height:2.2em">
              {{ p.description || 'No description available.' }}
            </div>
            <div style="display:flex;align-items:center;gap:.5rem">
              <span v-if="p.author" style="font-size:.65rem;color:var(--text-dim);flex:1">by {{ p.author }}</span>
              <span v-else style="flex:1"></span>
              <span v-if="isInstalled(p)" class="badge bs" style="font-size:.6rem">Installed</span>
              <button
                v-else
                class="btn btn-sm btn-primary"
                @click="installPlugin(p)"
                :disabled="installingId === (p.id || p.filename)"
              >
                <i class="fas" :class="installingId === (p.id || p.filename) ? 'fa-spinner fa-spin' : 'fa-download'"></i>
                Install
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Plugin Directory info -->
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
