import { useMutation, useQueryClient } from '@tanstack/react-query'
import { RefreshCw, Monitor, Globe, Server, Layers } from 'lucide-react'
import { api } from '../../api/client'
import { useDashboardStore } from '../../store/dashboardStore'
import { useEnvironments } from '../../hooks/useEnvironments'

export function Toolbar() {
  const queryClient = useQueryClient()
  const source = useDashboardStore((s) => s.selectedSource)
  const environment = useDashboardStore((s) => s.selectedEnvironment)
  const isChecking = useDashboardStore((s) => s.isChecking)
  const autoRefresh = useDashboardStore((s) => s.autoRefresh)
  const autoRefreshInterval = useDashboardStore((s) => s.autoRefreshInterval)
  const setSource = useDashboardStore((s) => s.setSelectedSource)
  const setEnvironment = useDashboardStore((s) => s.setSelectedEnvironment)
  const setResults = useDashboardStore((s) => s.setResults)
  const setAutoRefresh = useDashboardStore((s) => s.setAutoRefresh)
  const setAutoRefreshInterval = useDashboardStore((s) => s.setAutoRefreshInterval)

  const checkMutation = useMutation({
    mutationFn: () => api.containers.check(source, environment ?? undefined),
    onSuccess: (data) => {
      setResults(data)
      queryClient.invalidateQueries({ queryKey: ['containers'] })
    },
  })

  const { data: envData } = useEnvironments(source === 'portainer' || source === 'all')
  const environments = envData?.environments ?? []

  return (
    <div className="flex flex-wrap items-center gap-3">
      <button
        onClick={() => checkMutation.mutate()}
        disabled={isChecking}
        className="inline-flex items-center gap-2 rounded-lg bg-[var(--color-primary)] px-4 py-2 text-sm font-medium text-black transition-opacity hover:opacity-90 disabled:opacity-50"
      >
        <RefreshCw size={16} className={isChecking ? 'animate-spin' : ''} />
        {isChecking ? 'Checking...' : 'Refresh'}
      </button>

      <div className="flex items-center gap-2 text-xs text-[var(--color-text-muted)]">
        <span>Auto:</span>
        <button
          onClick={() => setAutoRefresh(!autoRefresh)}
          className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
            autoRefresh ? 'bg-[var(--color-primary)]' : 'bg-[var(--color-border-strong)]'
          }`}
        >
          <span
            className={`inline-block h-3.5 w-3.5 rounded-full bg-white transition-transform ${
              autoRefresh ? 'translate-x-[18px]' : 'translate-x-[3px]'
            }`}
          />
        </button>
        {autoRefresh && (
          <select
            value={autoRefreshInterval}
            onChange={(e) => setAutoRefreshInterval(Number(e.target.value))}
            className="rounded border border-[var(--color-border)] bg-[var(--color-bg-input)] px-1 py-0.5 text-xs text-[var(--color-text-primary)]"
          >
            <option value={60}>1m</option>
            <option value={120}>2m</option>
            <option value={300}>5m</option>
            <option value={600}>10m</option>
          </select>
        )}
      </div>

      <div className="flex items-center rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)]">
        {(['local', 'portainer', 'all'] as const).map((s) => (
          <button
            key={s}
            onClick={() => setSource(s)}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium transition-colors first:rounded-l-lg last:rounded-r-lg ${
              source === s
                ? 'bg-[var(--color-primary)]/10 text-[var(--color-primary)]'
                : 'text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)]'
            }`}
          >
            {s === 'local' && <Monitor size={14} />}
            {s === 'portainer' && <Server size={14} />}
            {s === 'all' && <Layers size={14} />}
            {s.charAt(0).toUpperCase() + s.slice(1)}
          </button>
        ))}
      </div>

      {environments.length > 0 && (
        <select
          value={environment ?? ''}
          onChange={(e) => setEnvironment(e.target.value || null)}
          className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-1.5 text-xs text-[var(--color-text-primary)]"
        >
          <option value="">All environments</option>
          {environments.map((env) => (
            <option key={env.id} value={String(env.id)}>
              {env.name}
            </option>
          ))}
        </select>
      )}
    </div>
  )
}
