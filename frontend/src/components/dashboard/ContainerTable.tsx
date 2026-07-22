import { useDashboardStore } from '../../store/dashboardStore'
import { deriveStatus } from '../../types'
import { ContainerRow } from './ContainerRow'
import { ErrorBoundary } from '../ErrorBoundary'

export function ContainerTable() {
  const results = useDashboardStore((s) => s.results)
  const selected = useDashboardStore((s) => s.selectedStatuses)
  const selectedSource = useDashboardStore((s) => s.selectedSource)

  // A malformed record (missing container_info) from a backend edge case
  // shouldn't blank the whole table before rendering even starts.
  const filtered = results
    .filter((r) => r && r.container_info)
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
        filtered.map((r) => (
          <ErrorBoundary
            key={r.container_info.name}
            fallback={(error) => (
              <div className="border-b border-[var(--color-border)] px-4 py-2.5 text-xs text-red-400">
                Failed to render {r.container_info.name}: {error.message}
              </div>
            )}
          >
            <ContainerRow result={r} />
          </ErrorBoundary>
        ))
      )}
    </div>
  )
}
