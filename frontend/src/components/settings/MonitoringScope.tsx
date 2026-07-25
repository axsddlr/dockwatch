interface FieldProps {
  label: string
  children: React.ReactNode
}

function Field({ label, children }: FieldProps) {
  return (
    <div className="space-y-1.5">
      <label className="block text-xs font-medium text-[var(--color-text-muted)]">{label}</label>
      {children}
    </div>
  )
}

export function MonitoringScope({
  ignored,
  notifyOnly,
  onChange,
}: {
  ignored: string
  notifyOnly: string
  onChange: (field: string, value: string) => void
}) {
  return (
    <section className="space-y-4">
      <h3 className="text-sm font-semibold text-[var(--color-text-primary)]">Monitoring Scope</h3>
      <p className="text-xs text-[var(--color-text-dim)]">
        Pin or unpin containers directly from the dashboard row actions.
      </p>
      <Field label="Ignored containers (comma-separated)">
        <input
          type="text"
          value={ignored}
          onChange={(e) => onChange('ignored', e.target.value)}
          placeholder="container1, container2"
          className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] placeholder-[var(--color-text-dim)] focus:border-[var(--color-primary)] focus:outline-none"
        />
      </Field>
      <Field label="Notify-only containers (comma-separated)">
        <input
          type="text"
          value={notifyOnly}
          onChange={(e) => onChange('notify_only', e.target.value)}
          placeholder="container1, container2"
          className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] placeholder-[var(--color-text-dim)] focus:border-[var(--color-primary)] focus:outline-none"
        />
      </Field>
    </section>
  )
}
