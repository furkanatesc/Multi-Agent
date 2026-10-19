<script setup lang="ts">
import { ref } from 'vue'
import { useProjectsStore } from '../stores/projects'

const store = useProjectsStore()
const feedback = ref('')
const busy = ref(false)
const error = ref<string | null>(null)

async function decide(kind: 'approve' | 'reject') {
  busy.value = true
  error.value = null
  try {
    if (kind === 'approve') await store.approve(feedback.value || undefined)
    else await store.reject(feedback.value || undefined)
    feedback.value = ''
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div v-if="store.hitl" class="panel p-4 !border-glow-violet/50">
    <h2 class="text-sm uppercase tracking-widest text-glow-violet mb-2">
      Human Approval — {{ store.hitl.gate_type }} gate
    </h2>
    <p class="text-sm text-muted mb-2">{{ store.hitl.question }}</p>
    <ul class="text-sm mb-3 space-y-1">
      <li v-if="store.hitl.security_score != null">Security score: {{ store.hitl.security_score }}</li>
      <li v-if="store.hitl.security_critical">⚠ Critical security finding</li>
      <li v-if="store.hitl.review_decision">Review: {{ store.hitl.review_decision }}</li>
      <li v-if="store.hitl.files != null">Files: {{ store.hitl.files }}</li>
    </ul>
    <input
      v-model="feedback"
      placeholder="Optional feedback…"
      class="w-full bg-space-900/60 rounded-lg p-2 text-sm border border-space-600 mb-3"
    />
    <div class="flex gap-3">
      <button
        :disabled="busy"
        class="flex-1 py-2 rounded-lg bg-glow-lime/20 border border-glow-lime text-glow-lime font-semibold disabled:opacity-50"
        @click="decide('approve')"
      >Approve</button>
      <button
        :disabled="busy"
        class="flex-1 py-2 rounded-lg bg-red-500/20 border border-red-400 text-red-300 font-semibold disabled:opacity-50"
        @click="decide('reject')"
      >Reject</button>
    </div>
    <p v-if="error" class="text-xs text-red-400 mt-2">Could not submit decision: {{ error }}</p>
  </div>
</template>
