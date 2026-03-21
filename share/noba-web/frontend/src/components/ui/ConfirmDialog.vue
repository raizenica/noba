<script setup>
import { ref } from 'vue'
import AppModal from './AppModal.vue'

const show = ref(false)
const message = ref('')
let _resolve = null

function confirm(msg) {
  message.value = msg
  show.value = true
  return new Promise((resolve) => { _resolve = resolve })
}

function handleYes() { show.value = false; if (_resolve) _resolve(true) }
function handleNo() { show.value = false; if (_resolve) _resolve(false) }

defineExpose({ confirm })
</script>

<template>
  <AppModal :show="show" title="Confirm" @close="handleNo">
    <p style="padding:1rem">{{ message }}</p>
    <template #footer>
      <button class="btn" @click="handleNo">Cancel</button>
      <button class="btn btn-danger" @click="handleYes">Confirm</button>
    </template>
  </AppModal>
</template>
