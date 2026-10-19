<script setup lang="ts">
import { computed } from 'vue'
import * as d3 from 'd3'
import { useProjectsStore } from '../stores/projects'

const store = useProjectsStore()

const W = 120
const H = 32

const sparkPath = computed<string>(() => {
  const data = store.costHistory
  if (data.length < 2) return ''
  const x = d3.scaleLinear().domain([0, data.length - 1]).range([0, W])
  const y = d3.scaleLinear().domain([0, d3.max(data) || 1]).range([H - 1, 1])
  const line = d3.line<number>().x((_, i) => x(i)).y((d) => y(d))
  return line(data) ?? ''
})
</script>

<template>
  <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
    <div class="panel p-3">
      <div class="text-xs text-muted">Cost (USD)</div>
      <div class="text-xl font-semibold glow-text">${{ store.metrics.total_cost_usd.toFixed(3) }}</div>
      <svg :width="W" :height="H" class="mt-1" aria-hidden="true">
        <path :d="sparkPath" fill="none" stroke="#38e1ff" stroke-width="1.5" />
      </svg>
    </div>
    <div class="panel p-3">
      <div class="text-xs text-muted">Iterations</div>
      <div class="text-xl font-semibold">{{ store.metrics.iteration_count }}</div>
    </div>
    <div class="panel p-3">
      <div class="text-xs text-muted">Security</div>
      <div class="text-xl font-semibold">{{ store.metrics.security_score ?? '—' }}</div>
    </div>
    <div class="panel p-3">
      <div class="text-xs text-muted">Review</div>
      <div class="text-xl font-semibold">{{ store.metrics.review_decision ?? '—' }}</div>
    </div>
  </div>
</template>
