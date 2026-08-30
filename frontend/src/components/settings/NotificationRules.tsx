export function NotificationRules({
  notifyOn,
  firstCheckNotify,
  onChange,
  onToggle,
}: {
  notifyOn: string
  firstCheckNotify: boolean
  onChange: (field: string, value: string) => void
  onToggle: (field: string) => void
}) {
  return (
    <section data-tour="settings-notify-rules" className="space-y-4">
      <h3 className="text-sm font-semibold text-[var(--color-text-primary)]">Notification Rules</h3>

      <div className="space-y-1.5">
        <label className="block text-xs font-medium text-[var(--color-text-muted)]">Notify on events</label>
        <input
          type="text"
          value={notifyOn}
          onChange={(e) => onChange('notify_on', e.target.value)}
          placeholder="new, update"
          className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] placeholder-[var(--color-text-dim)] focus:border-[var(--color-primary)] focus:outline-none"
        />
      </div>

      <label className="flex items-center gap-3">
        <button
          onClick={() => onToggle('first_check_notify')}
          className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
            firstCheckNotify ? 'bg-[var(--color-primary)]' : 'bg-[var(--color-border-strong)]'
          }`}
        >
          <span
            className={`inline-block h-3.5 w-3.5 rounded-full bg-white transition-transform ${
              firstCheckNotify ? 'translate-x-[18px]' : 'translate-x-[3px]'
            }`}
          />
        </button>
        <span className="text-sm text-[var(--color-text-primary)]">Notify on first check</span>
      </label>
    </section>
  )
}
