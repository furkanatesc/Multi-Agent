export type NodeName =
  | 'supervisor' | 'architect' | 'coder' | 'inner_loop_check'
  | 'security_scan' | 'hitl_gate' | 'test_generator' | 'reviewer'
  | 'deploy_gate' | 'deployer'

export type NodeStatus = 'idle' | 'running' | 'complete'

export type GateType = 'security' | 'deploy'

export interface HitlPayload {
  gate_type: GateType
  question?: string
  security_score?: number | null
  security_critical?: boolean
  review_decision?: string | null
  files?: number
  [k: string]: unknown
}

/** JSON-safe projection of a node's state update (backend `_safe_delta`). */
export interface StateDelta {
  status?: string
  security_score?: number
  review_decision?: string
  total_cost_usd?: number
  iteration_count?: number
  source_files?: string[]
  architecture_spec?: Record<string, unknown>
  [k: string]: unknown
}

export type StreamEvent =
  | { type: 'run_started'; project_id: string; mode: string }
  | { type: 'node'; node: NodeName; status: 'complete'; state_delta: StateDelta }
  | { type: 'log'; line: string }
  | { type: 'hitl_request'; gate_type: GateType; payload: HitlPayload }
  | { type: 'hitl_resolved'; gate_type: GateType | null; decision: string }
  | { type: 'completed'; status: string; error?: string }

export interface RunSummary {
  project_id: string
  mode: string
  prompt: string
  status: string
  awaiting_hitl: boolean
  event_count: number
}

export interface Metrics {
  total_cost_usd: number
  iteration_count: number
  security_score: number | null
  review_decision: string | null
}
