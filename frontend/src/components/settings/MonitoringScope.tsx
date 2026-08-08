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

function ContainerChecklist({
  containerNames,
  checked,
  onToggle,
  helpText,
}: {
  containerNames: string[]
  checked: string[]
  onToggle: (name: string) => void
  helpText: string
}) {
  // A checked name may be absent from the discovered list (e.g. ignored
  // containers are excluded from check results) — union them so it can
  // always be unchecked again.
  const allNames = [...new Set([...containerNames, ...checked])].sort()

  return (
    <>
      {allNames.length === 0 ? (
        <p className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-xs text-[var(--color-text-dim)]">
          No containers discovered yet — run a check from the dashboard first.
        </p>
      ) : (
        <div className="max-h-48 space-y-1 overflow-y-auto rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] p-2">
          {allNames.map((name) => {
            const discovered = containerNames.includes(name)
            return (
              <label
                key={name}
                className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 text-sm text-[var(--color-text-primary)] hover:bg-[var(--color-bg-panel)]"
              >
                <input
                  type="checkbox"
                  checked={checked.includes(name)}
                  onChange={() => onToggle(name)}
                  className="accent-[var(--color-primary)]"
                />
                <span className="truncate">{name}</span>
                {!discovered && (
                  <span className="ml-auto shrink-0 text-[10px] text-[var(--color-text-dim)]">
                    not in last check
                  </span>
                )}
              </label>
            )
          })}
        </div>
      )}
      <p className="text-[10px] text-[var(--color-text-dim)]">{helpText}</p>
    </>
  )
}

export function MonitoringScope({
  ignored,
  autoUpdate,
  containerNames,
  notifyOnly,
  onToggleIgnored,
  onToggleAutoUpdate,
  onChange,
}: {
  ignored: string[]
  autoUpdate: string[]
  containerNames: string[]
  notifyOnly: string
  onToggleIgnored: (name: string) => void
  onToggleAutoUpdate: (name: string) => void
  onChange: (field: string, value: string) => void
}) {
  return (
    <section className="space-y-4">
      <h3 className="text-sm font-semibold text-[var(--color-text-primary)]">Monitoring Scope</h3>
      <p className="text-xs text-[var(--color-text-dim)]">
        Pin or unpin containers directly from the dashboard row actions.
      </p>
      <Field label="Ignored containers">
        <ContainerChecklist
          containerNames={containerNames}
          checked={ignored}
          onToggle={onToggleIgnored}
          helpText="Checked containers are skipped during update checks. Applies on save."
        />
      </Field>
      <Field label="Auto-update containers">
        <ContainerChecklist
          containerNames={containerNames}
          checked={autoUpdate}
          onToggle={onToggleAutoUpdate}
          helpText="Checked containers update automatically, without a click, whenever a scheduled check finds them outdated. Off by default — everything else still requires manual approval."
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
