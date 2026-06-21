import { useState } from 'react'
import { useTestPortainer } from '../../hooks/useSettings'

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label className="block text-xs font-medium text-[var(--color-text-muted)]">{label}</label>
      {children}
    </div>
  )
}

export function PortainerIntegration({
  enabled,
  url,
  apiKey,
  environments,
  onChange,
  onToggle,
}: {
  enabled: boolean
  url: string
  apiKey: string
  environments: string
  onChange: (field: string, value: string) => void
  onToggle: (field: string) => void
}) {
  const [testResult, setTestResult] = useState<string | null>(null)
  const testMutation = useTestPortainer()

  return (
    <section className="space-y-4">
      <h3 className="text-sm font-semibold text-[var(--color-text-primary)]">Portainer</h3>

      <label className="flex items-center gap-3">
        <button
          onClick={() => onToggle('portainer_enabled')}
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

      <Field label="URL">
        <input
          type="text"
          value={url}
          onChange={(e) => onChange('portainer_url', e.target.value)}
          placeholder="https://portainer.example.com"
          className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] placeholder-[var(--color-text-dim)] focus:border-[var(--color-primary)] focus:outline-none"
        />
      </Field>
      <Field label="API Key">
        <input
          type="password"
          value={apiKey}
          onChange={(e) => onChange('portainer_api_key', e.target.value)}
          placeholder="ptr_..."
          className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] placeholder-[var(--color-text-dim)] focus:border-[var(--color-primary)] focus:outline-none"
        />
      </Field>
      <Field label="Environment IDs (comma-separated)">
        <input
          type="text"
          value={environments}
          onChange={(e) => onChange('portainer_environments', e.target.value)}
          placeholder="1, 2"
          className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] placeholder-[var(--color-text-dim)] focus:border-[var(--color-primary)] focus:outline-none"
        />
      </Field>

      <div className="flex items-center gap-3">
        <button
          onClick={async () => {
            setTestResult(null)
            try {
              const res = await testMutation.mutateAsync({ url, api_key: apiKey })
              setTestResult(`Connected. ${res.environments.length} environment(s) found.`)
            } catch (e) {
              setTestResult(e instanceof Error ? e.message : 'Connection failed')
            }
          }}
          disabled={testMutation.isPending || !url || !apiKey}
          className="rounded-lg border border-[var(--color-border)] px-3 py-1.5 text-xs font-medium text-[var(--color-text-muted)] hover:bg-[var(--color-border)] transition-colors disabled:opacity-50"
        >
          {testMutation.isPending ? 'Testing...' : 'Test Connection'}
        </button>
        {testResult && (
          <span className={`text-xs ${testResult.startsWith('Connected') ? 'text-green-400' : 'text-red-400'}`}>
            {testResult}
          </span>
        )}
      </div>
    </section>
  )
}
