<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  columns: { type: Array, required: true },
  rows: { type: Array, default: () => [] },
  pageSize: { type: Number, default: 50 },
})

const sortField = ref('')
const sortDir = ref('asc')
const page = ref(1)

function toggleSort(key) {
  if (sortField.value === key) { sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc' }
  else { sortField.value = key; sortDir.value = 'asc' }
}

const sorted = computed(() => {
  if (!sortField.value) return props.rows
  return [...props.rows].sort((a, b) => {
    const va = a[sortField.value], vb = b[sortField.value]
    const cmp = va < vb ? -1 : va > vb ? 1 : 0
    return sortDir.value === 'asc' ? cmp : -cmp
  })
})

const paged = computed(() => {
  const start = (page.value - 1) * props.pageSize
  return sorted.value.slice(start, start + props.pageSize)
})

const totalPages = computed(() => Math.ceil(props.rows.length / props.pageSize) || 1)
</script>

<template>
  <div>
    <table class="audit-table" style="width:100%">
      <thead>
        <tr>
          <th v-for="col in columns" :key="col.key"
              @click="col.sortable !== false && toggleSort(col.key)"
              :style="col.sortable !== false ? 'cursor:pointer' : ''">
            {{ col.label }}
            <span v-if="sortField === col.key">{{ sortDir === 'asc' ? '\u25B2' : '\u25BC' }}</span>
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(row, i) in paged" :key="i">
          <td v-for="col in columns" :key="col.key">
            <slot :name="'cell-' + col.key" :row="row" :value="row[col.key]">
              {{ row[col.key] }}
            </slot>
          </td>
        </tr>
        <tr v-if="paged.length === 0">
          <td :colspan="columns.length" style="text-align:center;opacity:.4;padding:1rem">No data</td>
        </tr>
      </tbody>
    </table>
    <div v-if="totalPages > 1" style="display:flex;gap:.5rem;margin-top:.5rem;align-items:center">
      <button class="btn btn-sm" :disabled="page <= 1" @click="page--">Prev</button>
      <span style="font-size:.85rem;opacity:.6">{{ page }} / {{ totalPages }}</span>
      <button class="btn btn-sm" :disabled="page >= totalPages" @click="page++">Next</button>
    </div>
  </div>
</template>
