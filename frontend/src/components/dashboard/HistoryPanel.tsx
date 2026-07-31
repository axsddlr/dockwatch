import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { History, RotateCcw, X } from 'lucide-react'
import { api } from '../../api/client'
import { hasPermission } from '../RequireAuth'

const STATUS_COLOR: Record<string, string> = {
  success: 'text-green-400 bg-green-400/10 border-green-400/30',
  failed: 'text-red-400 bg-red-400/10 border-red-400/30',
}

const ACTION_LABEL: Record<string, string> = {
  update: 'Update',
  rollback: 'Rollback',
  restart: 'Restart',
  digest_drift_detected: 'Digest drift',
}

export function HistoryPanel({ name, onClose }: { name: string; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [message, setMessage] = useState<string | null>(null)
  const canRollback = hasPermission('update_containers')

  const { data, isLoading, error } = useQuery({
    queryKey: ['containerHistory', name],
    queryFn: () => api.containers.getHistory(name),
  })

  const rollbackMutation = useMutation({
    mutationFn: () => api.containers.rollback(name),
    onSuccess: (data) => {
      setMessage(data.plan.message)
      queryClient.invalidateQueries({ queryKey: ['containerHistory', name] })
      queryClient.invalidateQueries({ queryKey: ['containers'] })
    },
    onError: (e: Error) => setMessage(e.message),
  })

  const lastSuccessfulUpdate = data?.find((e) => e.action === 'update' && e.status === 'success')
  const canOfferRollback = canRollback && lastSuccessfulUpdate && lastSuccessfulUpdate.id === data?.[0]?.id

  return (
    <div className="border-t border-[var(--color-border)] bg-[var(--color-bg-panel-alt)]">
      <div className="flex items-center justify-between px-4 py-2.5">
        <div className="flex items-center gap-2 text-xs font-medium text-[var(--color-text-muted)]">
          <History size={14} className="text-blue-400" />
          Update history: {name}
        </div>
        <div className="flex items-center gap-3">
          {canOfferRollback && (
            <button
              onClick={() => rollbackMutation.mutate()}
              disabled={rollbackMutation.isPending}
              className="inline-flex items-center gap-1 rounded border border-[var(--color-border)] px-2 py-0.5 text-[11px] font-medium text-[var(--color-text-primary)] hover:bg-[var(--color-border)] transition-colors disabled:opacity-50"
              title={`Roll back to ${lastSuccessfulUpdate?.old_tag}`}
            >
              <RotateCcw size={11} className={rollbackMutation.isPending ? 'animate-spin' : ''} />
              Rollback to {lastSuccessfulUpdate?.old_tag}
            </button>
          )}
          <button onClick={onClose} className="rounded p-0.5 text-[var(--color-text-dim)] hover:text-[var(--color-text-primary)]">
            <X size={14} />
          </button>
        </div>
      </div>

      {message && <p className="px-4 pb-2 text-xs text-[var(--color-text-muted)]">{message}</p>}

      <div className="max-h-64 overflow-y-auto border-t border-[var(--color-border)]">
        {isLoading && <p className="px-4 py-4 text-xs text-[var(--color-text-dim)]">Loading history...</p>}
        {error && <p className="px-4 py-4 text-xs text-red-400">{(error as Error).message}</p>}
        {data && data.length === 0 && (
          <p className="px-4 py-4 text-xs text-[var(--color-text-dim)]">No recorded update activity yet.</p>
        )}
        {data?.map((entry) => (
          <div key={entry.id} className="flex items-start gap-3 border-b border-[var(--color-border)] px-4 py-2.5 text-xs last:border-b-0">
            <span
              className={`inline-flex items-center gap-1 rounded border px-1.5 py-px text-[10px] font-semibold flex-shrink-0 ${
                STATUS_COLOR[entry.status] || 'text-zinc-400 bg-zinc-400/10 border-zinc-400/30'
              }`}
            >
              {entry.action === 'rollback' && <RotateCcw size={10} />}
              {ACTION_LABEL[entry.action] || entry.action}
            </span>
            <div className="min-w-0 flex-1 space-y-0.5">
              <div className="font-mono text-[var(--color-text-primary)]">
                {entry.old_tag ?? '-'} <span className="text-[var(--color-text-dim)]">&rarr;</span> {entry.new_tag ?? '-'}
              </div>
              {entry.error && <div className="text-red-400">{entry.error}</div>}
              <div className="flex items-center gap-2 text-[var(--color-text-dim)]">
                <span>{entry.username ?? 'unknown'}</span>
                <span>{new Date(entry.created_at).toLocaleString()}</span>
                {entry.source !== 'local' && <span>({entry.source})</span>}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
