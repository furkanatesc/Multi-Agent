import type { RunSummary } from '../types'

export type RunMode = 'real' | 'demo'

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return (await res.json()) as T
}

export function startProject(
  prompt: string,
  platform: string | null,
  mode: RunMode,
): Promise<{ project_id: string; mode: RunMode }> {
  return fetch(`/api/projects?mode=${mode}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt, platform }),
  }).then((r) => json(r))
}

export function listProjects(): Promise<{ runs: RunSummary[] }> {
  return fetch('/api/projects').then((r) => json(r))
}

export function approveHitl(
  id: string,
  decision: 'approve' | 'reject',
  feedback?: string,
): Promise<{ project_id: string; accepted: boolean }> {
  return fetch(`/api/hitl/${id}/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ decision, feedback: feedback ?? null }),
  }).then((r) => json(r))
}
