<script setup lang="ts">
import { ref } from 'vue'
import { useProjectsStore } from '../stores/projects'

const store = useProjectsStore()
const prompt = ref('')
const platform = ref<string>('react-native')
const demo = ref(true)
const submitting = ref(false)
const error = ref<string | null>(null)

async function submit() {
  if (!prompt.value.trim()) return
  submitting.value = true
  error.value = null
  try {
    await store.start(prompt.value.trim(), platform.value, demo.value ? 'demo' : 'real')
    prompt.value = ''
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <form class="panel p-4 space-y-3" @submit.prevent="submit">
    <textarea
      v-model="prompt"
      rows="3"
      placeholder="Describe the app to build…"
      class="w-full bg-space-900/60 rounded-lg p-3 text-sm outline-none border border-space-600 focus:border-glow-cyan"
    />
    <div class="flex items-center gap-3 text-sm">
      <select v-model="platform" class="bg-space-900/60 rounded-lg p-2 border border-space-600">
        <option value="react-native">React Native</option>
        <option value="flutter">Flutter</option>
        <option value="native-ios">Native iOS</option>
        <option value="native-android">Native Android</option>
      </select>
      <label class="flex items-center gap-2 cursor-pointer">
        <input v-model="demo" type="checkbox" /> Demo mode (keyless)
      </label>
    </div>
    <button
      type="submit"
      :disabled="submitting || !prompt.trim()"
      class="w-full py-2 rounded-lg bg-glow-cyan/20 border border-glow-cyan text-glow-cyan font-semibold hover:bg-glow-cyan/30 disabled:opacity-50"
    >
      {{ submitting ? 'Starting…' : 'Build' }}
    </button>
    <p v-if="error" class="text-xs text-red-400">Could not start run: {{ error }}</p>
  </form>
</template>
