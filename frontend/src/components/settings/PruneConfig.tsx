function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label className="block text-xs font-medium text-[var(--color-text-muted)]">{label}</label>
      {children}
    </div>
  )
}

function Toggle({ checked, onToggle, label }: { checked: boolean; onToggle: () => void; label: string }) {
  return (
    <label className="flex items-center gap-3">
      <button
        onClick={onToggle}
        className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
          checked ? 'bg-[var(--color-primary)]' : 'bg-[var(--color-border-strong)]'
        }`}
      >
        <span
          className={`inline-block h-3.5 w-3.5 rounded-full bg-white transition-transform ${
            checked ? 'translate-x-[18px]' : 'translate-x-[3px]'
          }`}
        />
      </button>
      <span className="text-sm text-[var(--color-text-primary)]">{label}</span>
    </label>
  )
}

export function PruneConfig({
  enabled,
  intervalHours,
  runOnStartup,
  mode,
  keepRecentPerRepository,
  notify,
  onChange,
  onToggle,
}: {
  enabled: boolean
  intervalHours: number
  runOnStartup: boolean
  mode: string
  keepRecentPerRepository: number
  notify: boolean
  onChange: (field: string, value: string) => void
  onToggle: (field: string) => void
}) {
  return (
    <section className="space-y-4">
      <h3 className="text-sm font-semibold text-[var(--color-text-primary)]">Image Pruning</h3>
      <p className="text-xs text-[var(--color-text-dim)]">
        Remove dangling or unused images on a schedule. The retention guard always keeps the
        newest images per repository.
      </p>

      <Toggle checked={enabled} onToggle={() => onToggle('prune_enabled')} label="Enabled" />

      <div className="grid grid-cols-2 gap-4">
        <Field label="Interval (hours)">
          <input
            type="number"
            min={1}
            value={intervalHours}
            onChange={(e) => onChange('prune_interval_hours', e.target.value)}
            className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-primary)] focus:outline-none"
          />
        </Field>
        <Field label="Keep recent per repository (0 disables)">
          <input
            type="number"
            min={0}
            value={keepRecentPerRepository}
            onChange={(e) => onChange('prune_keep_recent_per_repository', e.target.value)}
            className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-primary)] focus:outline-none"
          />
        </Field>
      </div>

      <Field label="Mode">
        <select
          value={mode}
          onChange={(e) => onChange('prune_mode', e.target.value)}
          className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-primary)] focus:outline-none"
        >
          <option value="dangling">Dangling only</option>
          <option value="unused">Unused (dangling + unreferenced)</option>
        </select>
      </Field>

      <Toggle checked={runOnStartup} onToggle={() => onToggle('prune_run_on_startup')} label="Run on startup" />
      <Toggle checked={notify} onToggle={() => onToggle('prune_notify')} label="Notify after pruning" />
    </section>
  )
}
