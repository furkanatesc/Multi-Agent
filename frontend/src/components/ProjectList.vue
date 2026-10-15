<script setup lang="ts">
import { onMounted } from 'vue'
import { useProjectsStore } from '../stores/projects'

const store = useProjectsStore()
onMounted(() => {
  store.refreshList().catch(() => {
    /* backend not up yet — list stays empty */
  })
})

const badgeClass = (status: string): string => {
  if (status === 'completed') return 'text-glow-lime border-glow-lime'
  if (status === 'failed') return 'text-red-400 border-red-400'
  if (status === 'awaiting_hitl') return 'text-glow-violet border-glow-violet'
  return 'text-glow-cyan border-glow-cyan'
}
</script>

<template>
  <div class="panel p-4 space-y-2">
    <h2 class="text-sm uppercase tracking-widest text-muted">Runs</h2>
    <p v-if="store.runs.length === 0" class="text-xs text-muted">No runs yet.</p>
    <ul class="space-y-1">
      <li
        v-for="r in store.runs"
        :key="r.project_id"
        class="p-2 rounded-lg cursor-pointer hover:bg-space-700/50 flex items-center justify-between gap-2"
        :class="{ 'bg-space-700/70': r.project_id === store.activeId }"
        @click="store.select(r.project_id)"
      >
        <span class="truncate text-sm">{{ r.prompt || r.project_id }}</span>
        <span
          class="shrink-0 text-xs px-2 py-0.5 rounded-full border"
          :class="badgeClass(r.status)"
        >
          {{ r.status }}
        </span>
      </li>
    </ul>
  </div>
</template>
