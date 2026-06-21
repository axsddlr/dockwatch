import { useEffect } from 'react'
import { useDashboardStore } from '../store/dashboardStore'
import { useWebSocket } from '../hooks/useWebSocket'
import { StatCards } from '../components/dashboard/StatCards'
import { Toolbar } from '../components/dashboard/Toolbar'
import { FilterBar } from '../components/dashboard/FilterBar'
import { ContainerTable } from '../components/dashboard/ContainerTable'
import { ConnectionStatus } from '../components/dashboard/ConnectionStatus'
import { ErrorBanner } from '../components/dashboard/ErrorBanner'
import { api } from '../api/client'
import { useMutation } from '@tanstack/react-query'

export function DashboardPage() {
  useWebSocket()
  const setResults = useDashboardStore((s) => s.setResults)
  const autoRefresh = useDashboardStore((s) => s.autoRefresh)
  const autoRefreshInterval = useDashboardStore((s) => s.autoRefreshInterval)
  const source = useDashboardStore((s) => s.selectedSource)
  const environment = useDashboardStore((s) => s.selectedEnvironment)

  const initialCheck = useMutation({
    mutationFn: () => api.containers.check(source, environment ?? undefined),
    onSuccess: (data) => setResults(data),
  })

  useEffect(() => {
    initialCheck.mutate()
  }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!autoRefresh) return
    const timer = setInterval(() => {
      initialCheck.mutate()
    }, autoRefreshInterval * 1000)
    return () => clearInterval(timer)
  }, [autoRefresh, autoRefreshInterval])  // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-[var(--color-text-primary)]">Dashboard</h1>
        <ConnectionStatus />
      </div>

      <ErrorBanner
        message={initialCheck.error instanceof Error ? initialCheck.error.message : null}
        onDismiss={() => initialCheck.reset()}
      />

      <StatCards />

      <div className="flex flex-col gap-3">
        <Toolbar />
        <FilterBar />
      </div>

      <ContainerTable />
    </div>
  )
}
