function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label className="block text-xs font-medium text-[var(--color-text-muted)]">{label}</label>
      {children}
    </div>
  )
}

export function SchedulerConfig({
  interval,
  jitter,
  maxConcurrent,
  updateDelayDays,
  runOnStartup,
  onChange,
  onToggle,
}: {
  interval: number
  jitter: number
  maxConcurrent: number
  updateDelayDays: number
  runOnStartup: boolean
  onChange: (field: string, value: string) => void
  onToggle: (field: string) => void
}) {
  return (
    <section data-tour="settings-scheduler" className="space-y-4">
      <h3 className="text-sm font-semibold text-[var(--color-text-primary)]">Scheduler</h3>
      <div className="grid grid-cols-2 gap-4">
        <Field label="Interval (seconds)">
          <input
            type="number"
            value={interval}
            onChange={(e) => onChange('schedule_interval_seconds', e.target.value)}
            className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-primary)] focus:outline-none"
          />
        </Field>
        <Field label="Jitter (seconds)">
          <input
            type="number"
            value={jitter}
            onChange={(e) => onChange('schedule_jitter_seconds', e.target.value)}
            className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-primary)] focus:outline-none"
          />
        </Field>
        <Field label="Max concurrent checks">
          <input
            type="number"
            value={maxConcurrent}
            onChange={(e) => onChange('max_concurrent_checks', e.target.value)}
            className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-primary)] focus:outline-none"
          />
        </Field>
        <Field label="Update delay (days)">
          <input
            type="number"
            min={0}
            value={updateDelayDays}
            onChange={(e) => onChange('update_delay_days', e.target.value)}
            className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-primary)] focus:outline-none"
          />
        </Field>
      </div>
      <label className="flex items-center gap-3">
        <button
          onClick={() => onToggle('run_on_startup')}
          className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
            runOnStartup ? 'bg-[var(--color-primary)]' : 'bg-[var(--color-border-strong)]'
          }`}
        >
          <span
            className={`inline-block h-3.5 w-3.5 rounded-full bg-white transition-transform ${
              runOnStartup ? 'translate-x-[18px]' : 'translate-x-[3px]'
            }`}
          />
        </button>
        <span className="text-sm text-[var(--color-text-primary)]">Run on startup</span>
      </label>
    </section>
  )
}
