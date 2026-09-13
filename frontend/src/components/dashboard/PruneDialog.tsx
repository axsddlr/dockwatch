import { useEffect } from 'react'
import { X, AlertTriangle, Trash2 } from 'lucide-react'
import { usePrunePreview, useRunPrune } from '../../hooks/usePrune'
import type { PruneCandidate } from '../../types'

function formatBytes(bytes: number): string {
  if (!bytes || bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  const value = bytes / Math.pow(1024, i)
  return `${value.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}

function shortId(imageId: string): string {
  return imageId.replace('sha256:', '').slice(0, 12)
}

function tagLabel(candidate: PruneCandidate): string {
  if (candidate.repo_tags.length === 0) return '<none>'
  return candidate.repo_tags.join(', ')
}

export function PruneDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const previewQuery = usePrunePreview(open)
  const runMutation = useRunPrune()

  // Clear any previous run result when the dialog is reopened.
  const resetRun = runMutation.reset
  useEffect(() => {
    if (open) resetRun()
  }, [open, resetRun])

  if (!open) return null

  const preview = previewQuery.data?.preview ?? null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="w-full max-w-2xl rounded-xl border border-[var(--color-border-strong)] bg-[var(--color-bg-panel)] p-6 shadow-[0_8px_30px_rgba(0,0,0,0.35)]">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2">
            <Trash2 size={18} className="text-[var(--color-primary)]" />
            <h3 className="text-base font-semibold text-[var(--color-text-primary)]">Prune images</h3>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1 text-[var(--color-text-muted)] hover:bg-[var(--color-border)] hover:text-[var(--color-text-primary)]"
          >
            <X size={16} />
          </button>
        </div>

        <div className="mt-4 space-y-3">
          {previewQuery.isLoading && (
            <p className="text-sm text-[var(--color-text-muted)]">Loading preview…</p>
          )}

          {previewQuery.isError && (
            <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-400">
              {previewQuery.error instanceof Error ? previewQuery.error.message : 'Failed to load preview.'}
            </div>
          )}

          {preview && (
            <>
              <div className="flex items-center justify-between rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm">
                <span className="text-[var(--color-text-muted)]">
                  {preview.candidates.length} image(s) eligible ({preview.mode})
                </span>
                <span className="font-mono text-[var(--color-text-primary)]">
                  {formatBytes(preview.estimated_bytes)} reclaimable
                </span>
              </div>

              {preview.candidates.length === 0 ? (
                <p className="text-sm text-[var(--color-text-muted)]">
                  Nothing to prune — no images match the current mode.
                </p>
              ) : (
                <div className="max-h-64 overflow-y-auto rounded-lg border border-[var(--color-border)]">
                  <table className="w-full text-xs">
                    <thead className="sticky top-0 bg-[var(--color-bg-table-head)] text-left text-[var(--color-text-muted)]">
                      <tr>
                        <th className="px-3 py-2 font-medium">Image</th>
                        <th className="px-3 py-2 font-medium">Tags</th>
                        <th className="px-3 py-2 font-medium">Size</th>
                        <th className="px-3 py-2 font-medium">Reason</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[var(--color-border)]">
                      {preview.candidates.map((candidate) => (
                        <tr key={candidate.image_id} className="hover:bg-[var(--color-bg-panel-alt)]/50">
                          <td className="px-3 py-1.5 font-mono text-[var(--color-text-primary)]">
                            {shortId(candidate.image_id)}
                          </td>
                          <td className="max-w-[180px] truncate px-3 py-1.5 text-[var(--color-text-primary)]">
                            {tagLabel(candidate)}
                          </td>
                          <td className="px-3 py-1.5 text-[var(--color-text-muted)]">
                            {formatBytes(candidate.size_bytes)}
                          </td>
                          <td className="px-3 py-1.5 text-[var(--color-text-muted)]">{candidate.reason}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}

          {runMutation.isError && (
            <div className="flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-400">
              <AlertTriangle size={14} />
              {runMutation.error instanceof Error ? runMutation.error.message : 'Prune failed'}
            </div>
          )}

          {runMutation.isSuccess && (
            <div className="rounded-lg border border-green-500/30 bg-green-500/10 px-3 py-2 text-sm text-green-400">
              Removed {runMutation.data.removed.length} image(s), reclaimed{' '}
              {formatBytes(runMutation.data.reclaimed_bytes)}.
            </div>
          )}
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="rounded-lg border border-[var(--color-border)] px-4 py-2 text-sm font-medium text-[var(--color-text-muted)] hover:bg-[var(--color-border)] transition-colors"
          >
            {runMutation.isSuccess ? 'Done' : 'Cancel'}
          </button>
          {!runMutation.isSuccess && (
            <button
              onClick={() => runMutation.mutate(undefined)}
              disabled={runMutation.isPending || previewQuery.isLoading || (preview?.candidates.length ?? 0) === 0}
              className="rounded-lg bg-[var(--color-primary)] px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {runMutation.isPending ? 'Pruning...' : `Prune ${preview?.candidates.length ?? 0} image(s)`}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
