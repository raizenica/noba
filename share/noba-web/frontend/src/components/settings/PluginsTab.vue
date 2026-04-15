<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, onMounted } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useApi } from '../../composables/useApi'
import { useSettingsStore } from '../../stores/settings'
import AppModal from '../ui/AppModal.vue'

const authStore = useAuthStore()
const settingsStore = useSettingsStore()
const { get, post } = useApi()

const pluginList = ref([])
const pluginLoading = ref(false)
const bundledPlugins = ref([])
const bundledLoading = ref(false)
const catalogPlugins = ref([])
const catalogLoading = ref(false)
const catalogError = ref('')
const installingId = ref('')

// Config modal
const configModal = ref(false)
const configPlugin = ref(null)
const configSchema = ref({})
const configValues = ref({})
const configSaving = ref(false)
const configError = ref('')

// Catalog URL
const catalogUrl = ref('')
const catalogUrlSaving = ref(false)

onMounted(() => {
  if (authStore.isAdmin) {
    loadPlugins()
    loadBundled()
    loadCatalog()
    catalogUrl.value = settingsStore.settings?.pluginCatalogUrl || ''
  }
})

async function loadPlugins() {
  pluginLoading.value = true
  try {
    const d = await get('/api/plugins/managed')
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
    const action = enabled ? 'enable' : 'disable'
    await post(`/api/plugins/${id}/${action}`, {})
    const p = pluginList.value.find(x => x.id === id)
    if (p) p.enabled = enabled
  } catch { /* silent */ }
}

async function loadBundled() {
  bundledLoading.value = true
  try {
    const d = await get('/api/plugins/bundled')
    bundledPlugins.value = Array.isArray(d) ? d : []
  } catch { /* silent */ }
  finally { bundledLoading.value = false }
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
    await post('/api/plugins/install', {
      filename: plugin.filename,
      url: plugin.url || '',
      bundled: !!plugin.bundled,
    })
    await loadPlugins()
    // Mark as installed
    const markInstalled = (list) => {
      const idx = list.findIndex(p => (p.id || p.filename) === (plugin.id || plugin.filename))
      if (idx >= 0) list[idx]._installed = true
    }
    markInstalled(bundledPlugins.value)
    markInstalled(catalogPlugins.value)
  } catch { /* silent */ }
  finally { installingId.value = '' }
}

function isInstalled(plugin) {
  const fname = (plugin.filename || '').replace('.py', '')
  return plugin._installed || pluginList.value.some(p => p.id === fname || p.id === plugin.id)
}

// Config modal
async function openConfig(plugin) {
  configPlugin.value = plugin
  configError.value = ''
  configSaving.value = false
  try {
    const d = await get(`/api/plugins/${plugin.id}/config`)
    configSchema.value = d.schema || {}
    configValues.value = { ...(d.config || {}) }
    configModal.value = true
  } catch (e) {
    configError.value = e.message || 'Failed to load config'
  }
}

async function saveConfig() {
  configSaving.value = true
  configError.value = ''
  try {
    await post(`/api/plugins/${configPlugin.value.id}/config`, configValues.value)
    configModal.value = false
  } catch (e) {
    configError.value = e.message || 'Failed to save config'
  } finally {
    configSaving.value = false
  }
}

function addListItem(key) {
  if (!configValues.value[key]) configValues.value[key] = []
  configValues.value[key].push('')
}

function removeListItem(key, index) {
  configValues.value[key].splice(index, 1)
}

// Catalog URL
async function saveCatalogUrl() {
  catalogUrlSaving.value = true
  try {
    const current = settingsStore.settings || {}
    await post('/api/settings', { ...current, pluginCatalogUrl: catalogUrl.value })
    await settingsStore.fetchSettings()
    await loadCatalog()
  } catch { /* silent */ }
  finally { catalogUrlSaving.value = false }
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
      <!-- Installed Plugins -->
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
          No plugins installed. Install from the catalog below or place <code>.py</code> files in <code>~/.config/noba/plugins/</code>.
        </div>

        <div style="display:flex;flex-direction:column;gap:.5rem">
          <div
            v-for="p in pluginList" :key="p.id"
            style="display:flex;align-items:center;gap:.75rem;padding:.6rem .75rem;background:var(--surface-2);border:1px solid var(--border);border-radius:6px"
          >
            <div style="width:2rem;height:2rem;display:flex;align-items:center;justify-content:center;background:var(--surface);border-radius:4px;flex-shrink:0">
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
              <button
                v-if="p.has_config"
                class="btn btn-sm"
                @click="openConfig(p)"
                title="Configure plugin"
                style="color:var(--accent)"
              >
                <i class="fas fa-cog"></i>
              </button>
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

      <!-- Bundled Catalog -->
      <div class="s-section">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:.8rem">
          <span class="s-label" style="margin:0">
            <i class="fas fa-box-open" style="margin-right:.3rem"></i> Bundled Plugins
          </span>
        </div>

        <div v-if="bundledLoading" style="text-align:center;padding:1rem;color:var(--text-muted)">
          <i class="fas fa-spinner fa-spin"></i> Loading...
        </div>

        <div v-else-if="bundledPlugins.length === 0" class="empty-msg">
          No bundled plugins available.
        </div>

        <div v-else style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:.6rem">
          <div
            v-for="p in bundledPlugins" :key="p.id || p.filename"
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
              <span style="font-size:.6rem;color:var(--text-dim);flex:1">
                <i class="fas fa-cube" style="margin-right:.2rem"></i> Bundled
              </span>
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

      <!-- Remote Catalog -->
      <div class="s-section">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:.8rem">
          <span class="s-label" style="margin:0">
            <i class="fas fa-store" style="margin-right:.3rem"></i> Remote Catalog
          </span>
          <button class="btn btn-sm" @click="loadCatalog" :disabled="catalogLoading">
            <i class="fas fa-sync" :class="catalogLoading ? 'fa-spin' : ''"></i> Refresh
          </button>
        </div>

        <!-- Catalog URL -->
        <div style="display:flex;gap:.4rem;margin-bottom:.8rem;align-items:center">
          <input
            v-model="catalogUrl"
            class="input"
            type="url"
            placeholder="https://example.com/noba-plugins.json"
            style="flex:1;font-size:.8rem"
          >
          <button class="btn btn-sm" @click="saveCatalogUrl" :disabled="catalogUrlSaving">
            <i class="fas" :class="catalogUrlSaving ? 'fa-spinner fa-spin' : 'fa-save'"></i> Save
          </button>
        </div>

        <div v-if="catalogLoading" style="text-align:center;padding:1rem;color:var(--text-muted)">
          <i class="fas fa-spinner fa-spin"></i> Loading catalog...
        </div>

        <div v-else-if="!catalogUrl && catalogPlugins.length === 0" class="empty-msg">
          Enter a catalog URL above to browse community plugins.
        </div>

        <div v-else-if="catalogError" style="padding:.75rem;font-size:.8rem;color:var(--warning);background:var(--surface-2);border:1px solid var(--border);border-radius:6px">
          <i class="fas fa-exclamation-triangle"></i> {{ catalogError }}
        </div>

        <div v-else-if="catalogPlugins.length === 0 && catalogUrl" class="empty-msg">
          No plugins found at the configured catalog URL.
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
        <span class="s-label">Plugin Development</span>
        <div style="font-size:.78rem;color:var(--text-muted)">
          Plugins are Python files placed in <code>~/.config/noba/plugins/</code>.<br>
          Each plugin must export <code>PLUGIN_NAME</code>, <code>PLUGIN_VERSION</code>, and a <code>register(app, db)</code> function.<br>
          Plugins can define <code>PLUGIN_CONFIG_SCHEMA</code> to expose configurable settings in the UI.<br>
          Plugins can add API routes, dashboard cards, automation types, and metric collectors.
        </div>
      </div>
    </template>

    <!-- Config Modal -->
    <AppModal :show="configModal" :title="'Configure: ' + (configPlugin?.name || '')" width="560px" @close="configModal = false">
      <div v-if="configError" style="color:var(--danger);font-size:.8rem;margin-bottom:.6rem">
        <i class="fas fa-exclamation-triangle"></i> {{ configError }}
      </div>

      <div style="display:flex;flex-direction:column;gap:.7rem">
        <div v-for="(field, key) in configSchema" :key="key">
          <label style="display:block;font-size:.78rem;font-weight:600;margin-bottom:.25rem;color:var(--text)">
            {{ field.label || key }}
            <span v-if="field.required" style="color:var(--danger)">*</span>
          </label>

          <!-- String -->
          <input
            v-if="field.type === 'string'"
            v-model="configValues[key]"
            class="input"
            :type="field.secret ? 'password' : 'text'"
            :placeholder="field.placeholder || ''"
            style="width:100%;font-size:.8rem"
          >

          <!-- Number -->
          <input
            v-else-if="field.type === 'number'"
            v-model.number="configValues[key]"
            class="input"
            type="number"
            :min="field.min"
            :max="field.max"
            :placeholder="field.placeholder || ''"
            style="width:100%;font-size:.8rem"
          >

          <!-- Boolean -->
          <label v-else-if="field.type === 'boolean'" style="display:flex;align-items:center;gap:.4rem;cursor:pointer">
            <input
              v-model="configValues[key]"
              type="checkbox"
              style="accent-color:var(--accent)"
            >
            <span style="font-size:.78rem;color:var(--text-muted)">{{ field.label || key }}</span>
          </label>

          <!-- List -->
          <div v-else-if="field.type === 'list'">
            <div v-for="(item, idx) in (configValues[key] || [])" :key="idx" style="display:flex;gap:.3rem;margin-bottom:.3rem">
              <input
                v-model="configValues[key][idx]"
                class="input"
                type="text"
                style="flex:1;font-size:.8rem"
              >
              <button class="btn btn-sm" @click="removeListItem(key, idx)" style="color:var(--danger)" title="Remove">
                <i class="fas fa-times"></i>
              </button>
            </div>
            <button class="btn btn-sm" @click="addListItem(key)" style="font-size:.72rem">
              <i class="fas fa-plus" style="margin-right:.2rem"></i> Add
            </button>
          </div>
        </div>
      </div>

      <template #footer>
        <button class="btn btn-sm" @click="configModal = false">Cancel</button>
        <button class="btn btn-sm btn-primary" @click="saveConfig" :disabled="configSaving">
          <i class="fas" :class="configSaving ? 'fa-spinner fa-spin' : 'fa-save'" style="margin-right:.3rem"></i>
          Save
        </button>
      </template>
    </AppModal>
  </div>
</template>
