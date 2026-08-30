import { Check } from 'lucide-react'

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
  const allChecked = allNames.length > 0 && allNames.every((n) => checked.includes(n))

  const toggleAll = () => {
    if (allChecked) {
      checked.forEach((n) => onToggle(n))
    } else {
      allNames.filter((n) => !checked.includes(n)).forEach((n) => onToggle(n))
    }
  }

  return (
    <div>
      {allNames.length === 0 ? (
        <p className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-xs text-[var(--color-text-dim)]">
          No containers discovered yet — run a check from the dashboard first.
        </p>
      ) : (
        <div className="overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-input)]">
          <div className="flex items-center justify-between gap-2 border-b border-[var(--color-border)] bg-[var(--color-bg-panel)]/60 px-3 py-2">
            <span className="text-xs font-medium text-[var(--color-text-muted)]">
              {checked.length} of {allNames.length} selected
            </span>
            <button
              type="button"
              onClick={toggleAll}
              className="text-xs font-medium text-[var(--color-primary)] transition-opacity hover:opacity-80"
            >
              {allChecked ? 'Clear all' : 'Select all'}
            </button>
          </div>
          <div className="max-h-48 space-y-0.5 overflow-y-auto p-1.5">
            {allNames.map((name) => {
              const isChecked = checked.includes(name)
              const discovered = containerNames.includes(name)
              return (
                <button
                  key={name}
                  type="button"
                  onClick={() => onToggle(name)}
                  aria-pressed={isChecked}
                  className={`flex w-full items-center gap-2.5 rounded-lg border px-2.5 py-2 text-sm transition-colors ${
                    isChecked
                      ? 'border-[var(--color-primary)]/30 bg-[var(--color-primary)]/10 text-[var(--color-text-primary)]'
                      : 'border-transparent text-[var(--color-text-muted)] hover:bg-[var(--color-bg-panel)] hover:text-[var(--color-text-primary)]'
                  }`}
                >
                  <span
                    className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-[5px] border transition-colors ${
                      isChecked
                        ? 'border-[var(--color-primary)] bg-[var(--color-primary)] text-white'
                        : 'border-[var(--color-border)] bg-[var(--color-bg-panel)]'
                    }`}
                  >
                    {isChecked && <Check size={12} strokeWidth={3} />}
                  </span>
                  <span className="truncate">{name}</span>
                  {!discovered && (
                    <span className="ml-auto shrink-0 text-[10px] text-[var(--color-text-dim)]">
                      not in last check
                    </span>
                  )}
                </button>
              )
            })}
          </div>
        </div>
      )}
      <p className="mt-1.5 text-[10px] text-[var(--color-text-dim)]">{helpText}</p>
    </div>
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
    <section data-tour="settings-monitoring" className="space-y-4">
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
