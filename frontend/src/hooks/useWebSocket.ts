import { useEffect, useRef, useCallback } from 'react'
import type { WsMessage } from '../types'
import { useDashboardStore } from '../store/dashboardStore'

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
