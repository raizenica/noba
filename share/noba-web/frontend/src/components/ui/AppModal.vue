<script setup>
defineProps({
  show: Boolean,
  title: { type: String, default: '' },
  width: { type: String, default: '540px' },
})
const emit = defineEmits(['close'])
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="show" class="modal-overlay" @click.self="emit('close')" @keydown.escape="emit('close')">
        <div class="modal-box" :style="{ maxWidth: width }">
          <div v-if="title" class="modal-title">
            {{ title }}
            <button class="modal-close" @click="emit('close')" aria-label="Close">&times;</button>
          </div>
          <slot />
          <div v-if="$slots.footer" class="modal-footer">
            <slot name="footer" />
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
