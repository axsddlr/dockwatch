import { useDashboardStore } from '../../store/dashboardStore'
import { deriveStatus, STATUS_CONFIG, type ContainerStatus } from '../../types'

export function FilterBar() {
  const results = useDashboardStore((s) => s.results)
  const selected = useDashboardStore((s) => s.selectedStatuses)
  const selectedSource = useDashboardStore((s) => s.selectedSource)
  const toggle = useDashboardStore((s) => s.toggleStatusFilter)

  const statuses: ContainerStatus[] = ['UP_TO_DATE', 'OUTDATED', 'PINNED', 'LOCAL', 'UNKNOWN', 'ERROR']

  const sourceFiltered = selectedSource === 'all'
    ? results
    : results.filter((r) => r.container_info.source === selectedSource)

  return (
    <div className="flex flex-wrap gap-2">
      {statuses.map((status) => {
        const cfg = STATUS_CONFIG[status]
        const count = sourceFiltered.filter((r) => deriveStatus(r) === status).length
        const isActive = selected.size === 0 || selected.has(status)

        return (
          <button
            key={status}
            onClick={() => toggle(status)}
            className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
              isActive
                ? `${cfg.bg} ${cfg.color} border-current/30`
                : 'border-[var(--color-border)] text-[var(--color-text-dim)] bg-transparent opacity-50'
            }`}
          >
            {cfg.label}
            <span className="tabular-nums opacity-70">{count}</span>
          </button>
        )
      })}
    </div>
  )
}
