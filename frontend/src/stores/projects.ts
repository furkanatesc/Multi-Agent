import { defineStore } from 'pinia'
import type {
  HitlPayload, Metrics, NodeName, NodeStatus, RunSummary, StreamEvent,
} from '../types'
import * as api from '../services/api'
import { connectStream } from '../composables/useWebSocket'

const NODE_ORDER: NodeName[] = [
  'supervisor', 'architect', 'coder', 'inner_loop_check', 'security_scan',
  'hitl_gate', 'test_generator', 'reviewer', 'deploy_gate', 'deployer',
]

interface State {
  runs: RunSummary[]
  activeId: string | null
  runStatus: string | null
  runError: string | null
  logs: string[]
  nodes: Record<NodeName, NodeStatus>
  hitl: HitlPayload | null
  metrics: Metrics
  costHistory: number[]
  disconnect: (() => void) | null
}

function emptyNodes(): Record<NodeName, NodeStatus> {
  return Object.fromEntries(NODE_ORDER.map((n) => [n, 'idle'])) as Record<NodeName, NodeStatus>
}

function emptyMetrics(): Metrics {
  return { total_cost_usd: 0, iteration_count: 0, security_score: null, review_decision: null }
}

export const useProjectsStore = defineStore('projects', {
  state: (): State => ({
    runs: [],
    activeId: null,
    runStatus: null,
    runError: null,
    logs: [],
    nodes: emptyNodes(),
    hitl: null,
    metrics: emptyMetrics(),
    costHistory: [],
    disconnect: null,
  }),
  getters: {
    nodeOrder: (): NodeName[] => NODE_ORDER,
    isAwaiting: (s): boolean => s.hitl !== null,
  },
  actions: {
    async refreshList() {
      this.runs = (await api.listProjects()).runs
    },
    async start(prompt: string, platform: string | null, mode: api.RunMode) {
      const { project_id } = await api.startProject(prompt, platform, mode)
      await this.refreshList()
      this.select(project_id)
    },
    /** Clear everything derived from the event stream. */
    resetRunView() {
      this.runStatus = 'pending'
      this.runError = null
      this.logs = []
      this.nodes = emptyNodes()
      this.hitl = null
      this.metrics = emptyMetrics()
      this.costHistory = []
    },
    select(id: string) {
      this.disconnect?.()
      this.activeId = id
      this.resetRunView()
      this.disconnect = connectStream(
        id,
        (ev) => this.applyEvent(ev),
        () => this.resetRunView(),
      )
    },
    applyEvent(ev: StreamEvent) {
      switch (ev.type) {
        case 'run_started':
          this.runStatus = 'running'
          break
        case 'log':
          this.logs.push(ev.line)
          break
        case 'node': {
          this.nodes[ev.node] = 'complete'
          const d = ev.state_delta
          // Cost/iterations are additive reducers server-side: deltas are increments.
          if (typeof d.total_cost_usd === 'number') {
            this.metrics.total_cost_usd += d.total_cost_usd
            this.costHistory.push(this.metrics.total_cost_usd)
          }
          if (typeof d.iteration_count === 'number') this.metrics.iteration_count += d.iteration_count
          if (typeof d.security_score === 'number') this.metrics.security_score = d.security_score
          if (typeof d.review_decision === 'string') this.metrics.review_decision = d.review_decision
          break
        }
        case 'hitl_request':
          this.hitl = ev.payload
          this.runStatus = 'awaiting_hitl'
          this.nodes[ev.gate_type === 'security' ? 'hitl_gate' : 'deploy_gate'] = 'running'
          void this.refreshList()
          break
        case 'hitl_resolved':
          this.hitl = null
          this.runStatus = 'running'
          void this.refreshList()
          break
        case 'completed':
          this.hitl = null
          this.runStatus = ev.status
          this.runError = ev.error ?? null
          void this.refreshList()
          break
      }
    },
    async approve(feedback?: string) {
      if (this.activeId) await api.approveHitl(this.activeId, 'approve', feedback)
    },
    async reject(feedback?: string) {
      if (this.activeId) await api.approveHitl(this.activeId, 'reject', feedback)
    },
  },
})
