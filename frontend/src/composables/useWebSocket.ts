import type { StreamEvent } from '../types'

/**
 * Open a stream to a run and invoke `onEvent` per message. Reconnects on drop
 * (exponential backoff, max 10s) until a terminal `completed` event is seen.
 * The backend replays the run's history from index 0 on every connection, so
 * `onReplay` is called when a reconnect opens, letting the consumer reset
 * derived state (no double-counting).
 */
export function connectStream(
  projectId: string,
  onEvent: (ev: StreamEvent) => void,
  onReplay: () => void,
): () => void {
  let ws: WebSocket | null = null
  let closedByUs = false
  let done = false
  let retry: ReturnType<typeof setTimeout> | null = null

  const url = (): string => {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    return `${proto}://${location.host}/api/projects/${projectId}/stream`
  }

  let attempt = 0

  const open = (isRetry: boolean): void => {
    if (closedByUs) return
    const socket = new WebSocket(url())
    ws = socket
    socket.onopen = () => {
      attempt = 0
      // Reset only once the replaying connection is actually up, so a down
      // server doesn't blank the view while we retry.
      if (isRetry && !closedByUs) onReplay()
    }
    socket.onmessage = (m: MessageEvent<string>) => {
      // A closing socket can still deliver buffered frames; never let them
      // leak into whatever run is selected next.
      if (closedByUs || socket !== ws) return
      const ev = JSON.parse(m.data) as StreamEvent
      if (ev.type === 'completed') done = true
      onEvent(ev)
    }
    socket.onclose = () => {
      if (closedByUs || done || socket !== ws) return
      const delay = Math.min(1000 * 2 ** attempt, 10000)
      attempt += 1
      retry = setTimeout(() => open(true), delay)
    }
  }

  open(false)
  return () => {
    closedByUs = true
    if (retry) clearTimeout(retry)
    ws?.close()
  }
}
