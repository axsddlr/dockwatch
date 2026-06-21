import { useMutation } from '@tanstack/react-query'
import { Shield, ShieldCheck, Loader2 } from 'lucide-react'
import { api } from '../../api/client'
import { useDashboardStore } from '../../store/dashboardStore'

export function ScanButton({ name }: { name: string }) {
  const setScanResult = useDashboardStore((s) => s.setScanResult)
  const setScanning = useDashboardStore((s) => s.setScanning)
  const setExpandedScan = useDashboardStore((s) => s.setExpandedScan)
  const scanning = useDashboardStore((s) => s.scanningContainers[name])
  const hasScan = !!useDashboardStore((s) => s.scannedContainers[name])

  const scanMutation = useMutation({
    mutationFn: () => api.containers.scan(name),
    onMutate: () => setScanning(name, true),
    onSuccess: (data) => {
      setScanning(name, false)
      setScanResult(name, data.result)
      setExpandedScan(name)
    },
    onError: () => {
      setScanning(name, false)
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
    setScanning(name, true)
    getScanMutation.mutate()
  }

  return (
    <button
      onClick={handleClick}
      disabled={scanning || scanMutation.isPending || getScanMutation.isPending}
      className="rounded-lg p-1.5 text-[var(--color-text-muted)] hover:bg-[var(--color-border)] hover:text-purple-400 transition-colors disabled:opacity-50"
      title="Trivy scan"
    >
      {scanning || scanMutation.isPending || getScanMutation.isPending ? (
        <Loader2 size={14} className="animate-spin" />
      ) : (
        <Shield size={14} />
      )}
    </button>
  )
}
