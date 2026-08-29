function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label className="block text-xs font-medium text-[var(--color-text-muted)]">{label}</label>
      {children}
    </div>
  )
}

export function TrivyConfig({
  enabled,
  binaryPath,
  severity,
  scanners,
  timeoutSeconds,
  skipDbUpdate,
  cacheTtlMinutes,
  onChange,
  onToggle,
}: {
  enabled: boolean
  binaryPath: string
  severity: string
  scanners: string
  timeoutSeconds: number
  skipDbUpdate: boolean
  cacheTtlMinutes: number
  onChange: (field: string, value: string) => void
  onToggle: (field: string) => void
}) {
  return (
    <section className="space-y-4">
      <h3 className="text-sm font-semibold text-[var(--color-text-primary)]">Trivy Scanner</h3>

      <label className="flex items-center gap-3">
        <button
          onClick={() => onToggle('trivy_enabled')}
          className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
            enabled ? 'bg-[var(--color-primary)]' : 'bg-[var(--color-border-strong)]'
          }`}
        >
          <span
            className={`inline-block h-3.5 w-3.5 rounded-full bg-white transition-transform ${
              enabled ? 'translate-x-[18px]' : 'translate-x-[3px]'
            }`}
          />
        </button>
        <span className="text-sm text-[var(--color-text-primary)]">Enabled</span>
      </label>

      <Field label="Binary path">
        <input
          type="text"
          value={binaryPath}
          onChange={(e) => onChange('trivy_binary_path', e.target.value)}
          placeholder="trivy"
          className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] placeholder-[var(--color-text-dim)] focus:border-[var(--color-primary)] focus:outline-none"
        />
      </Field>

      <div className="grid grid-cols-2 gap-4">
        <Field label="Severity (comma-separated)">
          <input
            type="text"
            value={severity}
            onChange={(e) => onChange('trivy_severity', e.target.value)}
            placeholder="CRITICAL, HIGH"
            className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] placeholder-[var(--color-text-dim)] focus:border-[var(--color-primary)] focus:outline-none"
          />
        </Field>
        <Field label="Scanners (comma-separated)">
          <input
            type="text"
            value={scanners}
            onChange={(e) => onChange('trivy_scanners', e.target.value)}
            placeholder="vuln"
            className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] placeholder-[var(--color-text-dim)] focus:border-[var(--color-primary)] focus:outline-none"
          />
        </Field>
        <Field label="Timeout (seconds)">
          <input
            type="number"
            value={timeoutSeconds}
            onChange={(e) => onChange('trivy_timeout_seconds', e.target.value)}
            className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-primary)] focus:outline-none"
          />
        </Field>
        <Field label="Cache TTL (minutes)">
          <input
            type="number"
            value={cacheTtlMinutes}
            onChange={(e) => onChange('trivy_cache_ttl_minutes', e.target.value)}
            className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-primary)] focus:outline-none"
          />
        </Field>
      </div>

      <label className="flex items-center gap-3">
        <button
          onClick={() => onToggle('trivy_skip_db_update')}
          className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
            skipDbUpdate ? 'bg-[var(--color-primary)]' : 'bg-[var(--color-border-strong)]'
          }`}
        >
          <span
            className={`inline-block h-3.5 w-3.5 rounded-full bg-white transition-transform ${
              skipDbUpdate ? 'translate-x-[18px]' : 'translate-x-[3px]'
            }`}
          />
        </button>
        <span className="text-sm text-[var(--color-text-primary)]">Skip DB update</span>
      </label>
    </section>
  )
}
