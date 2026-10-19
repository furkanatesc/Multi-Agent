<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import { useProjectsStore } from '../stores/projects'

const store = useProjectsStore()
const box = ref<HTMLDivElement | null>(null)

watch(
  () => store.logs.length,
  async () => {
    await nextTick()
    if (box.value) box.value.scrollTop = box.value.scrollHeight
  },
)
</script>

<template>
  <div class="panel p-4">
    <h2 class="text-sm uppercase tracking-widest text-muted mb-2">Logs</h2>
    <div ref="box" class="font-mono text-xs h-48 overflow-y-auto space-y-0.5">
      <p v-if="store.logs.length === 0" class="text-muted">Waiting for agent output…</p>
      <div v-for="(line, i) in store.logs" :key="i" class="text-[#c3cdea]">
        <span class="text-glow-cyan">›</span> {{ line }}
      </div>
      <div v-if="store.runError" class="text-red-400">
        <span>✗</span> {{ store.runError }}
      </div>
    </div>
  </div>
</template>
