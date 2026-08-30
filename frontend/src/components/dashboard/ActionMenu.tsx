import { useEffect, useRef, useState, type ReactNode } from 'react'
import { MoreVertical } from 'lucide-react'

export function ActionMenu({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onClickOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onClickOutside)
    return () => document.removeEventListener('mousedown', onClickOutside)
  }, [open])

  return (
    <div ref={ref} className="relative">
      <button
        data-tour="action-menu"
        onClick={() => setOpen((v) => !v)}
        className={`rounded-lg p-1.5 transition-colors ${
          open
            ? 'bg-[var(--color-border)] text-[var(--color-text-primary)]'
            : 'text-[var(--color-text-muted)] hover:bg-[var(--color-border)] hover:text-[var(--color-text-primary)]'
        }`}
        title="More actions"
      >
        <MoreVertical size={14} />
      </button>
      {open && (
        <div
          className="absolute right-0 top-full z-10 mt-1 min-w-[180px] rounded-lg border border-[var(--color-border-strong)] bg-[var(--color-bg-panel)] py-1 shadow-[0_8px_30px_rgba(0,0,0,0.35)]"
          onClick={() => setOpen(false)}
        >
          {children}
        </div>
      )}
    </div>
  )
}

export function ActionMenuItem({
  onClick,
  disabled,
  danger,
  icon,
  children,
}: {
  onClick: () => void
  disabled?: boolean
  danger?: boolean
  icon: ReactNode
  children: ReactNode
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs transition-colors disabled:opacity-50 ${
        danger
          ? 'text-red-400 hover:bg-red-400/10'
          : 'text-[var(--color-text-primary)] hover:bg-[var(--color-border)]'
      }`}
    >
      {icon}
      {children}
    </button>
  )
}
