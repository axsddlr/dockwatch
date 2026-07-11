import { useEffect, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { X, AlertTriangle, Rocket, Settings2 } from 'lucide-react'
import { api } from '../../api/client'
import type { UpdateResult } from '../../types'
import { ComposeProjectConfigDialog } from './ComposeProjectConfigDialog'

const COMPOSE_UNCONFIGURED_PATTERN = /compose project '.+' is missing from config\.compose_projects|compose project '.+' has no configured workdir/

interface UpdateDialogProps {
  result: UpdateResult
  open: boolean
  onClose: () => void
}

export function UpdateDialog({ result, open, onClose }: UpdateDialogProps) {
  const queryClient = useQueryClient()
  const [showComposeConfig, setShowComposeConfig] = useState(false)

  const updateMutation = useMutation({
    mutationFn: async () => {
      const data = await api.containers.update(result.container_info.name)
      if (!data.ok) {
        throw new Error(
          [data.plan.message, ...data.plan.details].filter(Boolean).join(' — ') ||
            'Update did not complete successfully.',
        )
      }
      return data
    },
    onSuccess: async () => {
      await api.containers.check('local')
      queryClient.invalidateQueries({ queryKey: ['containers'] })
      onClose()
    },
  })

  // Clear error/success left over from a previous update attempt so a
  // reopened dialog doesn't show another container's stale status.
  const resetMutation = updateMutation.reset
  useEffect(() => {
    if (open) resetMutation()
  }, [open, resetMutation])

  if (!open) return null

  const diff = result.version_diff
  const from = result.deployed_display ?? result.deployed_tag ?? result.deployed_version ?? '?'
  const to = result.latest_version ?? result.remote_tag ?? '?'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-xl border border-[var(--color-border-strong)] bg-[var(--color-bg-panel)] p-6 shadow-xl">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2">
            <Rocket size={18} className="text-[var(--color-primary)]" />
            <h3 className="text-base font-semibold text-[var(--color-text-primary)]">
              Update {result.container_info.name}
            </h3>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1 text-[var(--color-text-muted)] hover:bg-[var(--color-border)] hover:text-[var(--color-text-primary)]"
          >
            <X size={16} />
          </button>
        </div>

        <div className="mt-4 space-y-3">
          <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] p-3">
            <div className="flex justify-between text-sm">
              <span className="text-[var(--color-text-muted)]">Current</span>
              <span className="font-mono text-[var(--color-text-primary)]">{from}</span>
            </div>
            <div className="mt-1 flex justify-between text-sm">
              <span className="text-[var(--color-text-muted)]">Target</span>
              <span className="font-mono text-[var(--color-primary)]">{to}</span>
            </div>
            {diff && (
              <div className="mt-1 flex justify-between text-sm">
                <span className="text-[var(--color-text-muted)]">Bump</span>
                <span className="font-semibold text-yellow-400">{diff.bump_type}</span>
              </div>
            )}
          </div>

          {updateMutation.isError && (
            <div className="space-y-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-400">
              <div className="flex items-center gap-2">
                <AlertTriangle size={14} />
                {updateMutation.error instanceof Error ? updateMutation.error.message : 'Update failed'}
              </div>
              {result.container_info.compose_project &&
                updateMutation.error instanceof Error &&
                COMPOSE_UNCONFIGURED_PATTERN.test(updateMutation.error.message) && (
                  <button
                    onClick={() => setShowComposeConfig(true)}
                    className="flex items-center gap-1.5 rounded-lg border border-red-500/30 px-3 py-1.5 text-xs font-medium text-red-300 hover:bg-red-500/10 transition-colors"
                  >
                    <Settings2 size={12} />
                    Configure this project
                  </button>
                )}
            </div>
          )}

          {updateMutation.isSuccess && (
            <div className="rounded-lg border border-green-500/30 bg-green-500/10 px-3 py-2 text-sm text-green-400">
              Update successful.
            </div>
          )}
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="rounded-lg border border-[var(--color-border)] px-4 py-2 text-sm font-medium text-[var(--color-text-muted)] hover:bg-[var(--color-border)] transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={() => updateMutation.mutate()}
            disabled={updateMutation.isPending}
            className="rounded-lg bg-[var(--color-primary)] px-4 py-2 text-sm font-medium text-black transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {updateMutation.isPending ? 'Updating...' : 'Update'}
          </button>
        </div>
      </div>

      {result.container_info.compose_project && (
        <ComposeProjectConfigDialog
          containerName={result.container_info.name}
          composeProject={result.container_info.compose_project}
          open={showComposeConfig}
          onClose={() => setShowComposeConfig(false)}
        />
      )}
    </div>
  )
}
