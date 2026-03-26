<script setup>
import { ref, watch, nextTick, computed } from 'vue'
import { useModalsStore } from '../../stores/modals'
import { useApi } from '../../composables/useApi'
import { useNotificationsStore } from '../../stores/notifications'

const modals = useModalsStore()
const { post } = useApi()
const notif = useNotificationsStore()

const messages = ref([])
const input = ref('')
const sending = ref(false)
const messagesEl = ref(null)
const inputEl = ref(null)

const open = computed(() => modals.aiChat)

watch(open, async (val) => {
  if (val) {
    await nextTick()
    inputEl.value?.focus()
    scrollToBottom()
  }
})

function scrollToBottom() {
  nextTick(() => {
    if (messagesEl.value) messagesEl.value.scrollTop = messagesEl.value.scrollHeight
  })
}

function close() {
  modals.aiChat = false
}

function clearHistory() {
  messages.value = []
}

// Simple safe formatter: escape HTML then apply markdown-like patterns
function formatMessage(text) {
  const escaped = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
  // Code blocks first (multi-line); skip empty blocks the LLM sometimes emits
  const withBlocks = escaped.replace(/```[\w]*\n?([\s\S]*?)```/g, (_, code) =>
    code.trim() ? `<pre class="ai-code">${code}</pre>` : '')
  return withBlocks
    .replace(/`([^`\n]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\[ACTION:[^\]]+\]/g, '')  // strip raw action tags from display
    .replace(/\n/g, '<br>')
}

async function send() {
  const msg = input.value.trim()
  if (!msg || sending.value) return
  input.value = ''
  const history = messages.value.map(m => ({ role: m.role, content: m.content }))
  messages.value.push({ role: 'user', content: msg })
  scrollToBottom()
  sending.value = true
  try {
    const data = await post('/api/ai/chat', { message: msg, history })
    messages.value.push({ role: 'assistant', content: data.response, actions: data.actions || [] })
    scrollToBottom()
  } catch (e) {
    messages.value.pop()
    input.value = msg
    notif.addToast(e.message || 'AI request failed', 'error')
  } finally {
    sending.value = false
    nextTick(() => inputEl.value?.focus())
  }
}

function promptAction(action) {
  const desc = action.params
    ? `${action.cmd} ${action.params} on ${action.host}`
    : `${action.cmd} on ${action.host}`
  input.value = `Please confirm: run \`${desc}\`. What exactly will this do and is it safe?`
  inputEl.value?.focus()
}

function onKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}
</script>

<template>
  <!-- Backdrop -->
  <div
    v-if="open"
    class="sidebar-backdrop"
    style="z-index:59"
    @click="close"
  />

  <!-- Slide-in panel — always in DOM for smooth CSS transition -->
  <div class="ai-panel" :class="{ open }">
    <div class="ai-panel-header">
      <div style="display:flex;align-items:center;gap:.5rem">
        <i class="fas fa-robot" style="color:var(--accent)"></i>
        <span style="font-weight:600;font-size:.9rem">AI Ops Assistant</span>
        <i
          v-if="sending"
          class="fas fa-circle-notch fa-spin"
          style="font-size:.7rem;color:var(--text-muted)"
        ></i>
      </div>
      <div style="display:flex;gap:.25rem">
        <button
          class="icon-btn"
          title="Clear conversation"
          style="font-size:.8rem"
          @click="clearHistory"
        >
          <i class="fas fa-trash-alt"></i>
        </button>
        <button class="icon-btn" title="Close" @click="close">
          <i class="fas fa-times"></i>
        </button>
      </div>
    </div>

    <div ref="messagesEl" class="ai-messages">
      <!-- Empty state -->
      <div v-if="messages.length === 0" class="ai-empty">
        <i class="fas fa-robot" style="font-size:2.5rem;margin-bottom:.75rem;opacity:.3"></i>
        <div style="font-weight:600;margin-bottom:.4rem">AI Ops Assistant</div>
        <div style="font-size:.8rem;opacity:.7">
          Ask about your infrastructure, analyze logs, or get help troubleshooting incidents.
        </div>
        <div style="font-size:.75rem;margin-top:1rem;opacity:.5">
          Powered by Ollama / Anthropic / OpenAI
        </div>
      </div>

      <!-- Message list -->
      <div
        v-for="(msg, i) in messages"
        :key="i"
        :class="msg.role === 'user' ? 'ai-message-user' : 'ai-message-assistant'"
      >
        <div class="ai-msg-content" v-html="formatMessage(msg.content)" />
        <div v-if="msg.actions && msg.actions.length" class="ai-actions">
          <button
            v-for="(act, j) in msg.actions"
            :key="j"
            class="ai-action-btn"
            :title="`${act.cmd} on ${act.host}`"
            @click="promptAction(act)"
          >
            <i class="fas fa-terminal"></i>
            {{ act.cmd }} @ {{ act.host }}
          </button>
        </div>
      </div>

      <!-- Thinking indicator -->
      <div v-if="sending" class="ai-message-assistant">
        <i class="fas fa-circle-notch fa-spin" style="color:var(--text-muted);font-size:.8rem"></i>
        <span style="color:var(--text-muted);font-size:.8rem;margin-left:.4rem">Thinking…</span>
      </div>
    </div>

    <!-- Input area -->
    <div class="ai-input-area" style="padding:.6rem .75rem">
      <div style="display:flex;gap:.4rem;align-items:flex-end">
        <textarea
          ref="inputEl"
          v-model="input"
          class="ai-input"
          placeholder="Ask the AI Ops Assistant…"
          rows="3"
          @keydown="onKeydown"
        />
        <button
          class="btn btn-primary"
          style="height:52px;padding:0 .85rem;flex-shrink:0;width:auto"
          :disabled="!input.trim() || sending"
          @click="send"
        >
          <i class="fas fa-paper-plane"></i>
        </button>
      </div>
      <div style="font-size:.65rem;color:var(--text-muted);margin-top:.3rem">
        Enter to send · Shift+Enter for newline
      </div>
    </div>
  </div>
</template>
