import { AlertTriangle, ShieldAlert, ShieldCheck, ExternalLink, X, Skull } from 'lucide-react'
import type { TrivyScanResult, TrivyFinding } from '../../types'

const SEVERITY_ICON: Record<string, typeof Skull> = {
  CRITICAL: Skull,
  HIGH: AlertTriangle,
  MEDIUM: ShieldAlert,
  LOW: ShieldCheck,
}

const SEVERITY_COLOR: Record<string, string> = {
  CRITICAL: 'text-red-400 bg-red-400/10 border-red-400/30',
  HIGH: 'text-orange-400 bg-orange-400/10 border-orange-400/30',
  MEDIUM: 'text-yellow-400 bg-yellow-400/10 border-yellow-400/30',
  LOW: 'text-blue-400 bg-blue-400/10 border-blue-400/30',
}

function FindingRow({ f }: { f: TrivyFinding }) {
  const Icon = SEVERITY_ICON[f.severity] || ShieldCheck

  return (
    <div className="flex items-start gap-3 border-b border-[var(--color-border)] px-4 py-2.5 text-xs last:border-b-0">
      <span className={`inline-flex items-center gap-1 rounded border px-1.5 py-px text-[10px] font-semibold flex-shrink-0 ${SEVERITY_COLOR[f.severity] || 'text-zinc-400 bg-zinc-400/10 border-zinc-400/30'}`}>
        <Icon size={10} />
        {f.severity}
      </span>
      <div className="min-w-0 flex-1 space-y-0.5">
        <div className="font-medium text-[var(--color-text-primary)]">{f.title || f.vulnerability_id}</div>
        <div className="text-[var(--color-text-muted)]">
          {f.pkg_name} {f.installed_version}
          {f.fixed_version && (
            <span className="text-green-400"> &rarr; {f.fixed_version}</span>
          )}
        </div>
        <div className="flex items-center gap-2 text-[var(--color-text-dim)]">
          {f.vulnerability_id && <span className="font-mono">{f.vulnerability_id}</span>}
          {f.primary_url && (
            <a
              href={f.primary_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-0.5 text-[var(--color-primary)] hover:underline"
            >
              <ExternalLink size={10} />
              Details
            </a>
          )}
        </div>
      </div>
    </div>
  )
}

export function ScanResultsPanel({
  result,
  name,
  onClose,
}: {
  result: TrivyScanResult
  name: string
  onClose: () => void
}) {
  if (result.error) {
    return (
      <div className="border-t border-[var(--color-border)] bg-[var(--color-bg-panel-alt)] px-4 py-3">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2 text-xs font-medium text-[var(--color-text-muted)]">
            <ShieldAlert size={14} className="text-red-400" />
            Scan: {name}
          </div>
          <button onClick={onClose} className="rounded p-0.5 text-[var(--color-text-dim)] hover:text-[var(--color-text-primary)]">
            <X size={14} />
          </button>
        </div>
        <p className="text-xs text-red-400">{result.error}</p>
      </div>
    )
  }

  const bars = [
    { label: 'CRITICAL', count: result.critical_count, color: 'bg-red-500' },
    { label: 'HIGH', count: result.high_count, color: 'bg-orange-500' },
    { label: 'MEDIUM', count: result.medium_count, color: 'bg-yellow-500' },
    { label: 'LOW', count: result.low_count, color: 'bg-blue-500' },
  ]
  const maxCount = Math.max(...bars.map((b) => b.count), 1)

  return (
    <div className="border-t border-[var(--color-border)] bg-[var(--color-bg-panel-alt)]">
      <div className="flex items-center justify-between px-4 py-2.5">
        <div className="flex items-center gap-2 text-xs font-medium text-[var(--color-text-muted)]">
          <ShieldAlert size={14} className="text-purple-400" />
          Trivy scan: {name}
          <span className="text-[var(--color-text-dim)]">
            ({result.total_count} vulns)
          </span>
        </div>
        <button onClick={onClose} className="rounded p-0.5 text-[var(--color-text-dim)] hover:text-[var(--color-text-primary)]">
          <X size={14} />
        </button>
      </div>

      <div className="flex gap-1 px-4 pb-2.5">
        {bars.map((b) => (
          <div key={b.label} className="flex-1" title={`${b.label}: ${b.count}`}>
            <div className="text-center text-[10px] font-semibold text-[var(--color-text-dim)] mb-0.5">
              {b.count}
            </div>
            <div className="h-1 rounded-full bg-[var(--color-border)] overflow-hidden">
              <div
                className={`h-full rounded-full ${b.color} transition-all`}
                style={{ width: `${(b.count / maxCount) * 100}%` }}
              />
            </div>
          </div>
        ))}
      </div>

      <div className="max-h-64 overflow-y-auto border-t border-[var(--color-border)]">
        {result.findings.length === 0 ? (
          <p className="px-4 py-4 text-xs text-green-400">
            <ShieldCheck size={14} className="inline mr-1" />
            No vulnerabilities found.
          </p>
        ) : (
          result.findings.map((f, i) => <FindingRow key={`${f.vulnerability_id}-${i}`} f={f} />)
        )}
      </div>
    </div>
  )
}
