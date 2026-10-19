<script setup lang="ts">
import ProjectForm from './components/ProjectForm.vue'
import ProjectList from './components/ProjectList.vue'
import AgentGraph from './components/AgentGraph.vue'
import HITLPanel from './components/HITLPanel.vue'
import TerminalLogs from './components/TerminalLogs.vue'
import MetricCards from './components/MetricCards.vue'
import { useProjectsStore } from './stores/projects'

const store = useProjectsStore()
</script>

<template>
  <div class="min-h-screen flex flex-col lg:flex-row">
    <aside class="lg:w-80 p-4 space-y-4 border-b lg:border-b-0 lg:border-r border-space-600/40">
      <h1 class="text-2xl font-bold glow-text">◇ Multi-Agent</h1>
      <ProjectForm />
      <ProjectList />
    </aside>
    <main class="flex-1 p-4 lg:p-6 space-y-4 min-w-0">
      <div v-if="store.activeId" class="space-y-4">
        <AgentGraph />
        <HITLPanel />
        <MetricCards />
        <TerminalLogs />
      </div>
      <div v-else class="h-full min-h-[50vh] grid place-items-center text-muted">
        Start a build to watch the pipeline run.
      </div>
    </main>
  </div>
</template>
