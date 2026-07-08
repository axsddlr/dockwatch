import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Shield, Loader2 } from 'lucide-react'
import { api, ApiError } from '../../api/client'
import { useDashboardStore } from '../../store/dashboardStore'

export function ScanButton({ name }: { name: string }) {
  const setScanResult = useDashboardStore((s) => s.setScanResult)
  const setScanning = useDashboardStore((s) => s.setScanning)
  const setExpandedScan = useDashboardStore((s) => s.setExpandedScan)
  const scanning = useDashboardStore((s) => s.scanningContainers[name])
  const hasScan = !!useDashboardStore((s) => s.scannedContainers[name])
  const [error, setError] = useState<string | null>(null)

  const scanMutation = useMutation({
    mutationFn: () => api.containers.scan(name),
    onMutate: () => setScanning(name, true),
    onSuccess: (data) => {
      setScanning(name, false)
      setScanResult(name, data.result)
      setExpandedScan(name)
    },
    onError: (e: Error) => {
      setScanning(name, false)
      setError(
        e instanceof ApiError && e.status === 422
          ? 'Trivy scanning is disabled. Enable it in Settings.'
          : e.message,
      )
    },
  })

  const getScanMutation = useMutation({
    mutationFn: () => api.containers.getScan(name),
    onSuccess: (data) => {
      if (data.result) {
        setScanResult(name, data.result)
        setExpandedScan(name)
      } else {
        scanMutation.mutate()
      }
    },
    onError: () => {
      scanMutation.mutate()
    },
  })

  const handleClick = () => {
    if (hasScan) {
      setExpandedScan(name)
      return
    }
    setError(null)
    setScanning(name, true)
    getScanMutation.mutate()
  }

  const busy = scanning || scanMutation.isPending || getScanMutation.isPending

  return (
    <div className="relative flex items-center gap-1.5">
      {error && <span className="text-xs text-red-400">{error}</span>}
      <button
        onClick={handleClick}
        disabled={busy}
        className="rounded-lg p-1.5 text-[var(--color-text-muted)] hover:bg-[var(--color-border)] hover:text-purple-400 transition-colors disabled:opacity-50"
        title={error ?? 'Trivy scan'}
      >
        {busy ? <Loader2 size={14} className="animate-spin" /> : <Shield size={14} />}
      </button>
    </div>
  )
}
