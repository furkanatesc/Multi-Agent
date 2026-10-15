<script setup lang="ts">
import { watch, nextTick, onBeforeUnmount } from 'vue'
import gsap from 'gsap'
import { useProjectsStore } from '../stores/projects'
import type { NodeName, NodeStatus } from '../types'

const store = useProjectsStore()

// Static two-row constellation layout (x,y in a 1000x360 viewBox), pipeline order.
const POS: Record<NodeName, [number, number]> = {
  supervisor: [60, 90], architect: [210, 90], coder: [360, 90],
  inner_loop_check: [510, 90], security_scan: [660, 90], hitl_gate: [810, 90],
  test_generator: [810, 270], reviewer: [610, 270], deploy_gate: [410, 270],
  deployer: [210, 270],
}
const EDGES: [NodeName, NodeName][] = [
  ['supervisor', 'architect'], ['architect', 'coder'], ['coder', 'inner_loop_check'],
  ['inner_loop_check', 'security_scan'], ['security_scan', 'hitl_gate'],
  ['hitl_gate', 'test_generator'], ['test_generator', 'reviewer'],
  ['reviewer', 'deploy_gate'], ['deploy_gate', 'deployer'],
]

const COLORS: Record<NodeStatus, string> = {
  complete: '#a3e635',
  running: '#38e1ff',
  idle: '#33406b',
}
const R = 14

const color = (n: NodeName): string => COLORS[store.nodes[n]]
const glow = (n: NodeName): string =>
  store.nodes[n] === 'idle' ? 'none' : `drop-shadow(0 0 8px ${color(n)})`
const label = (n: NodeName): string => n.replace(/_/g, ' ')
const edgeActive = (a: NodeName, b: NodeName): boolean =>
  store.nodes[a] === 'complete' && store.nodes[b] !== 'idle'

const nodeEls: Partial<Record<NodeName, SVGCircleElement>> = {}
const setRef = (n: NodeName) => (el: unknown) => {
  if (el) nodeEls[n] = el as SVGCircleElement
  else delete nodeEls[n]
}

// Pulse only on the transition into `running`; stop it on the way out, so
// repeated store updates never stack tweens on the same element.
watch(
  () => ({ ...store.nodes }),
  async (now, before) => {
    await nextTick()
    for (const n of store.nodeOrder) {
      const el = nodeEls[n]
      if (!el || now[n] === before?.[n]) continue
      gsap.killTweensOf(el)
      if (now[n] === 'running') {
        gsap.fromTo(el, { attr: { r: R } }, { attr: { r: R + 6 }, repeat: -1, yoyo: true, duration: 0.7 })
      } else {
        gsap.set(el, { attr: { r: R } })
      }
    }
  },
)

onBeforeUnmount(() => {
  for (const el of Object.values(nodeEls)) if (el) gsap.killTweensOf(el)
})

</script>

<template>
  <div class="panel p-4">
    <div class="flex items-center justify-between mb-2">
      <h2 class="text-sm uppercase tracking-widest text-muted">Agent Graph</h2>
      <span v-if="store.runStatus" class="text-xs text-muted">status: {{ store.runStatus }}</span>
    </div>
    <svg viewBox="0 0 1000 360" class="w-full" role="img" aria-label="Pipeline agent graph">
      <line
        v-for="([a, b], i) in EDGES"
        :key="i"
        :x1="POS[a][0]" :y1="POS[a][1]" :x2="POS[b][0]" :y2="POS[b][1]"
        :stroke="edgeActive(a, b) ? '#38e1ff' : '#1b2350'"
        stroke-width="2"
      />
      <g v-for="n in store.nodeOrder" :key="n">
        <circle
          :ref="setRef(n)"
          :cx="POS[n][0]" :cy="POS[n][1]" :r="R"
          :fill="color(n)"
          :style="{ filter: glow(n), transition: 'fill 0.4s' }"
        />
        <text
          :x="POS[n][0]" :y="POS[n][1] + 34"
          text-anchor="middle" fill="#9fb0d9" font-size="12"
        >{{ label(n) }}</text>
      </g>
    </svg>
  </div>
</template>
