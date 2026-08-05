import { useEffect, useRef } from 'react'
import { useDashboardStore } from '../store/dashboardStore'
import { useWebSocket } from '../hooks/useWebSocket'
import { StatCards } from '../components/dashboard/StatCards'
import { Toolbar } from '../components/dashboard/Toolbar'
import { FilterBar } from '../components/dashboard/FilterBar'
import { ContainerTable } from '../components/dashboard/ContainerTable'
import { ConnectionStatus } from '../components/dashboard/ConnectionStatus'

export function DashboardPage() {
  useWebSocket()
  const setResults = useDashboardStore((s) => s.setResults)
  const autoRefresh = useDashboardStore((s) => s.autoRefresh)
  const autoRefreshInterval = useDashboardStore((s) => s.autoRefreshInterval)
  const source = useDashboardStore((s) => s.selectedSource)
  const environment = useDashboardStore((s) => s.selectedEnvironment)
  const isChecking = useDashboardStore((s) => s.isChecking)
  const isCheckingRef = useRef(false)

  useEffect(() => {
    isCheckingRef.current = isChecking
  }, [isChecking])

  useEffect(() => {
    if (!autoRefresh) return
    const timer = setInterval(() => {
      if (isCheckingRef.current) return
      const params = new URLSearchParams({ source })
      if (environment) params.set('environment', environment)
      fetch(`/api/containers/check?${params}`, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' } })
        .then((r) => { if (r.ok) return r.json(); throw new Error(`HTTP ${r.status}`) })
        .then((data) => setResults(data))
        .catch(() => {})
    }, autoRefreshInterval * 1000)
    return () => clearInterval(timer)
  }, [autoRefresh, autoRefreshInterval, source, environment, setResults])

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-[var(--color-text-primary)]">Dashboard</h1>
        <ConnectionStatus />
      </div>

      <StatCards />

      <div className="flex flex-col gap-3">
        <Toolbar />
        <FilterBar />
      </div>

      <ContainerTable />
    </div>
  )
}
