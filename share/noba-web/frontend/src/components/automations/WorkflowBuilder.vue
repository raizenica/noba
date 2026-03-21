<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount, onUpdated, nextTick } from 'vue'
import WorkflowNode from './WorkflowNode.vue'

const props = defineProps({
  modelValue: { type: Object, default: () => ({ nodes: [], edges: [], entry: '' }) },
})
const emit = defineEmits(['update:modelValue'])

// ── Local state ────────────────────────────────────────────────────────────
const nodes         = ref([])
const edges         = ref([])
const entry         = ref('')
const selectedNode  = ref(null)
const selectedEdge  = ref(null)
const connectingFrom = ref(null)   // {nodeId, port}
const nextId        = ref(1)
const showRaw       = ref(false)
const rawJson       = ref('')
const rawError      = ref('')
const canvasRef     = ref(null)

// Context menu
const ctxMenu = ref({ show: false, x: 0, y: 0, nodeId: null })

// ── Initialise from modelValue ─────────────────────────────────────────────
function initFromModel(val) {
  const srcNodes = val?.nodes || []
  const srcEdges = val?.edges || []
  nodes.value = srcNodes.map((n, i) => ({
    x: 80 + (i % 4) * 220,
    y: 60 + Math.floor(i / 4) * 160,
    ...n,
  }))
  edges.value = srcEdges.map(e => ({ ...e }))
  entry.value = val?.entry || (srcNodes[0]?.id ?? '')
  const maxId = srcNodes.reduce((m, n) => {
    const num = parseInt((n.id || '').replace(/\D/g, '') || '0', 10)
    return Math.max(m, isNaN(num) ? 0 : num)
  }, 0)
  nextId.value = maxId + 1
}

// Only initialise once when the modal opens; don't re-init on every emitted
// update (that would fight the user mid-edit). Watch with { once: false } but
// guard against re-entry by comparing serialised identity.
let lastEmitted = ''
watch(
  () => props.modelValue,
  (v) => {
    const serial = JSON.stringify(v)
    if (serial === lastEmitted) return  // we just emitted this — skip
    initFromModel(v)
  },
  { immediate: true, deep: true },
)

// ── Emit serialised graph ──────────────────────────────────────────────────
function emitGraph() {
  const payload = {
    nodes: nodes.value.map(n => ({ ...n })),
    edges: edges.value.map(e => ({ ...e })),
    entry: entry.value,
  }
  lastEmitted = JSON.stringify(payload)
  emit('update:modelValue', payload)
}

// ── Node operations ────────────────────────────────────────────────────────
const NODE_DEFAULTS = {
  action:        { label: 'Action' },
  condition:     { label: 'Condition', expression: '' },
  approval_gate: { label: 'Approval Gate' },
  parallel:      { label: 'Parallel' },
  delay:         { label: 'Delay', seconds: 30 },
  notification:  { label: 'Notification' },
}

function addNode(type) {
  const id = `node_${nextId.value++}`
  const col = nodes.value.length % 4
  const row = Math.floor(nodes.value.length / 4)
  const n = {
    id,
    type,
    x: 60 + col * 220,
    y: 60 + row * 170,
    ...NODE_DEFAULTS[type],
  }
  nodes.value.push(n)
  if (!entry.value) entry.value = id
  selectedNode.value = id
  emitGraph()
}

function deleteNode(id) {
  nodes.value = nodes.value.filter(n => n.id !== id)
  edges.value = edges.value.filter(e => e.from !== id && e.to !== id)
  if (entry.value === id) entry.value = nodes.value[0]?.id ?? ''
  if (selectedNode.value === id) selectedNode.value = null
  connectingFrom.value = null
  emitGraph()
}

function onNodePosition({ id, x, y }) {
  const n = nodes.value.find(n => n.id === id)
  if (n) { n.x = x; n.y = y }
  edgeVersion.value++  // recalculate edges on drag
}

function onNodeMouseUp() {
  emitGraph()
}

function selectNode(id) {
  selectedNode.value = id
  selectedEdge.value = null
}

function onCanvasClick() {
  selectedNode.value = null
  selectedEdge.value = null
  connectingFrom.value = null
}

function setEntry(id) {
  entry.value = id
  emitGraph()
}

// ── Edge / connection logic ────────────────────────────────────────────────
function onStartConnect(info) {
  connectingFrom.value = info
  selectedNode.value = null
}

function onEndConnect(targetId) {
  if (!connectingFrom.value) return
  const { nodeId: fromId, port } = connectingFrom.value
  if (fromId === targetId) { connectingFrom.value = null; return }
  const exists = edges.value.some(
    e => e.from === fromId && e.port === port && e.to === targetId,
  )
  if (!exists) {
    edges.value.push({ from: fromId, port, to: targetId })
    emitGraph()
  }
  connectingFrom.value = null
}

function selectEdge(edgeObj) {
  selectedEdge.value = edgeObj
  selectedNode.value = null
}

function deleteEdge(edgeObj) {
  edges.value = edges.value.filter(
    e => !(e.from === edgeObj.from && e.port === edgeObj.port && e.to === edgeObj.to),
  )
  if (selectedEdge.value === edgeObj) selectedEdge.value = null
  emitGraph()
}

function onKeyDown(e) {
  if ((e.key === 'Delete' || e.key === 'Backspace') && selectedEdge.value) {
    deleteEdge(selectedEdge.value)
  }
}

// ── SVG edge geometry ──────────────────────────────────────────────────────
// Use DOM-based port positions for accurate edge drawing
const edgeVersion = ref(0)  // bump to trigger recalc after render

function getPortPos(nodeId, portId, isInput) {
  const canvasEl = canvasRef.value
  if (!canvasEl) return null
  const nodeEl = canvasEl.querySelector(`[data-node-id="${nodeId}"]`)
  if (!nodeEl) return null

  let portEl
  if (isInput) {
    portEl = nodeEl.querySelector('.wn-port-in')
  } else {
    portEl = nodeEl.querySelector(`.wn-port-out[data-port="${portId}"]`)
      || nodeEl.querySelector('.wn-port-out')
  }
  if (!portEl) return null

  const canvasRect = canvasEl.getBoundingClientRect()
  const portRect = portEl.getBoundingClientRect()
  const z = zoom.value || 1
  return {
    x: (portRect.left + portRect.width / 2 - canvasRect.left + canvasEl.scrollLeft) / z,
    y: (portRect.top + portRect.height / 2 - canvasRect.top + canvasEl.scrollTop) / z,
  }
}

const edgePaths = computed(() => {
  // eslint-disable-next-line no-unused-expressions
  edgeVersion.value  // depend on version to recalc after DOM updates

  return edges.value.map(edge => {
    const src = getPortPos(edge.from, edge.port || 'default', false)
    const tgt = getPortPos(edge.to, null, true)
    if (!src || !tgt) {
      // Fallback: use node position estimates
      const fromNode = nodes.value.find(n => n.id === edge.from)
      const toNode   = nodes.value.find(n => n.id === edge.to)
      if (!fromNode || !toNode) return null
      const x1 = fromNode.x + 87, y1 = fromNode.y + 80
      const x2 = toNode.x + 87,   y2 = toNode.y
      const cpOff = Math.max(30, Math.abs(y2 - y1) * 0.4)
      return {
        edge,
        d: `M ${x1} ${y1} C ${x1} ${y1 + cpOff}, ${x2} ${y2 - cpOff}, ${x2} ${y2}`,
        stroke: 'var(--text-muted)',
        mx: (x1 + x2) / 2, my: (y1 + y2) / 2,
      }
    }

    const { x: x1, y: y1 } = src
    const { x: x2, y: y2 } = tgt
    const dx = Math.abs(x2 - x1)
    const dy = y2 - y1
    const cpOff = dy > 30
      ? Math.max(30, Math.min(80, Math.abs(dy) * 0.4))
      : Math.max(30, dx * 0.15)
    const d = `M ${x1} ${y1} C ${x1} ${y1 + cpOff}, ${x2} ${y2 - cpOff}, ${x2} ${y2}`

    let stroke = 'var(--text-muted)'
    if (edge.port === 'true' || edge.port === 'approved')  stroke = 'var(--success)'
    if (edge.port === 'false' || edge.port === 'denied')   stroke = 'var(--danger)'

    return { edge, d, stroke, mx: (x1 + x2) / 2, my: (y1 + y2) / 2 }
  }).filter(Boolean)
})

const canvasW = computed(() => {
  if (!nodes.value.length) return 800
  return Math.max(800, Math.max(...nodes.value.map(n => n.x + 250)))
})
const canvasH = computed(() => {
  if (!nodes.value.length) return 500
  return Math.max(500, Math.max(...nodes.value.map(n => n.y + 180)))
})

// ── Zoom ───────────────────────────────────────────────────────────────────
const zoom = ref(1)
function zoomIn()  { zoom.value = Math.min(2, +(zoom.value + 0.15).toFixed(2)) }
function zoomOut() { zoom.value = Math.max(0.3, +(zoom.value - 0.15).toFixed(2)) }
function zoomReset() { zoom.value = 1 }
function onWheel(e) { e.deltaY < 0 ? zoomIn() : zoomOut() }

// ── Raw JSON import/export ─────────────────────────────────────────────────
function switchToRaw() {
  rawJson.value = JSON.stringify({ nodes: nodes.value, edges: edges.value, entry: entry.value }, null, 2)
  rawError.value = ''
  showRaw.value = true
}

function applyRaw() {
  try {
    const parsed = JSON.parse(rawJson.value)
    initFromModel(parsed)
    emitGraph()
    rawError.value = ''
    showRaw.value = false
  } catch (e) {
    rawError.value = 'Invalid JSON: ' + e.message
  }
}

// ── Context menu (right-click node → set entry / delete) ─────────────────
function onGlobalCtx(e) {
  const wrapper = e.target.closest('.wn-wrapper')
  if (!wrapper) {
    ctxMenu.value.show = false
    return
  }
  e.preventDefault()
  // Resolve node id from the data attribute we stamp on the wrapper
  const nodeId = wrapper.dataset.nodeId
  if (!nodeId) return
  ctxMenu.value = { show: true, x: e.clientX, y: e.clientY, nodeId }
}

function setEntryFromCtx() {
  if (ctxMenu.value.nodeId) setEntry(ctxMenu.value.nodeId)
  ctxMenu.value.show = false
}

function deleteFromCtx() {
  if (ctxMenu.value.nodeId) deleteNode(ctxMenu.value.nodeId)
  ctxMenu.value.show = false
}

onMounted(() => {
  document.addEventListener('contextmenu', onGlobalCtx)
  // Bump edgeVersion after initial render so DOM-based port positions are available
  nextTick(() => { edgeVersion.value++ })
})

// Re-measure port positions after nodes change (debounced to avoid infinite loops)
let _edgeTimer = null
watch([nodes, edges], () => {
  clearTimeout(_edgeTimer)
  _edgeTimer = setTimeout(() => { edgeVersion.value++ }, 50)
}, { deep: true })
onBeforeUnmount(() => { document.removeEventListener('contextmenu', onGlobalCtx) })
</script>

<template>
  <!-- ── Toolbar ── -->
  <div class="wb-toolbar">
    <div class="wb-toolbar-left">
      <span class="wb-toolbar-label">Add:</span>
      <button class="wb-add-btn wb-action"       @click="addNode('action')">
        <i class="fas fa-play"></i> Action
      </button>
      <button class="wb-add-btn wb-condition"    @click="addNode('condition')">
        <i class="fas fa-code-branch"></i> Condition
      </button>
      <button class="wb-add-btn wb-approval"     @click="addNode('approval_gate')">
        <i class="fas fa-lock"></i> Approval
      </button>
      <button class="wb-add-btn wb-parallel"     @click="addNode('parallel')">
        <i class="fas fa-code-branch wb-rotated"></i> Parallel
      </button>
      <button class="wb-add-btn wb-delay"        @click="addNode('delay')">
        <i class="fas fa-clock"></i> Delay
      </button>
      <button class="wb-add-btn wb-notify"       @click="addNode('notification')">
        <i class="fas fa-bell"></i> Notify
      </button>
    </div>
    <div class="wb-toolbar-right">
      <div v-if="!showRaw" class="wb-zoom-controls">
        <button class="wb-zoom-btn" @click="zoomOut" title="Zoom out"><i class="fas fa-search-minus"></i></button>
        <span class="wb-zoom-label" @click="zoomReset" title="Reset zoom">{{ Math.round(zoom * 100) }}%</span>
        <button class="wb-zoom-btn" @click="zoomIn" title="Zoom in"><i class="fas fa-search-plus"></i></button>
      </div>
      <button v-if="!showRaw" class="wb-toggle-btn" @click="switchToRaw">
        <i class="fas fa-code"></i> JSON
      </button>
      <button v-else class="wb-toggle-btn wb-active" @click="showRaw = false">
        <i class="fas fa-project-diagram"></i> Visual
      </button>
    </div>
  </div>

  <!-- Connection hint bar -->
  <div v-if="connectingFrom" class="wb-connect-hint">
    <i class="fas fa-info-circle"></i>
    Click the input port (top dot) of the target node — or press Esc to cancel.
  </div>

  <!-- ── Visual canvas ── -->
  <div
    v-if="!showRaw"
    ref="canvasRef"
    class="wb-canvas"
    :style="{ minHeight: '500px' }"
    tabindex="0"
    @click="onCanvasClick"
    @keydown="onKeyDown"
    @keydown.escape="connectingFrom = null"
    @mouseup="onNodeMouseUp"
    @wheel.prevent="onWheel"
  >
    <!-- Zoom wrapper -->
    <div
      class="wb-zoom-layer"
      :style="{ transform: `scale(${zoom})`, transformOrigin: '0 0', width: canvasW + 'px', height: canvasH + 'px' }"
    >
    <!-- SVG edge layer -->
    <svg class="wb-svg" :width="canvasW" :height="canvasH">
      <defs>
        <marker id="wf-arr-n" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
          <path d="M0,0 L0,6 L8,3 z" fill="var(--text-muted)" />
        </marker>
        <marker id="wf-arr-s" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
          <path d="M0,0 L0,6 L8,3 z" fill="var(--success)" />
        </marker>
        <marker id="wf-arr-d" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
          <path d="M0,0 L0,6 L8,3 z" fill="var(--danger)" />
        </marker>
      </defs>

      <g
        v-for="ep in edgePaths"
        :key="`${ep.edge.from}-${ep.edge.port}-${ep.edge.to}`"
      >
        <!-- Wide invisible hit area -->
        <path
          :d="ep.d"
          fill="none"
          stroke="transparent"
          stroke-width="14"
          style="cursor:pointer;pointer-events:stroke"
          @click.stop="selectEdge(ep.edge)"
        />
        <!-- Visible edge path -->
        <path
          :d="ep.d"
          fill="none"
          :stroke="ep.stroke"
          :stroke-width="selectedEdge === ep.edge ? 2.5 : 1.5"
          :stroke-dasharray="selectedEdge === ep.edge ? '6,3' : 'none'"
          :marker-end="
            ep.stroke === 'var(--success)' ? 'url(#wf-arr-s)'
            : ep.stroke === 'var(--danger)' ? 'url(#wf-arr-d)'
            : 'url(#wf-arr-n)'"
          opacity="0.85"
          style="pointer-events:none"
        />
        <!-- Delete button at midpoint when edge selected -->
        <g
          v-if="selectedEdge === ep.edge"
          style="cursor:pointer;pointer-events:all"
          @click.stop="deleteEdge(ep.edge)"
        >
          <circle :cx="ep.mx" :cy="ep.my" r="9" fill="var(--danger)" opacity="0.9" />
          <text
            :x="ep.mx" :y="ep.my + 4"
            text-anchor="middle"
            font-size="12"
            fill="white"
            font-family="sans-serif"
            style="pointer-events:none"
          >×</text>
        </g>
      </g>
    </svg>

    <!-- Node components -->
    <WorkflowNode
      v-for="node in nodes"
      :key="node.id"
      :node="node"
      :selected="selectedNode === node.id"
      :is-entry="entry === node.id"
      :data-node-id="node.id"
      @select="selectNode"
      @start-connect="onStartConnect"
      @end-connect="onEndConnect"
      @delete="deleteNode"
      @update:position="onNodePosition"
    />

    <!-- Empty state -->
    <div v-if="nodes.length === 0" class="wb-empty">
      <i class="fas fa-project-diagram"></i>
      <p>No nodes yet — use the toolbar above to add your first node.</p>
    </div>
    </div><!-- /wb-zoom-layer -->
  </div>

  <!-- Footer hint -->
  <div v-if="!showRaw && nodes.length > 0" class="wb-hint-footer">
    <i class="fas fa-star" style="color:var(--warning)"></i>
    Right-click a node to set it as entry.
    <template v-if="selectedEdge">
      &nbsp;|&nbsp; Edge selected — press <kbd>Delete</kbd> to remove.
    </template>
  </div>

  <!-- ── Raw JSON view ── -->
  <div v-if="showRaw" class="wb-raw">
    <div class="wb-raw-label">Edit the graph JSON directly, then click Apply.</div>
    <textarea
      v-model="rawJson"
      class="wb-raw-textarea"
      spellcheck="false"
    ></textarea>
    <div v-if="rawError" class="wb-raw-error">{{ rawError }}</div>
    <div class="wb-raw-actions">
      <button class="btn" @click="showRaw = false">Cancel</button>
      <button class="btn btn-primary" @click="applyRaw">
        <i class="fas fa-check"></i> Apply
      </button>
    </div>
  </div>

  <!-- Context menu (Teleport so it's not clipped by overflow:auto on canvas) -->
  <Teleport to="body">
    <template v-if="ctxMenu.show">
      <div
        class="wb-context-menu"
        :style="{ left: ctxMenu.x + 'px', top: ctxMenu.y + 'px' }"
      >
        <div class="wb-ctx-item" @click="setEntryFromCtx">
          <i class="fas fa-star"></i> Set as Entry
        </div>
        <div class="wb-ctx-item wb-ctx-danger" @click="deleteFromCtx">
          <i class="fas fa-trash"></i> Delete Node
        </div>
      </div>
      <div class="wb-ctx-backdrop" @click="ctxMenu.show = false"></div>
    </template>
  </Teleport>
</template>

<style scoped>
/* ── Toolbar ── */
.wb-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: .5rem;
  padding: .4rem .5rem;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px 6px 0 0;
  flex-wrap: wrap;
}
.wb-toolbar-left  { display: flex; align-items: center; gap: .3rem; flex-wrap: wrap; }
.wb-toolbar-right { display: flex; align-items: center; }
.wb-toolbar-label {
  font-size: .62rem;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: .06em;
  white-space: nowrap;
  margin-right: .1rem;
}

.wb-add-btn {
  display: inline-flex;
  align-items: center;
  gap: .25rem;
  padding: .2rem .45rem;
  border-radius: 4px;
  border: 1px solid var(--border);
  background: var(--surface-2);
  color: var(--text-muted);
  font-size: .68rem;
  cursor: pointer;
  transition: background .12s, border-color .12s, color .12s;
  white-space: nowrap;
}
.wb-add-btn:hover { background: var(--surface); border-color: var(--border-hi); color: var(--text); }

.wb-action       { border-color: #3b82f6; color: #3b82f6; }
.wb-condition    { border-color: #f59e0b; color: #f59e0b; }
.wb-approval     { border-color: #f97316; color: #f97316; }
.wb-parallel     { border-color: #a855f7; color: #a855f7; }
.wb-delay        { border-color: #6b7280; color: #9ca3af; }
.wb-notify       { border-color: #22c55e; color: #22c55e; }
.wb-rotated { display: inline-block; transform: rotate(90deg); }

.wb-toggle-btn {
  display: inline-flex;
  align-items: center;
  gap: .25rem;
  padding: .2rem .5rem;
  border-radius: 4px;
  border: 1px solid var(--border);
  background: var(--surface-2);
  color: var(--text-muted);
  font-size: .68rem;
  cursor: pointer;
  transition: background .12s, color .12s;
}
.wb-toggle-btn:hover, .wb-toggle-btn.wb-active {
  background: var(--accent-dim);
  color: var(--accent);
  border-color: var(--accent);
}

/* ── Connection hint ── */
.wb-connect-hint {
  background: var(--warning-dim);
  border: 1px solid var(--warning-border);
  border-top: none;
  color: var(--warning);
  font-size: .75rem;
  padding: .3rem .6rem;
  display: flex;
  align-items: center;
  gap: .4rem;
}

/* ── Canvas ── */
.wb-canvas {
  position: relative;
  background: var(--bg);
  background-image: radial-gradient(circle, var(--border) 1px, transparent 1px);
  background-size: 24px 24px;
  border: 1px solid var(--border);
  border-top: none;
  overflow: auto;
  min-height: 500px;
  max-height: 70vh;
  outline: none;
}
.wb-zoom-layer {
  position: relative;
  transform-origin: 0 0;
}

/* ── Zoom controls ── */
.wb-zoom-controls {
  display: flex;
  align-items: center;
  gap: 2px;
  margin-right: .5rem;
}
.wb-zoom-btn {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text-muted);
  padding: 2px 6px;
  font-size: .7rem;
  cursor: pointer;
}
.wb-zoom-btn:hover { color: var(--text); border-color: var(--accent); }
.wb-zoom-label {
  font-size: .7rem;
  color: var(--text-muted);
  min-width: 36px;
  text-align: center;
  cursor: pointer;
}
.wb-zoom-label:hover { color: var(--accent); }

/* ── SVG ── */
.wb-svg {
  position: absolute;
  top: 0;
  left: 0;
  pointer-events: none;
  overflow: visible;
  z-index: 1;
}

/* ── Empty state ── */
.wb-empty {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: .75rem;
  color: var(--text-dim);
  pointer-events: none;
  z-index: 0;
}
.wb-empty i { font-size: 2.5rem; }
.wb-empty p { font-size: .85rem; }

/* ── Footer hint ── */
.wb-hint-footer {
  font-size: .7rem;
  color: var(--text-muted);
  padding: .25rem .6rem;
  background: var(--surface);
  border: 1px solid var(--border);
  border-top: none;
  border-radius: 0 0 6px 6px;
}
.wb-hint-footer kbd {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 0 3px;
  font-size: .62rem;
}

/* ── Raw JSON ── */
.wb-raw {
  border: 1px solid var(--border);
  border-top: none;
  border-radius: 0 0 6px 6px;
  padding: .75rem;
  background: var(--surface);
  display: flex;
  flex-direction: column;
  gap: .5rem;
}
.wb-raw-label { font-size: .75rem; color: var(--text-muted); }
.wb-raw-textarea {
  width: 100%;
  min-height: 240px;
  resize: vertical;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text);
  font-family: var(--font-data);
  font-size: .75rem;
  padding: .5rem;
  box-sizing: border-box;
}
.wb-raw-textarea:focus { outline: none; border-color: var(--accent); }
.wb-raw-error { color: var(--danger); font-size: .75rem; }
.wb-raw-actions { display: flex; justify-content: flex-end; gap: .5rem; }

/* ── Context menu ── */
.wb-context-menu {
  position: fixed;
  z-index: 9999;
  background: var(--surface-2);
  border: 1px solid var(--border-hi);
  border-radius: 5px;
  padding: .25rem 0;
  min-width: 140px;
  box-shadow: 0 4px 16px rgba(0,0,0,.55);
}
.wb-ctx-item {
  padding: .35rem .75rem;
  font-size: .8rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: .4rem;
  color: var(--text);
  transition: background .1s;
}
.wb-ctx-item:hover { background: var(--surface); }
.wb-ctx-danger { color: var(--danger); }
.wb-ctx-backdrop {
  position: fixed;
  inset: 0;
  z-index: 9998;
}
</style>
