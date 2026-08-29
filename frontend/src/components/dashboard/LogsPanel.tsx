import { useQuery } from '@tanstack/react-query'
import { RefreshCw, ScrollText, X } from 'lucide-react'
import { api } from '../../api/client'

export function LogsPanel({ name, onClose }: { name: string; onClose: () => void }) {
  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: ['containerLogs', name],
    queryFn: () => api.containers.getLogs(name),
  })

  return (
    <div className="border-t border-[var(--color-border)] bg-[var(--color-bg-panel-alt)]">
      <div className="flex items-center justify-between px-4 py-2.5">
        <div className="flex items-center gap-2 text-xs font-medium text-[var(--color-text-muted)]">
          <ScrollText size={14} className="text-blue-400" />
          Logs: {name}
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="inline-flex items-center gap-1 rounded border border-[var(--color-border)] px-2 py-0.5 text-[11px] font-medium text-[var(--color-text-primary)] hover:bg-[var(--color-border)] transition-colors disabled:opacity-50"
          >
            <RefreshCw size={11} className={isFetching ? 'animate-spin' : ''} />
            Refresh
          </button>
          <button onClick={onClose} className="rounded p-0.5 text-[var(--color-text-dim)] hover:text-[var(--color-text-primary)]">
            <X size={14} />
          </button>
        </div>
      </div>

      <div className="max-h-80 overflow-y-auto border-t border-[var(--color-border)]">
        {isLoading && <p className="px-4 py-4 text-xs text-[var(--color-text-dim)]">Loading logs...</p>}
        {error && <p className="px-4 py-4 text-xs text-red-400">{(error as Error).message}</p>}
        {data?.logs === '' && (
          <p className="px-4 py-4 text-xs text-[var(--color-text-dim)]">No log output.</p>
        )}
        {data?.logs && (
          <pre className="whitespace-pre-wrap break-all px-4 py-3 font-mono text-[11px] leading-relaxed text-[var(--color-text-primary)]">
            {data.logs}
          </pre>
        )}
      </div>
    </div>
  )
}
