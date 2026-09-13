import { useState } from 'react'
import { useRunHealthCheck } from '../../hooks/useHealth'
import { refreshDashboardResults } from '../../store/dashboardStore'

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

export function HealthConfig({
  enabled,
  intervalSeconds,
  autoRestart,
  restartUnhealthyOnly,
  unhealthyAfterSamples,
  maxRestartsPerHour,
  cooldownSeconds,
  notifyTransitions,
  onChange,
  onToggle,
}: {
  enabled: boolean
  intervalSeconds: number
  autoRestart: boolean
  restartUnhealthyOnly: boolean
  unhealthyAfterSamples: number
  maxRestartsPerHour: number
  cooldownSeconds: number
  notifyTransitions: boolean
  onChange: (field: string, value: string) => void
  onToggle: (field: string) => void
}) {
  const runCheck = useRunHealthCheck()
  const [checkMessage, setCheckMessage] = useState<string | null>(null)

  const handleRunCheck = async () => {
    setCheckMessage(null)
    try {
      const result = await runCheck.mutateAsync()
      setCheckMessage(`Health check complete (${result.states.length} container(s)).`)
      try {
        await refreshDashboardResults()
      } catch {
        // Best-effort: the check succeeded even if the follow-up refresh failed.
      }
    } catch (e) {
      setCheckMessage(e instanceof Error ? e.message : 'Health check failed')
    }
  }

  return (
    <section className="space-y-4">
      <h3 className="text-sm font-semibold text-[var(--color-text-primary)]">Container Health</h3>
      <p className="text-xs text-[var(--color-text-dim)]">
        Periodically sample container health and optionally auto-restart unhealthy or exited
        containers. Auto-restart applies only to containers you opt in below (Monitoring Scope).
      </p>

      <div className="flex items-center gap-3">
        <button
          onClick={handleRunCheck}
          disabled={runCheck.isPending}
          className="inline-flex items-center gap-2 rounded-lg border border-[var(--color-border)] px-3 py-1.5 text-xs font-medium text-[var(--color-text-muted)] hover:bg-[var(--color-border)] hover:text-[var(--color-text-primary)] transition-colors disabled:opacity-50"
        >
          {runCheck.isPending ? 'Checking...' : 'Run health check'}
        </button>
        {checkMessage && <span className="text-xs text-[var(--color-text-muted)]">{checkMessage}</span>}
      </div>

      <Toggle checked={enabled} onToggle={() => onToggle('health_enabled')} label="Enabled" />

      <Field label="Check interval (seconds)">
        <input
          type="number"
          min={10}
          value={intervalSeconds}
          onChange={(e) => onChange('health_interval_seconds', e.target.value)}
          className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-primary)] focus:outline-none"
        />
      </Field>

      <Toggle
        checked={autoRestart}
        onToggle={() => onToggle('health_auto_restart')}
        label="Auto-restart unhealthy containers"
      />

      <Toggle
        checked={restartUnhealthyOnly}
        onToggle={() => onToggle('health_restart_unhealthy_only')}
        label="Restart unhealthy only (off also restarts exited containers)"
      />

      <div className="grid grid-cols-2 gap-4">
        <Field label="Unhealthy after samples">
          <input
            type="number"
            min={1}
            value={unhealthyAfterSamples}
            onChange={(e) => onChange('health_unhealthy_after_samples', e.target.value)}
            className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-primary)] focus:outline-none"
          />
        </Field>
        <Field label="Max restarts per hour">
          <input
            type="number"
            min={0}
            value={maxRestartsPerHour}
            onChange={(e) => onChange('health_max_restarts_per_hour', e.target.value)}
            className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-primary)] focus:outline-none"
          />
        </Field>
        <Field label="Restart cooldown (seconds)">
          <input
            type="number"
            min={0}
            value={cooldownSeconds}
            onChange={(e) => onChange('health_cooldown_seconds', e.target.value)}
            className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-primary)] focus:outline-none"
          />
        </Field>
      </div>

      <Toggle
        checked={notifyTransitions}
        onToggle={() => onToggle('health_notify_transitions')}
        label="Notify on health transitions"
      />
    </section>
  )
}
