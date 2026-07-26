import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Pin, PinOff, RefreshCw, Rocket } from 'lucide-react'
import { api } from '../../api/client'
import { hasPermission } from '../RequireAuth'
import { useDashboardStore } from '../../store/dashboardStore'
import { deriveStatus, STATUS_CONFIG, BUMP_COLORS, type UpdateResult } from '../../types'
import { UpdateDialog } from './UpdateDialog'
import { ScanButton } from './ScanButton'
import { ScanResultsPanel } from './ScanResultsPanel'

interface ContainerRowProps {
  result: UpdateResult
}

export function ContainerRow({ result }: ContainerRowProps) {
  const queryClient = useQueryClient()
  const status = deriveStatus(result)
  const cfg = STATUS_CONFIG[status]
  const [showUpdate, setShowUpdate] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const scanResult = useDashboardStore((s) => s.scannedContainers[result.container_info.name])
  const expandedScan = useDashboardStore((s) => s.expandedScan)
  const setExpandedScan = useDashboardStore((s) => s.setExpandedScan)
  const isScanOpen = expandedScan === result.container_info.name

  const pinMutation = useMutation({
    mutationFn: () =>
      status === 'PINNED'
        ? api.containers.unpin(result.container_info.name)
        : api.containers.pin(result.container_info.name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['containers'] })
    },
  })

  const singleCheckMutation = useMutation({
    mutationFn: () => api.containers.check('local'),
    onSuccess: (data) => {
      setMessage(data.length > 0 ? 'Check completed.' : 'No results.')
    },
    onError: (e: Error) => {
      setMessage(e.message)
    },
  })

  const bump = result.version_diff?.bump_type
  const canUpdate = hasPermission('update_containers')
  const canScan = hasPermission('scan_containers')
  const showUpdateBtn = status === 'OUTDATED' && canUpdate

  return (
    <div className="grid grid-cols-12 items-center gap-2 border-b border-[var(--color-border)] px-4 py-3 text-sm last:border-b-0 hover:bg-[var(--color-bg-panel-alt)]/50 transition-colors">
      <div className="col-span-3 flex items-center gap-3 min-w-0">
        <span className={`h-2 w-2 flex-shrink-0 rounded-full ${cfg.color.replace('text-', 'bg-')}`} />
        <div className="min-w-0">
          <div className="truncate font-medium text-[var(--color-text-primary)]">
            {result.container_info.name}
          </div>
          <div className="truncate text-xs text-[var(--color-text-muted)]">
            {result.container_info.image_name}
            {result.container_info.source !== 'local' && (
              <span className="ml-1.5 inline-flex items-center rounded border border-[var(--color-border)] px-1 py-px text-[10px]">
                {result.container_info.source}
              </span>
            )}
          </div>
        </div>
      </div>

      <div className="col-span-1">
        <span className={`inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium ${cfg.bg} ${cfg.color}`}>
          {cfg.label}
        </span>
      </div>

      <div className="col-span-1 truncate text-xs text-[var(--color-text-muted)]">
        {result.comparison_basis ?? '-'}
      </div>

      <div
        className="col-span-2 truncate font-mono text-xs text-[var(--color-text-primary)]"
        title={result.deployed_display ?? result.deployed_tag ?? result.deployed_version ?? undefined}
      >
        {result.deployed_display ?? result.deployed_tag ?? result.deployed_version ?? '-'}
      </div>

      <div className="col-span-3 flex items-center gap-1.5 min-w-0">
        <span
          className="truncate font-mono text-xs text-[var(--color-text-primary)]"
          title={result.latest_version ?? result.remote_tag ?? undefined}
        >
          {result.latest_version ?? result.remote_tag ?? '-'}
        </span>
        {bump && BUMP_COLORS[bump] && (
          <span className={`inline-flex rounded border px-1.5 py-px text-[10px] font-semibold ${BUMP_COLORS[bump]}`}>
            {bump}
          </span>
        )}
      </div>

      <div className="col-span-2 flex items-center justify-end gap-1">
        {message && <span className="text-xs text-green-400">{message}</span>}
        <button
          onClick={() => singleCheckMutation.mutate()}
          disabled={singleCheckMutation.isPending}
          className="rounded-lg p-1.5 text-[var(--color-text-muted)] hover:bg-[var(--color-border)] hover:text-[var(--color-text-primary)] transition-colors"
          title="Check this container"
        >
          <RefreshCw size={14} className={singleCheckMutation.isPending ? 'animate-spin' : ''} />
        </button>
        {canUpdate && (
          <button
            onClick={() => pinMutation.mutate()}
            disabled={pinMutation.isPending}
            className={`rounded-lg p-1.5 transition-colors ${
              status === 'PINNED'
                ? 'text-blue-400 hover:bg-blue-400/10'
                : 'text-[var(--color-text-muted)] hover:bg-[var(--color-border)] hover:text-[var(--color-text-primary)]'
            }`}
            title={status === 'PINNED' ? 'Unpin' : 'Pin'}
          >
            {status === 'PINNED' ? <PinOff size={14} /> : <Pin size={14} />}
          </button>
        )}
        {showUpdateBtn && (
          <button
            onClick={() => setShowUpdate(true)}
            className="rounded-lg p-1.5 text-[var(--color-primary)] hover:bg-[var(--color-primary)]/10 transition-colors"
            title="Update"
          >
            <Rocket size={14} />
          </button>
        )}
        {canScan && <ScanButton name={result.container_info.name} />}
      </div>

      {showUpdate && <UpdateDialog result={result} open={showUpdate} onClose={() => setShowUpdate(false)} />}
      {isScanOpen && scanResult && (
        <div className="col-span-12">
          <ScanResultsPanel
            result={scanResult}
            name={result.container_info.name}
            onClose={() => setExpandedScan(null)}
          />
        </div>
      )}
    </div>
  )
}
