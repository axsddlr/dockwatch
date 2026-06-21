import { AlertTriangle, X } from 'lucide-react'
import { useState } from 'react'

interface ErrorBannerProps {
  message: string | null
  onDismiss: () => void
}

export function ErrorBanner({ message, onDismiss }: ErrorBannerProps) {
  const [dismissed, setDismissed] = useState(false)

  if (!message || dismissed) return null

  return (
    <div className="flex items-center gap-3 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400">
      <AlertTriangle size={16} className="flex-shrink-0" />
      <span className="flex-1">{message}</span>
      <button
        onClick={() => { setDismissed(true); onDismiss() }}
        className="rounded p-0.5 hover:bg-red-500/20 transition-colors"
      >
        <X size={14} />
      </button>
    </div>
  )
}
