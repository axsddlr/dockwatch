import { useState, useEffect, useRef } from 'react'
import { useSettings, useSaveSettings } from '../hooks/useSettings'
import { MonitoringScope } from '../components/settings/MonitoringScope'
import { TagFilters } from '../components/settings/TagFilters'
import { NotificationDelivery } from '../components/settings/NotificationDelivery'
import { NotificationRules } from '../components/settings/NotificationRules'
import { SchedulerConfig } from '../components/settings/SchedulerConfig'
import { PortainerIntegration } from '../components/settings/PortainerIntegration'
import { TrivyConfig } from '../components/settings/TrivyConfig'
import { SettingsActions } from '../components/settings/SettingsActions'
import type { DockwatchSettings } from '../types'

function parseCsv(v: string): string[] {
  return v
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
}

function formatCsv(arr: string[]): string {
  return arr.join(', ')
}

export function SettingsPage() {
  const { data, isLoading } = useSettings()
  const saveMutation = useSaveSettings()
  const [saveMessage, setSaveMessage] = useState<string | null>(null)

  const [form, setForm] = useState({
    pinned: '',
    ignored: '',
    notify_only: '',
    include_tags: '',
    exclude_tags: '',
    notify_on: '',
    first_check_notify: false,
    webhook_url: '',
    discord_webhook: '',
    ntfy_url: '',
    schedule_interval_seconds: 300,
    schedule_jitter_seconds: 30,
    run_on_startup: true,
    max_concurrent_checks: 5,
    portainer_enabled: false,
    portainer_url: '',
    portainer_api_key: '',
    portainer_environments: '',
    trivy_enabled: false,
    trivy_binary_path: 'trivy',
    trivy_severity: 'CRITICAL, HIGH',
    trivy_scanners: 'vuln',
    trivy_timeout_seconds: 300,
    trivy_skip_db_update: false,
    trivy_cache_ttl_minutes: 60,
  })

  // Hydrate the form from the server only once; later refetches (e.g. on
  // window focus) must not overwrite edits the user is still making.
  const hydratedRef = useRef(false)

  useEffect(() => {
    if (data && !hydratedRef.current) {
      hydratedRef.current = true
      setForm({
        pinned: formatCsv(data.pinned ?? []),
        ignored: formatCsv(data.ignored ?? []),
        notify_only: formatCsv(data.notify_only ?? []),
        include_tags: formatCsv(data.include_tags ?? []),
        exclude_tags: formatCsv(data.exclude_tags ?? []),
        notify_on: formatCsv(data.notify_on ?? []),
        first_check_notify: data.first_check_notify ?? false,
        webhook_url: data.webhook_url ?? '',
        discord_webhook: data.discord_webhook ?? '',
        ntfy_url: data.ntfy_url ?? '',
        schedule_interval_seconds: data.schedule_interval_seconds ?? 300,
        schedule_jitter_seconds: data.schedule_jitter_seconds ?? 30,
        run_on_startup: data.run_on_startup ?? true,
        max_concurrent_checks: data.max_concurrent_checks ?? 5,
        portainer_enabled: data.portainer?.enabled ?? false,
        portainer_url: data.portainer?.url ?? '',
        portainer_api_key: data.portainer?.api_key ?? '',
        portainer_environments: formatCsv(data.portainer?.environments ?? []),
        trivy_enabled: data.trivy?.enabled ?? false,
        trivy_binary_path: data.trivy?.binary_path ?? 'trivy',
        trivy_severity: formatCsv(data.trivy?.severity ?? ['CRITICAL', 'HIGH']),
        trivy_scanners: formatCsv(data.trivy?.scanners ?? ['vuln']),
        trivy_timeout_seconds: data.trivy?.timeout_seconds ?? 300,
        trivy_skip_db_update: data.trivy?.skip_db_update ?? false,
        trivy_cache_ttl_minutes: data.trivy?.cache_ttl_minutes ?? 60,
      })
    }
  }, [data])

  const NUMERIC_FIELDS = new Set([
    'schedule_interval_seconds',
    'schedule_jitter_seconds',
    'max_concurrent_checks',
    'trivy_timeout_seconds',
    'trivy_cache_ttl_minutes',
  ])

  const handleChange = (field: string, value: string) => {
    if (NUMERIC_FIELDS.has(field)) {
      // Keep the field editable while the user is mid-edit (e.g. clearing
      // it to type a new value), but never store a NaN/non-numeric value —
      // that would get JSON.stringify'd as a string and sent to a backend
      // field typed as int.
      if (value.trim() === '') return
      const parsed = Number(value)
      if (!Number.isFinite(parsed)) return
      setForm((prev) => ({ ...prev, [field]: parsed }))
      return
    }
    setForm((prev) => ({ ...prev, [field]: value }))
  }

  const handleToggle = (field: string) => {
    setForm((prev) => ({ ...prev, [field]: !(prev as Record<string, unknown>)[field] }))
  }

  const handleSave = async () => {
    setSaveMessage(null)
    const payload: Partial<DockwatchSettings> = {
      pinned: parseCsv(form.pinned),
      ignored: parseCsv(form.ignored),
      notify_only: parseCsv(form.notify_only),
      include_tags: parseCsv(form.include_tags),
      exclude_tags: parseCsv(form.exclude_tags),
      notify_on: parseCsv(form.notify_on),
      first_check_notify: form.first_check_notify,
      webhook_url: form.webhook_url,
      discord_webhook: form.discord_webhook,
      ntfy_url: form.ntfy_url,
      schedule_interval_seconds: form.schedule_interval_seconds,
      schedule_jitter_seconds: form.schedule_jitter_seconds,
      run_on_startup: form.run_on_startup,
      max_concurrent_checks: form.max_concurrent_checks,
        portainer: {
          enabled: form.portainer_enabled,
          url: form.portainer_url,
          api_key: form.portainer_api_key,
          environments: parseCsv(form.portainer_environments),
        },
        trivy: {
          enabled: form.trivy_enabled,
          binary_path: form.trivy_binary_path,
          severity: parseCsv(form.trivy_severity),
          scanners: parseCsv(form.trivy_scanners),
          timeout_seconds: form.trivy_timeout_seconds,
          skip_db_update: form.trivy_skip_db_update,
          cache_ttl_minutes: form.trivy_cache_ttl_minutes,
        },
      }
    try {
      await saveMutation.mutateAsync(payload)
      setSaveMessage('Settings saved.')
    } catch (e) {
      setSaveMessage(e instanceof Error ? e.message : 'Save failed')
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16 text-sm text-[var(--color-text-muted)]">
        Loading settings...
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <h1 className="text-lg font-semibold text-[var(--color-text-primary)]">Settings</h1>

      <div className="max-w-2xl space-y-8">
        <MonitoringScope
          pinned={form.pinned}
          ignored={form.ignored}
          notifyOnly={form.notify_only}
          onChange={handleChange}
        />

        <TagFilters
          includeTags={form.include_tags}
          excludeTags={form.exclude_tags}
          onChange={handleChange}
        />

        <NotificationDelivery
          webhookUrl={form.webhook_url}
          discordWebhook={form.discord_webhook}
          ntfyUrl={form.ntfy_url}
          onChange={handleChange}
        />

        <NotificationRules
          notifyOn={form.notify_on}
          firstCheckNotify={form.first_check_notify}
          onChange={handleChange}
          onToggle={handleToggle}
        />

        <SchedulerConfig
          interval={form.schedule_interval_seconds}
          jitter={form.schedule_jitter_seconds}
          maxConcurrent={form.max_concurrent_checks}
          runOnStartup={form.run_on_startup}
          onChange={handleChange}
          onToggle={handleToggle}
        />

        <PortainerIntegration
          enabled={form.portainer_enabled}
          url={form.portainer_url}
          apiKey={form.portainer_api_key}
          environments={form.portainer_environments}
          onChange={handleChange}
          onToggle={handleToggle}
        />

        <TrivyConfig
          enabled={form.trivy_enabled}
          binaryPath={form.trivy_binary_path}
          severity={form.trivy_severity}
          scanners={form.trivy_scanners}
          timeoutSeconds={form.trivy_timeout_seconds}
          skipDbUpdate={form.trivy_skip_db_update}
          cacheTtlMinutes={form.trivy_cache_ttl_minutes}
          onChange={handleChange}
          onToggle={handleToggle}
        />
      </div>

      <div className="border-t border-[var(--color-border)] pt-6">
        <SettingsActions onSave={handleSave} saving={saveMutation.isPending} saveMessage={saveMessage} />
      </div>
    </div>
  )
}
