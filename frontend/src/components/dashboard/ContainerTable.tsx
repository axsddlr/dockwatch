import { useDashboardStore } from '../../store/dashboardStore'
import { deriveStatus } from '../../types'
import { ContainerRow } from './ContainerRow'

export function ContainerTable() {
  const results = useDashboardStore((s) => s.results)
  const selected = useDashboardStore((s) => s.selectedStatuses)
  const selectedSource = useDashboardStore((s) => s.selectedSource)

  const filtered = results
    .filter((r) => selectedSource === 'all' || r.container_info.source === selectedSource)
    .filter((r) => selected.size === 0 || selected.has(deriveStatus(r)))

  if (results.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-[var(--color-text-muted)]">
        <p className="text-sm">No containers checked yet.</p>
        <p className="mt-1 text-xs text-[var(--color-text-dim)]">
          Click Refresh to discover and check running containers.
        </p>
      </div>
    )
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-panel)]">
      <div className="grid grid-cols-12 items-center gap-2 border-b border-[var(--color-border)] bg-[var(--color-bg-table-head)] px-4 py-2.5 text-xs font-semibold text-[var(--color-text-muted)] uppercase tracking-wider">
        <span className="col-span-3">Container</span>
        <span className="col-span-1">Status</span>
        <span className="col-span-1">Basis</span>
        <span className="col-span-2">Deployed</span>
        <span className="col-span-3">Remote</span>
        <span className="col-span-2"></span>
      </div>

      {filtered.length === 0 ? (
        <p className="px-4 py-8 text-center text-sm text-[var(--color-text-dim)]">
          No containers match the selected filters.
        </p>
      ) : (
        filtered.map((r) => <ContainerRow key={r.container_info.name} result={r} />)
      )}
    </div>
  )
}
