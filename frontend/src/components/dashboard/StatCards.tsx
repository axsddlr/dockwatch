import { useDashboardStore } from '../../store/dashboardStore'
import { deriveStatus } from '../../types'

export function StatCards() {
  const results = useDashboardStore((s) => s.results)

  const counts = results.reduce(
    (acc, r) => {
      acc.total++
      const s = deriveStatus(r)
      if (s === 'UP_TO_DATE') acc.upToDate++
      else if (s === 'OUTDATED') acc.outdated++
      else if (s === 'PINNED') acc.pinned++
      return acc
    },
    { total: 0, upToDate: 0, outdated: 0, pinned: 0 },
  )

  const cards = [
    { label: 'Total', value: counts.total, color: 'text-[var(--color-text-primary)]' },
    { label: 'Up-to-date', value: counts.upToDate, color: 'text-green-400' },
    { label: 'Outdated', value: counts.outdated, color: 'text-red-400' },
    { label: 'Pinned', value: counts.pinned, color: 'text-blue-400' },
  ]

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {cards.map((c) => (
        <div
          key={c.label}
          className="rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-panel)] p-4"
        >
          <div className="text-xs font-medium text-[var(--color-text-muted)] uppercase tracking-wider">
            {c.label}
          </div>
          <div className={`mt-1 text-2xl font-bold tabular-nums ${c.color}`}>
            {c.value}
          </div>
        </div>
      ))}
    </div>
  )
}
