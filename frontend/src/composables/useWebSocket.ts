import type { StreamEvent } from '../types'

/**
 * Open a stream to a run and invoke `onEvent` per message. Reconnects on drop
 * until a terminal `completed` event is seen. The backend replays the run's
 * history from index 0 on every connection, so `onReplay` is called before each
 * reconnect to let the consumer reset derived state (no double-counting).
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

  const open = (isRetry: boolean): void => {
    if (isRetry) onReplay()
    ws = new WebSocket(url())
    ws.onmessage = (m: MessageEvent<string>) => {
      const ev = JSON.parse(m.data) as StreamEvent
      if (ev.type === 'completed') done = true
      onEvent(ev)
    }
    ws.onclose = () => {
      if (!closedByUs && !done) retry = setTimeout(() => open(true), 1000)
    }
  }

  open(false)
  return () => {
    closedByUs = true
    if (retry) clearTimeout(retry)
    ws?.close()
  }
}
