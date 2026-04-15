<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, onMounted } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useApi } from '../../composables/useApi'
import { useModalsStore } from '../../stores/modals'
import AppModal from '../ui/AppModal.vue'
import { USER_ACTION_MSG_TIMEOUT_MS } from '../../constants'

const authStore = useAuthStore()
const { post } = useApi()
const modals = useModalsStore()

const userList = ref([])
const usersLoading = ref(false)

const showAddForm = ref(false)
const newUsername = ref('')
const newPassword = ref('')
const newRole = ref('viewer')

const showPassModal = ref(false)
const passModalUser = ref('')
const passModalNew = ref('')
const passModalConfirm = ref('')
const passModalError = ref('')

const actionMsg = ref('')

onMounted(() => {
  if (authStore.isAdmin) fetchUsers()
})

async function fetchUsers() {
  usersLoading.value = true
  try {
    const d = await post('/api/admin/users', { action: 'list' })
    userList.value = Array.isArray(d) ? d : (d.users || [])
  } catch { /* silent */ }
  finally { usersLoading.value = false }
}

async function addUser() {
  if (!newUsername.value || !newPassword.value) return
  try {
    await post('/api/admin/users', {
      action: 'add',
      username: newUsername.value,
      password: newPassword.value,
      role: newRole.value,
    })
    actionMsg.value = `User "${newUsername.value}" added.`
    showAddForm.value = false
    newUsername.value = ''
    newPassword.value = ''
    newRole.value = 'viewer'
    await fetchUsers()
  } catch (e) {
    actionMsg.value = 'Add failed: ' + e.message
  }
  setTimeout(() => { actionMsg.value = '' }, USER_ACTION_MSG_TIMEOUT_MS)
}

async function confirmRemoveUser(username) {
  if (!await modals.confirm(`Remove user "${username}"?`)) return
  try {
    await post('/api/admin/users', { action: 'remove', username })
    actionMsg.value = `User "${username}" removed.`
    await fetchUsers()
  } catch (e) {
    actionMsg.value = 'Remove failed: ' + e.message
  }
  setTimeout(() => { actionMsg.value = '' }, USER_ACTION_MSG_TIMEOUT_MS)
}

function openPassModal(username) {
  passModalUser.value = username
  passModalNew.value = ''
  passModalConfirm.value = ''
  passModalError.value = ''
  showPassModal.value = true
}

async function changePassword() {
  passModalError.value = ''
  if (!passModalNew.value) { passModalError.value = 'Password required.'; return }
  if (passModalNew.value !== passModalConfirm.value) { passModalError.value = 'Passwords do not match.'; return }
  try {
    await post('/api/admin/users', {
      action: 'change_password',
      username: passModalUser.value,
      password: passModalNew.value,
    })
    showPassModal.value = false
    actionMsg.value = 'Password updated.'
  } catch (e) {
    passModalError.value = 'Failed: ' + e.message
  }
  setTimeout(() => { actionMsg.value = '' }, USER_ACTION_MSG_TIMEOUT_MS)
}

function roleBadgeClass(role) {
  if (role === 'admin') return 'ba'
  if (role === 'operator') return 'bw'
  return 'bn'
}
</script>

<template>
  <div>
    <!-- Admin gate -->
    <div v-if="!authStore.isAdmin" style="text-align:center;padding:3rem;color:var(--text-muted)">
      <i class="fas fa-lock" style="font-size:2rem;margin-bottom:.75rem;display:block;opacity:.4"></i>
      Admin role required to manage users.
    </div>

    <template v-else>
      <div class="s-section">
        <span class="s-label">User Management</span>

        <!-- Action message -->
        <div v-if="actionMsg" style="font-size:.82rem;color:var(--text-muted);margin-bottom:.75rem">{{ actionMsg }}</div>

        <!-- Add user form -->
        <div v-if="showAddForm" style="margin-bottom:1rem;border:1px solid var(--border);padding:1rem;border-radius:4px">
          <div class="field-2">
            <div>
              <label class="field-label" for="new-username">Username</label>
              <input id="new-username" class="field-input" type="text" v-model="newUsername"
                @keyup.enter="addUser" autocomplete="username">
            </div>
            <div>
              <label class="field-label" for="new-password">Password</label>
              <input id="new-password" class="field-input" type="password" v-model="newPassword"
                @keyup.enter="addUser" autocomplete="new-password">
            </div>
          </div>
          <div style="margin-top:.75rem">
            <label class="field-label" for="new-role">Role</label>
            <select id="new-role" v-model="newRole" class="field-input field-select" style="max-width:180px">
              <option value="viewer">viewer</option>
              <option value="operator">operator</option>
              <option value="admin">admin</option>
            </select>
            <button class="btn btn-sm btn-primary" style="margin-left:1rem" @click="addUser">
              <i class="fas fa-check"></i> Save
            </button>
            <button class="btn btn-sm" style="margin-left:.4rem" @click="showAddForm = false; newUsername = ''; newPassword = ''; newRole = 'viewer'">
              Cancel
            </button>
          </div>
        </div>

        <!-- User list -->
        <div style="display:flex;flex-direction:column;gap:.45rem;margin-bottom:.75rem">
          <div
            v-for="u in userList" :key="u.username"
            style="display:flex;justify-content:space-between;padding:.5rem;background:var(--surface-2);border:1px solid var(--border);border-radius:4px"
          >
            <div>
              <i class="fas fa-user" style="color:var(--text-muted);margin-right:.5rem"></i>
              <span>{{ u.username }}</span>
              <span class="badge" :class="roleBadgeClass(u.role)" style="margin-left:.5rem">{{ u.role }}</span>
            </div>
            <div style="display:flex;gap:.5rem">
              <button class="btn btn-sm" @click="openPassModal(u.username)" :aria-label="'Change password for ' + u.username">
                <i class="fas fa-key"></i>
              </button>
              <button
                v-if="u.username !== authStore.username"
                class="btn btn-sm btn-danger"
                @click="confirmRemoveUser(u.username)"
                :aria-label="'Remove user ' + u.username"
              >
                <i class="fas fa-trash"></i>
              </button>
            </div>
          </div>
          <div v-if="userList.length === 0 && !usersLoading" style="text-align:center;padding:2rem;background:var(--surface);border:1px dashed var(--border);border-radius:6px;color:var(--text-muted)">
            <i class="fas fa-users" style="font-size:2rem;display:block;margin-bottom:.75rem;opacity:.3"></i>
            No users loaded yet.
            <br v-if="authStore.isAdmin">
            <button v-if="authStore.isAdmin" class="btn btn-primary" style="margin-top:1rem" @click="showAddForm = true">
              <i class="fas fa-plus"></i> Create First User
            </button>
          </div>
        </div>

        <!-- Buttons -->
        <div style="display:flex;gap:.5rem">
          <button class="btn btn-sm" @click="fetchUsers">
            <i class="fas fa-sync" :class="usersLoading ? 'fa-spin' : ''"></i> Refresh
          </button>
          <button class="btn btn-sm btn-primary" @click="showAddForm = !showAddForm">
            <i class="fas fa-plus"></i> Add User
          </button>
        </div>
      </div>

      <!-- Change Password Modal -->
      <AppModal :show="showPassModal" :title="`Change password — ${passModalUser}`" @close="showPassModal = false">
        <div style="padding:1rem;display:flex;flex-direction:column;gap:.75rem">
          <div>
            <label class="field-label">New Password</label>
            <input class="field-input" type="password" v-model="passModalNew" autocomplete="new-password">
          </div>
          <div>
            <label class="field-label">Confirm Password</label>
            <input class="field-input" type="password" v-model="passModalConfirm" autocomplete="new-password" @keyup.enter="changePassword">
          </div>
          <div v-if="passModalError" style="color:var(--danger);font-size:.82rem">{{ passModalError }}</div>
        </div>
        <template #footer>
          <button class="btn btn-sm" @click="showPassModal = false">Cancel</button>
          <button class="btn btn-sm btn-primary" @click="changePassword">
            <i class="fas fa-check"></i> Update
          </button>
        </template>
      </AppModal>
    </template>
  </div>
</template>
