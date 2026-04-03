<!-- Copyright (c) 2024-2026 Kevin Van Nieuwenhove. All rights reserved. -->
<!-- NOBA Command Center — Licensed under Apache 2.0. -->
<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import WorkflowNode from './WorkflowNode.vue'
import WorkflowNodePalette from './workflow/WorkflowNodePalette.vue'
import WorkflowNodeConfig from './workflow/WorkflowNodeConfig.vue'
import WorkflowRawEditor from './workflow/WorkflowRawEditor.vue'

const props = defineProps({
  modelValue: { type: Object, default: () => ({ nodes: [], edges: [], entry: '' }) },
})
const emit = defineEmits(['update:modelValue', 'close'])

// ── Local state ─────────────────────────────────────────────────────────────
const nodes = ref([]);         const edges = ref([]);         const entry = ref('')
const selectedNode = ref(null); const selectedEdge = ref(null); const connectingFrom = ref(null)
const nextId = ref(1);          const showRaw = ref(false);     const canvasRef = ref(null)
const isDirty = ref(false);     const edgeVersion = ref(0)
const panX = ref(0); const panY = ref(0); const isPanning = ref(false); const lastMousePos = ref({ x: 0, y: 0 })
const zoom = ref(1); const ctxMenu = ref({ show: false, x: 0, y: 0, nodeId: null })

// ── Lifecycle / modals ───────────────────────────────────────────────────────
function handleClose() { emit('close') }
defineExpose({ handleClose })

// ── Node defaults ────────────────────────────────────────────────────────────
const NODE_DEFAULTS = {
  action: { label: 'Action', config: { type: '', config: {} } }, condition: { label: 'Condition', expression: '' },
  approval_gate: { label: 'Approval Gate' }, parallel: { label: 'Parallel' },
  delay: { label: 'Delay', seconds: 30 }, notification: { label: 'Notification' },
}

// ── Init & emit ──────────────────────────────────────────────────────────────
function initFromModel(val) {
  const srcNodes = val?.nodes || []; const srcEdges = val?.edges || []
  nodes.value = srcNodes.map((n, i) => ({ x: 80 + (i % 4) * 220, y: 60 + Math.floor(i / 4) * 160, ...n }))
  edges.value = srcEdges.map(e => ({ ...e }))
  entry.value = val?.entry || (srcNodes[0]?.id ?? '')
  const maxId = srcNodes.reduce((m, n) => { const num = parseInt((n.id || '').replace(/\D/g, '') || '0', 10); return Math.max(m, isNaN(num) ? 0 : num) }, 0)
  nextId.value = maxId + 1; isDirty.value = false
}

let lastEmitted = ''
watch(() => props.modelValue, (v) => { const s = JSON.stringify(v); if (s === lastEmitted) return; initFromModel(v) }, { immediate: true, deep: true })

function emitGraph() {
  const payload = { nodes: nodes.value.map(n => ({ ...n })), edges: edges.value.map(e => ({ ...e })), entry: entry.value }
  lastEmitted = JSON.stringify(payload); isDirty.value = true; emit('update:modelValue', payload)
}

// ── Node operations ──────────────────────────────────────────────────────────
function addNode(type) {
  const id = `node_${nextId.value++}`; const col = nodes.value.length % 4; const row = Math.floor(nodes.value.length / 4)
  nodes.value.push({ id, type, x: 60 + col * 220, y: 60 + row * 170, ...NODE_DEFAULTS[type] })
  if (!entry.value) entry.value = id; selectedNode.value = id; emitGraph()
}
function deleteNode(id) {
  nodes.value = nodes.value.filter(n => n.id !== id); edges.value = edges.value.filter(e => e.from !== id && e.to !== id)
  if (entry.value === id) entry.value = nodes.value[0]?.id ?? ''; if (selectedNode.value === id) selectedNode.value = null
  connectingFrom.value = null; emitGraph()
}
function updateNode(updated) { const idx = nodes.value.findIndex(n => n.id === updated.id); if (idx !== -1) { nodes.value[idx] = { ...nodes.value[idx], ...updated }; emitGraph() } }
function onNodePosition({ id, x, y }) { const n = nodes.value.find(n => n.id === id); if (n) { n.x = x; n.y = y }; edgeVersion.value++ }
function selectNode(id) { selectedNode.value = id; selectedEdge.value = null }
function onCanvasClick() { selectedNode.value = null; selectedEdge.value = null; connectingFrom.value = null }
function setEntry(id) { entry.value = id; emitGraph() }
const selectedNodeObj = computed(() => nodes.value.find(n => n.id === selectedNode.value) || null)

// ── Edge logic ───────────────────────────────────────────────────────────────
function onStartConnect(info) { connectingFrom.value = info; selectedNode.value = null }
function onEndConnect(targetId) {
  if (!connectingFrom.value) return
  const { nodeId: fromId, port } = connectingFrom.value; if (fromId === targetId) { connectingFrom.value = null; return }
  if (!edges.value.some(e => e.from === fromId && e.port === port && e.to === targetId)) { edges.value.push({ from: fromId, port, to: targetId }); emitGraph() }
  connectingFrom.value = null
}
function selectEdge(edgeObj) { selectedEdge.value = edgeObj; selectedNode.value = null }
function deleteEdge(edgeObj) {
  edges.value = edges.value.filter(e => !(e.from === edgeObj.from && e.port === edgeObj.port && e.to === edgeObj.to))
  if (selectedEdge.value === edgeObj) selectedEdge.value = null; emitGraph()
}
function onKeyDown(e) { if ((e.key === 'Delete' || e.key === 'Backspace') && selectedEdge.value) deleteEdge(selectedEdge.value) }

// ── SVG edge geometry ────────────────────────────────────────────────────────
function getPortPos(nodeId, portId, isInput) {
  const canvasEl = canvasRef.value; if (!canvasEl) return null
  const nodeEl = canvasEl.querySelector(`[data-node-id="${nodeId}"]`); if (!nodeEl) return null
  const portEl = isInput ? nodeEl.querySelector('.wn-port-in') : (nodeEl.querySelector(`.wn-port-out[data-port="${portId}"]`) || nodeEl.querySelector('.wn-port-out'))
  if (!portEl) return null
  const canvasRect = canvasEl.getBoundingClientRect(); const portRect = portEl.getBoundingClientRect(); const z = zoom.value || 1
  return { x: (portRect.left + portRect.width / 2 - canvasRect.left + canvasEl.scrollLeft) / z, y: (portRect.top + portRect.height / 2 - canvasRect.top + canvasEl.scrollTop) / z }
}
const canvasW = computed(() => !nodes.value.length ? 800 : Math.max(800, Math.max(...nodes.value.map(n => n.x + 250))))
const canvasH = computed(() => !nodes.value.length ? 500 : Math.max(500, Math.max(...nodes.value.map(n => n.y + 180))))
const edgePaths = computed(() => {
  edgeVersion.value  // eslint-disable-line no-unused-expressions
  return edges.value.map(edge => {
    const src = getPortPos(edge.from, edge.port || 'default', false); const tgt = getPortPos(edge.to, null, true)
    if (!src || !tgt) {
      const fn = nodes.value.find(n => n.id === edge.from); const tn = nodes.value.find(n => n.id === edge.to); if (!fn || !tn) return null
      const x1 = fn.x + 87, y1 = fn.y + 80, x2 = tn.x + 87, y2 = tn.y; const cpOff = Math.max(30, Math.abs(y2 - y1) * 0.4)
      return { edge, d: `M ${x1} ${y1} C ${x1} ${y1 + cpOff}, ${x2} ${y2 - cpOff}, ${x2} ${y2}`, stroke: 'var(--text-muted)', mx: (x1 + x2) / 2, my: (y1 + y2) / 2 }
    }
    const { x: x1, y: y1 } = src; const { x: x2, y: y2 } = tgt; const dx = Math.abs(x2 - x1); const dy = y2 - y1
    const cpOff = dy > 30 ? Math.max(30, Math.min(80, Math.abs(dy) * 0.4)) : Math.max(30, dx * 0.15)
    let stroke = 'var(--text-muted)'
    if (edge.port === 'true' || edge.port === 'approved') stroke = 'var(--success)'
    if (edge.port === 'false' || edge.port === 'denied')  stroke = 'var(--danger)'
    return { edge, d: `M ${x1} ${y1} C ${x1} ${y1 + cpOff}, ${x2} ${y2 - cpOff}, ${x2} ${y2}`, stroke, mx: (x1 + x2) / 2, my: (y1 + y2) / 2 }
  }).filter(Boolean)
})

// ── Zoom / pan ───────────────────────────────────────────────────────────────
function zoomIn()    { zoom.value = Math.min(2, +(zoom.value + 0.15).toFixed(2)) }
function zoomOut()   { zoom.value = Math.max(0.3, +(zoom.value - 0.15).toFixed(2)) }
function zoomReset() { zoom.value = 1; panX.value = 0; panY.value = 0 }
function onWheel(e)  { e.deltaY < 0 ? zoomIn() : zoomOut() }
function onCanvasMouseDown(e) { if (e.target === canvasRef.value || e.target.classList.contains('wb-svg')) { isPanning.value = true; lastMousePos.value = { x: e.clientX, y: e.clientY } } }
function onGlobalMouseMove(e) { if (isPanning.value) { panX.value += e.clientX - lastMousePos.value.x; panY.value += e.clientY - lastMousePos.value.y; lastMousePos.value = { x: e.clientX, y: e.clientY } } }
function onGlobalMouseUp()    { isPanning.value = false }

// ── Context menu ─────────────────────────────────────────────────────────────
function onGlobalCtx(e) {
  const wrapper = e.target.closest('.wn-wrapper'); if (!wrapper) { ctxMenu.value.show = false; return }
  e.preventDefault(); const nodeId = wrapper.dataset.nodeId; if (!nodeId) return
  ctxMenu.value = { show: true, x: e.clientX, y: e.clientY, nodeId }
}
function setEntryFromCtx() { if (ctxMenu.value.nodeId) setEntry(ctxMenu.value.nodeId); ctxMenu.value.show = false }
function deleteFromCtx()   { if (ctxMenu.value.nodeId) deleteNode(ctxMenu.value.nodeId); ctxMenu.value.show = false }

// ── Raw JSON helpers ─────────────────────────────────────────────────────────
const rawSnapshot = computed(() => ({ nodes: nodes.value, edges: edges.value, entry: entry.value }))
function onRawApply(parsed) { initFromModel(parsed); emitGraph(); showRaw.value = false }

onMounted(() => { document.addEventListener('contextmenu', onGlobalCtx); window.addEventListener('mousemove', onGlobalMouseMove); window.addEventListener('mouseup', onGlobalMouseUp); nextTick(() => { edgeVersion.value++ }) })
let _edgeTimer = null
watch([nodes, edges], () => { clearTimeout(_edgeTimer); _edgeTimer = setTimeout(() => { edgeVersion.value++ }, 50) }, { deep: true })
onBeforeUnmount(() => { document.removeEventListener('contextmenu', onGlobalCtx); window.removeEventListener('mousemove', onGlobalMouseMove); window.removeEventListener('mouseup', onGlobalMouseUp) })
</script>

<template>
  <!-- Toolbar -->
  <div class="wb-toolbar">
    <WorkflowNodePalette @add-node="addNode" />
    <div class="wb-toolbar-right">
      <div v-if="!showRaw" class="wb-zoom-controls">
        <button class="wb-zoom-btn" @click="zoomOut" title="Zoom out"><i class="fas fa-search-minus"></i></button>
        <span class="wb-zoom-label" role="button" tabindex="0" @click="zoomReset" @keydown.enter="zoomReset" @keydown.space.prevent="zoomReset" title="Reset zoom/pan">{{ Math.round(zoom * 100) }}%</span>
        <button class="wb-zoom-btn" @click="zoomIn" title="Zoom in"><i class="fas fa-search-plus"></i></button>
        <button class="wb-zoom-btn" @click="zoomReset" title="Reset view"><i class="fas fa-compress-arrows-alt"></i></button>
      </div>
      <button v-if="!showRaw" class="wb-toggle-btn" @click="showRaw = true"><i class="fas fa-code"></i> JSON</button>
      <button v-else class="wb-toggle-btn wb-active" @click="showRaw = false"><i class="fas fa-project-diagram"></i> Visual</button>
    </div>
  </div>

  <!-- Connection hint -->
  <div v-if="connectingFrom" class="wb-connect-hint">
    <i class="fas fa-info-circle"></i> Click the input port (top dot) of the target node — or press Esc to cancel.
  </div>

  <!-- Canvas + Config panel -->
  <div v-if="!showRaw" class="wb-canvas-row">
    <div ref="canvasRef" class="wb-canvas" tabindex="0" :style="{ cursor: isPanning ? 'grabbing' : 'auto' }"
      @click="onCanvasClick" @keydown="onKeyDown" @keydown.escape="connectingFrom = null"
      @mousedown="onCanvasMouseDown" @mouseup="emitGraph" @wheel.prevent="onWheel">
      <div class="wb-zoom-layer" :style="{ transform: `translate(${panX}px, ${panY}px) scale(${zoom})`, transformOrigin: '0 0', width: canvasW + 'px', height: canvasH + 'px' }">
        <svg class="wb-svg" :width="canvasW" :height="canvasH">
          <defs>
            <marker id="wf-arr-n" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L0,6 L8,3 z" fill="var(--text-muted)" /></marker>
            <marker id="wf-arr-s" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L0,6 L8,3 z" fill="var(--success)" /></marker>
            <marker id="wf-arr-d" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L0,6 L8,3 z" fill="var(--danger)" /></marker>
          </defs>
          <g v-for="ep in edgePaths" :key="`${ep.edge.from}-${ep.edge.port}-${ep.edge.to}`">
            <path :d="ep.d" fill="none" stroke="transparent" stroke-width="14" style="cursor:pointer;pointer-events:stroke" @click.stop="selectEdge(ep.edge)" />
            <path :d="ep.d" fill="none" :stroke="ep.stroke" :stroke-width="selectedEdge === ep.edge ? 2.5 : 1.5" :stroke-dasharray="selectedEdge === ep.edge ? '6,3' : 'none'" :marker-end="ep.stroke === 'var(--success)' ? 'url(#wf-arr-s)' : ep.stroke === 'var(--danger)' ? 'url(#wf-arr-d)' : 'url(#wf-arr-n)'" opacity="0.85" style="pointer-events:none" />
            <g v-if="selectedEdge === ep.edge" style="cursor:pointer;pointer-events:all" @click.stop="deleteEdge(ep.edge)">
              <circle :cx="ep.mx" :cy="ep.my" r="9" fill="var(--danger)" opacity="0.9" />
              <text :x="ep.mx" :y="ep.my + 4" text-anchor="middle" font-size="12" fill="white" font-family="sans-serif" style="pointer-events:none">×</text>
            </g>
          </g>
        </svg>
        <WorkflowNode v-for="node in nodes" :key="node.id" :node="node" :selected="selectedNode === node.id" :is-entry="entry === node.id" :data-node-id="node.id" @select="selectNode" @start-connect="onStartConnect" @end-connect="onEndConnect" @delete="deleteNode" @update:position="onNodePosition" />
        <div v-if="nodes.length === 0" class="wb-empty"><i class="fas fa-project-diagram"></i><p>No nodes yet — use the toolbar above to add your first node.</p></div>
      </div>
    </div>
    <WorkflowNodeConfig v-if="selectedNodeObj" :node="selectedNodeObj" @update="updateNode" @delete="deleteNode" @close="selectedNode = null" />
  </div>

  <!-- Footer hint -->
  <div v-if="!showRaw && nodes.length > 0" class="wb-hint-footer">
    <i class="fas fa-star" style="color:var(--warning)"></i> Right-click a node to set it as entry.
    <template v-if="selectedEdge">&nbsp;|&nbsp; Edge selected — press <kbd>Delete</kbd> to remove.</template>
  </div>

  <!-- Raw JSON editor -->
  <WorkflowRawEditor v-if="showRaw" :model-value="rawSnapshot" @apply="onRawApply" @cancel="showRaw = false" />

  <!-- Context menu -->
  <Teleport to="body">
    <template v-if="ctxMenu.show">
      <div class="wb-context-menu" :style="{ left: ctxMenu.x + 'px', top: ctxMenu.y + 'px' }">
        <div class="wb-ctx-item" @click="setEntryFromCtx"><i class="fas fa-star"></i> Set as Entry</div>
        <div class="wb-ctx-item wb-ctx-danger" @click="deleteFromCtx"><i class="fas fa-trash"></i> Delete Node</div>
      </div>
      <div class="wb-ctx-backdrop" @click="ctxMenu.show = false"></div>
    </template>
  </Teleport>
</template>

<style scoped>
.wb-toolbar { display: flex; align-items: center; justify-content: space-between; gap: .5rem; padding: .4rem .5rem; background: var(--surface); border: 1px solid var(--border); border-radius: 6px 6px 0 0; flex-wrap: wrap; }
.wb-toolbar-right { display: flex; align-items: center; }
.wb-zoom-controls { display: flex; align-items: center; gap: 2px; margin-right: .5rem; }
.wb-zoom-btn { background: var(--surface-2); border: 1px solid var(--border); border-radius: 4px; color: var(--text-muted); padding: 2px 6px; font-size: .7rem; cursor: pointer; }
.wb-zoom-btn:hover { color: var(--text); border-color: var(--accent); }
.wb-zoom-label { font-size: .7rem; color: var(--text-muted); min-width: 36px; text-align: center; cursor: pointer; }
.wb-zoom-label:hover { color: var(--accent); }
.wb-toggle-btn { display: inline-flex; align-items: center; gap: .25rem; padding: .2rem .5rem; border-radius: 4px; border: 1px solid var(--border); background: var(--surface-2); color: var(--text-muted); font-size: .68rem; cursor: pointer; }
.wb-toggle-btn:hover, .wb-toggle-btn.wb-active { background: var(--accent-dim); color: var(--accent); border-color: var(--accent); }
.wb-connect-hint { background: var(--warning-dim); border: 1px solid var(--warning-border); border-top: none; color: var(--warning); font-size: .75rem; padding: .3rem .6rem; display: flex; align-items: center; gap: .4rem; }
.wb-canvas-row { display: flex; align-items: stretch; border: 1px solid var(--border); border-top: none; }
.wb-canvas { flex: 1; position: relative; background: var(--bg); background-image: radial-gradient(circle, var(--border) 1px, transparent 1px); background-size: 24px 24px; overflow: auto; min-height: 500px; max-height: 70vh; outline: none; }
.wb-zoom-layer { position: relative; transform-origin: 0 0; }
.wb-svg { position: absolute; top: 0; left: 0; pointer-events: none; overflow: visible; z-index: 1; }
.wb-empty { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: .75rem; color: var(--text-dim); pointer-events: none; z-index: 0; }
.wb-empty i { font-size: 2.5rem; } .wb-empty p { font-size: .85rem; }
.wb-hint-footer { font-size: .7rem; color: var(--text-muted); padding: .25rem .6rem; background: var(--surface); border: 1px solid var(--border); border-top: none; border-radius: 0 0 6px 6px; }
.wb-hint-footer kbd { background: var(--surface-2); border: 1px solid var(--border); border-radius: 3px; padding: 0 3px; font-size: .62rem; }
.wb-context-menu { position: fixed; z-index: 9999; background: var(--surface-2); border: 1px solid var(--border-hi); border-radius: 5px; padding: .25rem 0; min-width: 140px; box-shadow: 0 4px 16px rgba(0,0,0,.55); }
.wb-ctx-item { padding: .35rem .75rem; font-size: .8rem; cursor: pointer; display: flex; align-items: center; gap: .4rem; color: var(--text); transition: background .1s; }
.wb-ctx-item:hover { background: var(--surface); }
.wb-ctx-danger { color: var(--danger); }
.wb-ctx-backdrop { position: fixed; inset: 0; z-index: 9998; }
</style>
