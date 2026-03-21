<script setup>
import { ref, onMounted, nextTick } from 'vue'
import { useApi } from '../../composables/useApi'
import { useAuthStore } from '../../stores/auth'
import { useNotificationsStore } from '../../stores/notifications'

const { get, post, put } = useApi()
const authStore   = useAuthStore()
const notif       = useNotificationsStore()

// ── Alert incidents (auto-generated) ──────────────────────────────────────────
const incidents        = ref([])
const incidentLoading  = ref(false)

async function fetchIncidents() {
  incidentLoading.value = true
  try {
    const data = await get('/api/incidents?limit=100')
    incidents.value = Array.isArray(data) ? data : []
  } catch { /* silent */ }
  finally { incidentLoading.value = false }
}

async function resolveIncident(id) {
  try {
    await post(`/api/incidents/${id}/resolve`)
    notif.addToast('Incident resolved', 'success')
    await fetchIncidents()
  } catch { /* silent */ }
}

// ── Status incidents (war room) ───────────────────────────────────────────────
const spIncidents = ref([])

async function fetchStatusIncidents() {
  try {
    const data = await get('/api/status/incidents')
    spIncidents.value = (data && data.incidents) ? data.incidents : []
  } catch { /* silent */ }
}

// ── War room ──────────────────────────────────────────────────────────────────
const warRoomIncident  = ref(null)
const warRoomMessages  = ref([])
const warRoomLoading   = ref(false)
const warRoomMsg       = ref('')
const warRoomAssignTo  = ref('')
const threadRef        = ref(null)

// user list for assignment
const userList = ref([])
async function fetchUserList() {
  try {
    const data = await get('/api/users')
    userList.value = Array.isArray(data) ? data : []
  } catch { /* silent */ }
}

async function openWarRoom(incidentId) {
  warRoomLoading.value = true
  warRoomMessages.value = []
  warRoomMsg.value = ''
  warRoomAssignTo.value = ''
  try {
    const data = await get('/api/status/incidents')
    const found = ((data && data.incidents) || []).find(i => i.id === incidentId)
    warRoomIncident.value = found || null
    const msgData = await get(`/api/incidents/${incidentId}/messages`)
    warRoomMessages.value = (msgData && msgData.messages) ? msgData.messages : []
    await nextTick()
    scrollThread()
  } catch { /* silent */ }
  finally { warRoomLoading.value = false }
}

function closeWarRoom() {
  warRoomIncident.value  = null
  warRoomMessages.value  = []
  warRoomMsg.value       = ''
}

async function sendWarRoomMessage() {
  if (!warRoomIncident.value || !warRoomMsg.value.trim()) return
  try {
    await post(`/api/incidents/${warRoomIncident.value.id}/messages`, {
      message: warRoomMsg.value.trim(),
      msg_type: 'comment',
    })
    warRoomMsg.value = ''
    await refreshWarRoomMessages()
  } catch (e) {
    notif.addToast('Error: ' + e.message, 'error')
  }
}

async function refreshWarRoomMessages() {
  if (!warRoomIncident.value) return
  try {
    const data = await get(`/api/incidents/${warRoomIncident.value.id}/messages`)
    warRoomMessages.value = (data && data.messages) ? data.messages : []
    await nextTick()
    scrollThread()
  } catch { /* silent */ }
}

async function assignWarRoomIncident() {
  if (!warRoomIncident.value || !warRoomAssignTo.value) return
  try {
    await put(`/api/incidents/${warRoomIncident.value.id}/assign`, {
      assigned_to: warRoomAssignTo.value,
    })
    warRoomIncident.value.assigned_to = warRoomAssignTo.value
    notif.addToast('Incident assigned to ' + warRoomAssignTo.value, 'success')
    await refreshWarRoomMessages()
    await fetchStatusIncidents()
  } catch (e) {
    notif.addToast('Error: ' + e.message, 'error')
  }
}

function scrollThread() {
  if (threadRef.value) {
    threadRef.value.scrollTop = threadRef.value.scrollHeight
  }
}

function severityBorderStyle(severity) {
  if (severity === 'critical') return 'border-color:var(--danger);background:rgba(255,23,68,.05)'
  if (severity === 'major')    return 'border-color:var(--warning);background:rgba(255,179,0,.05)'
  return 'border-color:var(--accent);background:rgba(0,200,255,.05)'
}

function incidentSeverityBorderStyle(severity) {
  if (severity === 'critical') return 'border-color:var(--danger);background:rgba(255,23,68,.05)'
  if (severity === 'warning')  return 'border-color:var(--warning);background:rgba(255,179,0,.05)'
  return 'border-color:var(--accent);background:rgba(0,200,255,.05)'
}

function msgTypeBadgeStyle(msgType) {
  if (msgType === 'system') return 'background:rgba(0,200,255,.15);color:var(--accent)'
  if (msgType === 'action') return 'background:rgba(255,179,0,.15);color:var(--warning)'
  if (msgType === 'note')   return 'background:rgba(156,39,176,.15);color:#ce93d8'
  return 'background:var(--surface-2);color:var(--text-muted)'
}

function msgBgStyle(msgType) {
  if (msgType === 'system') return 'background:var(--surface-2);border-left:3px solid var(--accent)'
  return 'background:var(--bg);border-left:3px solid var(--border)'
}

onMounted(() => {
  fetchIncidents()
  fetchStatusIncidents()
  fetchUserList()
})
</script>

<template>
  <div>
    <!-- ── War Room view ──────────────────────────────────────────────────── -->
    <div v-if="warRoomIncident" style="margin-bottom:1rem">
      <!-- Header -->
      <div style="display:flex;align-items:center;gap:.5rem;margin-bottom:.8rem;flex-wrap:wrap">
        <button class="btn btn-xs" @click="closeWarRoom">
          <i class="fas fa-arrow-left"></i> Back
        </button>
        <span style="font-weight:700;font-size:.95rem">{{ warRoomIncident.title }}</span>
        <span
          style="font-size:.6rem;padding:.15rem .5rem;border-radius:3px;text-transform:uppercase;font-weight:700"
          :style="severityBorderStyle(warRoomIncident.severity)"
        >{{ warRoomIncident.severity }}</span>
        <span style="font-size:.6rem;padding:.15rem .5rem;border-radius:3px;background:var(--surface-2);color:var(--text-muted);text-transform:uppercase;font-weight:600">
          {{ warRoomIncident.status }}
        </span>
      </div>

      <!-- Assignment row -->
      <div style="display:flex;gap:.5rem;margin-bottom:.8rem;flex-wrap:wrap;align-items:center">
        <span style="font-size:.7rem;color:var(--text-muted)">Assigned to:</span>
        <span style="font-size:.75rem;font-weight:600">
          {{ warRoomIncident.assigned_to || 'Unassigned' }}
        </span>
        <template v-if="authStore.isOperator">
          <div style="display:flex;gap:.3rem;align-items:center">
            <select
              v-model="warRoomAssignTo"
              class="field-input"
              style="font-size:.7rem;padding:.15rem .3rem;width:120px"
            >
              <option value="">-- assign --</option>
              <option
                v-for="u in userList"
                :key="u.username || u"
                :value="u.username || u"
              >{{ u.username || u }}</option>
            </select>
            <button
              class="btn btn-xs"
              :disabled="!warRoomAssignTo"
              @click="assignWarRoomIncident"
            >
              <i class="fas fa-user-tag"></i> Assign
            </button>
          </div>
        </template>
      </div>

      <!-- Message thread -->
      <div
        ref="threadRef"
        style="background:var(--surface);border:1px solid var(--border);border-radius:6px;max-height:350px;overflow-y:auto;padding:.6rem;margin-bottom:.6rem"
      >
        <div v-if="warRoomLoading" class="empty-msg">Loading messages...</div>
        <template v-else>
          <div
            v-for="msg in warRoomMessages"
            :key="msg.id"
            style="margin-bottom:.5rem;padding:.4rem .6rem;border-radius:5px"
            :style="msgBgStyle(msg.msg_type)"
          >
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.2rem">
              <div style="display:flex;align-items:center;gap:.4rem">
                <span style="font-size:.75rem;font-weight:700">{{ msg.author }}</span>
                <span
                  style="font-size:.55rem;padding:.1rem .35rem;border-radius:3px;text-transform:uppercase;font-weight:600"
                  :style="msgTypeBadgeStyle(msg.msg_type)"
                >{{ msg.msg_type }}</span>
              </div>
              <span style="font-size:.6rem;color:var(--text-muted)">
                {{ new Date((msg.created_at || 0) * 1000).toLocaleString() }}
              </span>
            </div>
            <div style="font-size:.8rem;white-space:pre-wrap;word-break:break-word">{{ msg.message }}</div>
          </div>
          <div
            v-if="warRoomMessages.length === 0"
            style="font-size:.75rem;color:var(--text-muted);text-align:center;padding:1rem 0"
          >No messages yet. Start the conversation.</div>
        </template>
      </div>

      <!-- Message input -->
      <div v-if="authStore.isOperator" style="display:flex;gap:.4rem">
        <input
          v-model="warRoomMsg"
          class="field-input"
          style="flex:1;font-size:.8rem"
          type="text"
          placeholder="Type a message..."
          @keydown.enter="sendWarRoomMessage"
        >
        <button
          class="btn btn-sm btn-primary"
          :disabled="!warRoomMsg.trim()"
          @click="sendWarRoomMessage"
        >
          <i class="fas fa-paper-plane"></i> Send
        </button>
      </div>
    </div>

    <!-- ── Incident lists (shown when war room is closed) ─────────────────── -->
    <div v-else>
      <!-- Status incidents with war room -->
      <div style="margin-bottom:1.2rem">
        <div style="display:flex;align-items:center;gap:.5rem;margin-bottom:.5rem">
          <span style="font-weight:700;font-size:.85rem">
            <i class="fas fa-comments" style="margin-right:.3rem"></i>Status Incidents
          </span>
          <span style="font-size:.6rem;color:var(--text-muted)">(click to open war room)</span>
        </div>
        <div
          v-for="sinc in spIncidents"
          :key="sinc.id"
          style="display:flex;gap:.6rem;margin-bottom:.5rem;padding:.5rem;border-left:3px solid;border-radius:0 4px 4px 0;cursor:pointer;transition:background .15s"
          :style="severityBorderStyle(sinc.severity)"
          @click="openWarRoom(sinc.id)"
        >
          <div style="flex:1">
            <div style="display:flex;justify-content:space-between;align-items:center">
              <div style="display:flex;align-items:center;gap:.4rem">
                <span style="font-weight:600;font-size:.85rem">{{ sinc.title }}</span>
                <span style="font-size:.55rem;padding:.1rem .35rem;border-radius:3px;text-transform:uppercase;font-weight:600;background:var(--surface-2);color:var(--text-muted)">
                  {{ sinc.status }}
                </span>
              </div>
              <span style="font-size:.65rem;color:var(--text-muted)">
                {{ new Date((sinc.created_at || 0) * 1000).toLocaleString() }}
              </span>
            </div>
            <div style="display:flex;gap:.6rem;margin-top:.2rem;font-size:.65rem;color:var(--text-muted)">
              <span v-if="sinc.assigned_to">
                <i class="fas fa-user-tag"></i> {{ sinc.assigned_to }}
              </span>
              <span v-if="sinc.created_by">by {{ sinc.created_by }}</span>
              <span v-if="sinc.resolved_at" style="color:var(--success)">
                <i class="fas fa-check-circle"></i> Resolved
              </span>
            </div>
          </div>
        </div>
        <div v-if="spIncidents.length === 0" style="font-size:.75rem;color:var(--text-muted);padding:.3rem 0">
          No status incidents.
        </div>
      </div>

      <!-- Alert incidents (auto-generated) -->
      <div>
        <div style="font-weight:700;font-size:.85rem;margin-bottom:.5rem">
          <i class="fas fa-bell" style="margin-right:.3rem"></i>Alert Incidents
        </div>
        <div v-if="incidentLoading" class="empty-msg">Loading...</div>
        <template v-else-if="incidents.length > 0">
          <div
            v-for="inc in incidents"
            :key="inc.id"
            style="display:flex;gap:.6rem;margin-bottom:.8rem;padding:.5rem;border-left:3px solid;border-radius:0 4px 4px 0"
            :style="incidentSeverityBorderStyle(inc.severity)"
          >
            <div style="flex:1">
              <div style="display:flex;justify-content:space-between;align-items:center">
                <span style="font-weight:600;font-size:.85rem">{{ inc.title }}</span>
                <span style="font-size:.65rem;color:var(--text-muted)">
                  {{ new Date((inc.timestamp || 0) * 1000).toLocaleString() }}
                </span>
              </div>
              <div style="font-size:.7rem;color:var(--text-muted);margin-top:.2rem">
                {{ inc.source }}{{ inc.details ? ' \u2014 ' + inc.details : '' }}
              </div>
              <div v-if="!inc.resolved_at" style="margin-top:.3rem">
                <button class="btn btn-xs" @click="resolveIncident(inc.id)">
                  <i class="fas fa-check"></i> Resolve
                </button>
              </div>
              <div v-else style="font-size:.65rem;color:var(--success);margin-top:.2rem">
                Resolved {{ new Date(inc.resolved_at * 1000).toLocaleTimeString() }}
              </div>
            </div>
          </div>
        </template>
        <div v-else class="empty-msg">No incidents in the last 24 hours.</div>
      </div>
    </div>
  </div>
</template>
