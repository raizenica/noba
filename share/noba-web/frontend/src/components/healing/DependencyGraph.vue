<script setup>
import { computed, ref, onMounted } from 'vue'
import { useHealingStore } from '../../stores/healing'

const store = useHealingStore()
const svgEl = ref(null)
const selected = ref(null)

const nodeWidth = 150
const nodeHeight = 44
const hGap = 30
const vGap = 80

// Type → layer index (lower = higher on canvas)
const LAYER_ORDER = { external: 0, infrastructure: 1, service: 2, agent: 3 }

const nodes = computed(() => store.dependencies)

const layoutNodes = computed(() => {
  const layers = {}
  for (const node of nodes.value) {
    const layer = LAYER_ORDER[node.type] ?? 2
    if (!layers[layer]) layers[layer] = []
    layers[layer].push(node)
  }

  const result = []
  const sortedLayerKeys = Object.keys(layers).map(Number).sort((a, b) => a - b)

  // Find the widest layer to center narrower layers
  let maxLayerWidth = 0
  for (const key of sortedLayerKeys) {
    const w = layers[key].length * (nodeWidth + hGap) - hGap
    if (w > maxLayerWidth) maxLayerWidth = w
  }

  for (let li = 0; li < sortedLayerKeys.length; li++) {
    const key = sortedLayerKeys[li]
    const layerNodes = layers[key]
    const layerWidth = layerNodes.length * (nodeWidth + hGap) - hGap
    const xOffset = (maxLayerWidth - layerWidth) / 2

    for (let ni = 0; ni < layerNodes.length; ni++) {
      result.push({
        ...layerNodes[ni],
        x: xOffset + ni * (nodeWidth + hGap),
        y: li * (nodeHeight + vGap),
      })
    }
  }
  return result
})

const edges = computed(() => {
  const nodeMap = {}
  for (const n of layoutNodes.value) nodeMap[n.target] = n

  const result = []
  for (const node of layoutNodes.value) {
    if (!node.depends_on?.length) continue
    for (const dep of node.depends_on) {
      const parent = nodeMap[dep]
      if (!parent) continue
      result.push({
        x1: node.x + nodeWidth / 2,
        y1: node.y,
        x2: parent.x + nodeWidth / 2,
        y2: parent.y + nodeHeight,
      })
    }
  }
  return result
})

const viewBox = computed(() => {
  if (!layoutNodes.value.length) return '0 0 600 300'
  let maxX = 0, maxY = 0
  for (const n of layoutNodes.value) {
    if (n.x + nodeWidth > maxX) maxX = n.x + nodeWidth
    if (n.y + nodeHeight > maxY) maxY = n.y + nodeHeight
  }
  const padX = hGap
  const padY = vGap
  return `${-padX} ${-padY / 2} ${maxX + padX * 2} ${maxY + padY}`
})

// Read CSS variable from document root
function cssVar(name) {
  if (typeof window === 'undefined') return '#888'
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

const arrowColor = computed(() => cssVar('--text-muted'))
const textColor = computed(() => cssVar('--text'))
const mutedColor = computed(() => cssVar('--text-muted'))
const fontData = computed(() => cssVar('--font-data'))
const fontUi = computed(() => cssVar('--font-ui'))

// Fill colors by node type
const TYPE_FILL_VAR = {
  external: '--surface-2',
  infrastructure: '--accent',
  service: '--success',
  agent: '--warning',
}

function nodeFill(node) {
  const varName = TYPE_FILL_VAR[node.type] || '--surface-2'
  const base = cssVar(varName)
  // Use a dim version so it doesn't overpower text
  if (node.type === 'infrastructure') return `color-mix(in srgb, ${base} 20%, var(--surface))`
  if (node.type === 'service') return `color-mix(in srgb, ${base} 18%, var(--surface))`
  if (node.type === 'agent') return `color-mix(in srgb, ${base} 18%, var(--surface))`
  return cssVar('--surface')
}

function nodeStroke(node) {
  const health = node.health_status || node.health_check_result
  if (health === 'healthy' || health === 'ok') return cssVar('--success')
  if (health === 'down' || health === 'error') return cssVar('--danger')
  if (health === 'degraded' || health === 'warn') return cssVar('--warning')
  return cssVar('--text-muted')
}

function selectNode(node) {
  selected.value = selected.value?.target === node.target ? null : node
}

function truncate(str, max) {
  if (!str) return ''
  return str.length > max ? str.slice(0, max - 1) + '…' : str
}

function formatDeps(deps) {
  if (!deps?.length) return '—'
  return deps.join(', ')
}
</script>

<template>
  <div class="dep-graph-container">
    <div v-if="!nodes.length" class="empty-msg">
      No dependencies configured. Add dependencies in Settings or YAML config.
    </div>
    <svg v-else ref="svgEl" :viewBox="viewBox" class="dep-graph-svg">
      <defs>
        <marker id="arrowhead" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
          <polygon points="0 0, 8 3, 0 6" :fill="arrowColor" />
        </marker>
      </defs>

      <!-- Edges (arrows from child to parent dependency) -->
      <line
        v-for="(edge, i) in edges"
        :key="'e' + i"
        :x1="edge.x1"
        :y1="edge.y1"
        :x2="edge.x2"
        :y2="edge.y2"
        :stroke="arrowColor"
        stroke-width="1.5"
        marker-end="url(#arrowhead)"
      />

      <!-- Nodes -->
      <g
        v-for="node in layoutNodes"
        :key="node.target"
        :transform="`translate(${node.x}, ${node.y})`"
        class="dep-node"
        @click="selectNode(node)"
      >
        <rect
          :width="nodeWidth"
          :height="nodeHeight"
          rx="6"
          :fill="nodeFill(node)"
          :stroke="nodeStroke(node)"
          stroke-width="2"
          :stroke-dasharray="node.type === 'external' ? '6,3' : 'none'"
        />
        <text
          :x="nodeWidth / 2"
          :y="20"
          text-anchor="middle"
          :fill="textColor"
          font-size="12"
          :font-family="fontData"
        >
          {{ truncate(node.target, 18) }}
        </text>
        <text
          :x="nodeWidth / 2"
          :y="36"
          text-anchor="middle"
          :fill="mutedColor"
          font-size="10"
          :font-family="fontUi"
        >
          {{ node.type }}{{ node.site ? ' · ' + node.site : '' }}
        </text>
      </g>
    </svg>

    <!-- Selected node detail popover -->
    <div v-if="selected" class="dep-detail">
      <h4>{{ selected.target }}</h4>
      <div class="row">
        <span class="row-label">Type</span>
        <span class="row-val badge ba">{{ selected.type }}</span>
      </div>
      <div class="row">
        <span class="row-label">Site</span>
        <span class="row-val">{{ selected.site || '—' }}</span>
      </div>
      <div class="row">
        <span class="row-label">Health Check</span>
        <span class="row-val">{{ selected.health_check || '—' }}</span>
      </div>
      <div v-if="selected.depends_on?.length" class="row">
        <span class="row-label">Depends On</span>
        <span class="row-val">{{ formatDeps(selected.depends_on) }}</span>
      </div>
      <div v-if="selected.auto_discovered" class="row">
        <span class="row-label">Discovery</span>
        <span class="row-val badge bw">
          Auto-discovered{{ selected.confirmed ? ' (confirmed)' : '' }}
        </span>
      </div>
      <button class="btn btn-xs" @click="selected = null">Close</button>
    </div>
  </div>
</template>

<style scoped>
.dep-graph-container {
  position: relative;
}

.dep-graph-svg {
  width: 100%;
  height: auto;
  min-height: 300px;
  background: var(--surface-2);
  border-radius: 8px;
  border: 1px solid var(--border);
}

.dep-node {
  cursor: pointer;
}

.dep-node:hover rect {
  filter: brightness(1.2);
}

.dep-detail {
  position: absolute;
  top: 1rem;
  right: 1rem;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 1rem;
  min-width: 250px;
  z-index: 10;
}

.dep-detail h4 {
  margin: 0 0 .5rem;
}
</style>
