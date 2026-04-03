<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, onMounted } from 'vue'
import { useRouter }             from 'vue-router'
import { useApi }                from '../../composables/useApi'
import { useAuthStore }          from '../../stores/auth'
import { useNotificationsStore } from '../../stores/notifications'
import AppModal                  from '../ui/AppModal.vue'

const router    = useRouter()
const { get, post } = useApi()
const authStore = useAuthStore()
const notify    = useNotificationsStore()

// ── Playbook list ───────────────────────────────────────────────────────────
const playbooks = ref([])
const loading   = ref(false)

async function fetchPlaybooks() {
  loading.value = true
  try {
    const data = await get('/api/playbooks')
    playbooks.value = Array.isArray(data) ? data : []
  } catch (e) {
    notify.addToast('Failed to load playbooks: ' + e.message, 'error')
  } finally {
    loading.value = false
  }
}

// ── Install modal ───────────────────────────────────────────────────────────
const showInstallModal  = ref(false)
const installing        = ref(false)
const installTarget     = ref(null)   // playbook object being installed
const installName       = ref('')

function openInstall(pb) {
  installTarget.value = pb
  installName.value   = pb.name || ''
  showInstallModal.value = true
}

function closeInstall() {
  showInstallModal.value = false
  installTarget.value    = null
  installName.value      = ''
}

async function confirmInstall() {
  if (!installTarget.value) return
  if (!installName.value.trim()) {
    notify.addToast('Name is required', 'error')
    return
  }
  installing.value = true
  try {
    await post(`/api/playbooks/${installTarget.value.id}/install`, {
      name: installName.value.trim(),
    })
    notify.addToast(`Playbook "${installName.value.trim()}" installed`, 'success')
    closeInstall()
    router.push({ name: 'automations' })
  } catch (e) {
    notify.addToast('Install failed: ' + e.message, 'error')
  } finally {
    installing.value = false
  }
}

// ── Category badge ──────────────────────────────────────────────────────────
function categoryClass(cat) {
  if (!cat) return 'bn'
  const c = cat.toLowerCase()
  if (c === 'maintenance') return 'ba'   // blue accent
  if (c === 'backup')      return 'bs'   // green success
  return 'bn'
}

// ── Node count ──────────────────────────────────────────────────────────────
function nodeCount(pb) {
  try {
    return (pb.config && Array.isArray(pb.config.nodes)) ? pb.config.nodes.length : 0
  } catch {
    return 0
  }
}

onMounted(fetchPlaybooks)
</script>

<template>
  <div>
    <!-- Header -->
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:.8rem">
      <span style="font-size:.75rem;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:var(--text-muted)">
        <i class="fas fa-book-open" style="margin-right:.3rem"></i>
        Playbook Templates
      </span>
      <button class="btn btn-sm" :disabled="loading" @click="fetchPlaybooks">
        <i class="fas" :class="loading ? 'fa-spinner fa-spin' : 'fa-sync-alt'"></i>
      </button>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="empty-msg">Loading...</div>

    <!-- Empty state -->
    <div v-else-if="playbooks.length === 0" class="empty-msg">
      No playbook templates available.
    </div>

    <!-- Grid -->
    <div
      v-else
      style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:.8rem"
    >
      <div
        v-for="pb in playbooks"
        :key="pb.id"
        style="
          padding:.9rem;
          border:1px solid var(--border);
          border-radius:6px;
          background:var(--surface-2);
          display:flex;
          flex-direction:column;
          gap:.5rem;
        "
      >
        <!-- Title row -->
        <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:.4rem">
          <span style="font-weight:600;font-size:.88rem;line-height:1.3">
            {{ pb.name }}
          </span>
          <span
            v-if="pb.category"
            class="badge"
            :class="categoryClass(pb.category)"
            style="font-size:.55rem;flex-shrink:0;margin-top:.1rem"
          >
            {{ pb.category }}
          </span>
        </div>

        <!-- Description -->
        <div
          v-if="pb.description"
          style="font-size:.76rem;color:var(--text-muted);line-height:1.45;flex:1"
        >
          {{ pb.description }}
        </div>

        <!-- Meta row -->
        <div style="display:flex;align-items:center;gap:.6rem;font-size:.72rem;color:var(--text-muted)">
          <span v-if="nodeCount(pb) > 0">
            <i class="fas fa-sitemap" style="margin-right:.25rem"></i>{{ nodeCount(pb) }} node{{ nodeCount(pb) !== 1 ? 's' : '' }}
          </span>
          <span v-if="pb.type">
            <i class="fas fa-tag" style="margin-right:.25rem"></i>{{ pb.type }}
          </span>
        </div>

        <!-- Install button (operator+) -->
        <div v-if="authStore.isOperator" style="margin-top:.2rem">
          <button
            class="btn btn-sm btn-primary"
            style="width:100%"
            @click="openInstall(pb)"
          >
            <i class="fas fa-download" style="margin-right:.35rem"></i>Install
          </button>
        </div>
      </div>
    </div>

    <!-- ── Install modal ─────────────────────────────────────────────────── -->
    <AppModal
      :show="showInstallModal"
      title="Install Playbook"
      width="420px"
      @close="closeInstall"
    >
      <div style="padding:1rem;display:flex;flex-direction:column;gap:.75rem">
        <div v-if="installTarget" style="font-size:.82rem;color:var(--text-muted)">
          Installing template:
          <strong style="color:var(--text)">{{ installTarget.name }}</strong>
        </div>
        <div>
          <label class="field-label">Automation name</label>
          <input
            v-model="installName"
            type="text"
            class="field-input"
            placeholder="My playbook name"
            style="width:100%"
            @keydown.enter="confirmInstall"
          />
        </div>
      </div>
      <template #footer>
        <button class="btn" @click="closeInstall">Cancel</button>
        <button
          class="btn btn-primary"
          :disabled="installing || !installName.trim()"
          @click="confirmInstall"
        >
          <i
            class="fas"
            :class="installing ? 'fa-spinner fa-spin' : 'fa-check'"
            style="margin-right:.35rem"
          ></i>
          {{ installing ? 'Installing…' : 'Confirm' }}
        </button>
      </template>
    </AppModal>
  </div>
</template>
