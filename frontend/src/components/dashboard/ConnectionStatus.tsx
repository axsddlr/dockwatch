import { Wifi, WifiOff } from 'lucide-react'
import { useDashboardStore } from '../../store/dashboardStore'

export function ConnectionStatus() {
  const connected = useDashboardStore((s) => s.wsConnected)
  const lastChecked = useDashboardStore((s) => s.lastChecked)

  return (
    <div className="flex items-center gap-2 text-xs text-[var(--color-text-muted)]">
      {connected ? (
        <Wifi size={12} className="text-green-400" />
      ) : (
        <WifiOff size={12} className="text-red-400" />
      )}
      <span>{connected ? 'Connected' : 'Disconnected'}</span>
      {lastChecked && (
        <span className="text-[var(--color-text-dim)]">
          · Last check: {new Date(lastChecked).toLocaleTimeString()}
        </span>
      )}
    </div>
  )
}
