function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label className="block text-xs font-medium text-[var(--color-text-muted)]">{label}</label>
      {children}
    </div>
  )
}

export function TagFilters({
  includeTags,
  excludeTags,
  onChange,
}: {
  includeTags: string
  excludeTags: string
  onChange: (field: string, value: string) => void
}) {
  return (
    <section data-tour="settings-tags" className="space-y-4">
      <h3 className="text-sm font-semibold text-[var(--color-text-primary)]">Tag Filters</h3>
      <Field label="Include tags (comma-separated globs)">
        <input
          type="text"
          value={includeTags}
          onChange={(e) => onChange('include_tags', e.target.value)}
          placeholder="1.*, 2.*"
          className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] placeholder-[var(--color-text-dim)] focus:border-[var(--color-primary)] focus:outline-none"
        />
      </Field>
      <Field label="Exclude tags (comma-separated globs)">
        <input
          type="text"
          value={excludeTags}
          onChange={(e) => onChange('exclude_tags', e.target.value)}
          placeholder="*-rc*, *-beta*"
          className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] placeholder-[var(--color-text-dim)] focus:border-[var(--color-primary)] focus:outline-none"
        />
      </Field>
    </section>
  )
}
