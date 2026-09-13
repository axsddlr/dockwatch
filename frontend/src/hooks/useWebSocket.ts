import { useEffect, useRef, useCallback } from 'react'
import type { WsMessage, HealthStateRecord } from '../types'
import { useDashboardStore, refreshDashboardResults } from '../store/dashboardStore'

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const reconnectDelay = useRef(2000)
  const disposedRef = useRef(false)
  const setResults = useDashboardStore((s) => s.setResults)
  const setWsConnected = useDashboardStore((s) => s.setWsConnected)
  const setIsChecking = useDashboardStore((s) => s.setIsChecking)
  const setLastChecked = useDashboardStore((s) => s.setLastChecked)

  const connect = useCallback(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/ws`
    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onopen = () => {
      setWsConnected(true)
      reconnectDelay.current = 2000
    }

    ws.onmessage = (event) => {
      try {
        const msg: WsMessage = JSON.parse(event.data)
        switch (msg.type) {
          case 'check_started':
            setIsChecking(true)
            break
          case 'check_complete': {
            const results = (msg.payload.results as never) || []
            setResults(results)
            setIsChecking(false)
            setLastChecked(new Date().toISOString())
            break
          }
          case 'container_updated':
            setIsChecking(false)
            break
          case 'health_updated': {
            // Patch each row's state/health_status from the health engine's
            // snapshot, so the health indicator updates live without a full
            // container re-check.
            const states = (msg.payload.states as HealthStateRecord[]) || []
            const byName = new Map(states.map((s) => [s.container_name, s]))
            const store = useDashboardStore.getState()
            store.setResults(
              store.results.map((r) => {
                const hs = byName.get(r.container_info.name)
                if (!hs) return r
                return {
                  ...r,
                  container_info: { ...r.container_info, state: hs.state, health_status: hs.health_status },
                }
              }),
            )
            break
          }
          case 'health_restarted':
            // A container was auto-restarted; re-check so its row reflects
            // the new running state.
            void refreshDashboardResults()
            break
          case 'prune_started':
          case 'prune_complete':
            // Pruning progress is owned by the PruneDialog mutation; the
            // dashboard has no separate prune state to reflect.
            break
          case 'error':
            setIsChecking(false)
            break
        }
      } catch { /* ignore malformed */ }
    }

    ws.onclose = () => {
      setWsConnected(false)
      // Closing during unmount must not schedule a reconnect, or the socket
      // keeps reconnecting forever after the component is gone.
      if (disposedRef.current) return
      reconnectTimer.current = setTimeout(() => {
        reconnectDelay.current = Math.min(reconnectDelay.current * 1.5, 30000)
        connect()
      }, reconnectDelay.current)
    }

    ws.onerror = () => {
      ws.close()
    }
  }, [setResults, setWsConnected, setIsChecking, setLastChecked])

  useEffect(() => {
    disposedRef.current = false
    connect()
    return () => {
      disposedRef.current = true
      clearTimeout(reconnectTimer.current)
      wsRef.current?.close()
    }
  }, [connect])
}
