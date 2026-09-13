import { useState, useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { api } from '../api/client'
import { useSettings, useSaveSettings } from '../hooks/useSettings'
import { MonitoringScope } from '../components/settings/MonitoringScope'
import { TagFilters } from '../components/settings/TagFilters'
import { NotificationDelivery } from '../components/settings/NotificationDelivery'
import { NotificationRules } from '../components/settings/NotificationRules'
import { SchedulerConfig } from '../components/settings/SchedulerConfig'
import { PortainerIntegration } from '../components/settings/PortainerIntegration'
import { AgentIntegration } from '../components/settings/AgentIntegration'
import { TrivyConfig } from '../components/settings/TrivyConfig'
import { HealthConfig } from '../components/settings/HealthConfig'
import { HooksConfig } from '../components/settings/HooksConfig'
import { PruneConfig } from '../components/settings/PruneConfig'
import { SettingsActions } from '../components/settings/SettingsActions'
import { hasPermission, NoAccess } from '../components/RequireAuth'
import type { AgentConfig, DockwatchSettings, HookSettings } from '../types'

function parseCsv(v: string): string[] {
  return v
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
}

function formatCsv(arr: string[]): string {
  return arr.join(', ')
}

function cleanHooks(hooks: Record<string, HookSettings>): Record<string, HookSettings> {
  const clean: Record<string, HookSettings> = {}
  for (const [name, hook] of Object.entries(hooks)) {
    clean[name] = {
      pre_update: hook.pre_update.filter((s) => s.trim()),
      post_update: hook.post_update.filter((s) => s.trim()),
      pre_stop: hook.pre_stop.filter((s) => s.trim()),
      pre_rollback: hook.pre_rollback.filter((s) => s.trim()),
      post_rollback: hook.post_rollback.filter((s) => s.trim()),
    }
  }
  return clean
}

export function SettingsPage() {
  if (!hasPermission('manage_settings')) return <NoAccess permission="manage_settings" />
  return <SettingsPageInner />
}

function SettingsPageInner() {
  const { data, isLoading } = useSettings()
  const saveMutation = useSaveSettings()
  const [saveMessage, setSaveMessage] = useState<string | null>(null)
  const [advancedOpen, setAdvancedOpen] = useState(false)

  // Names for the ignored-containers checklist, from the last check's
  // cached results (GET, no docker churn).
  const { data: containerData } = useQuery({
    queryKey: ['containers', 'cached'],
    queryFn: () => api.containers.list(),
    staleTime: 30_000,
  })
  const containerNames = [
    ...new Set((containerData ?? []).map((r) => r.container_info.name)),
  ].sort()

  const [form, setForm] = useState({
    ignored: [] as string[],
    auto_update: [] as string[],
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
    update_delay_days: 0,
    agents: [] as AgentConfig[],
    portainer_enabled: false,
    portainer_url: '',
    portainer_api_key: '',
    portainer_environments: '',
    portainer_deploy_timeout: 120,
    trivy_enabled: false,
    trivy_binary_path: 'trivy',
    trivy_severity: 'CRITICAL, HIGH',
    trivy_scanners: 'vuln',
    trivy_timeout_seconds: 300,
    trivy_skip_db_update: false,
    trivy_cache_ttl_minutes: 60,
    health_enabled: false,
    health_interval_seconds: 60,
    health_auto_restart: false,
    health_restart_unhealthy_only: true,
    health_unhealthy_after_samples: 2,
    health_max_restarts_per_hour: 3,
    health_cooldown_seconds: 300,
    health_notify_transitions: true,
    hooks: {} as Record<string, HookSettings>,
    hook_timeout_seconds: 60,
    hook_user: '',
    hook_workdir: '',
    prune_enabled: false,
    prune_interval_hours: 24,
    prune_run_on_startup: false,
    prune_mode: 'dangling',
    prune_keep_recent_per_repository: 3,
    prune_notify: false,
    health_restart: [] as string[],
  })

  // Hydrate the form from the server only once; later refetches (e.g. on
  // window focus) must not overwrite edits the user is still making.
  const hydratedRef = useRef(false)

  useEffect(() => {
    if (data && !hydratedRef.current) {
      hydratedRef.current = true
      setForm({
        ignored: data.ignored ?? [],
        auto_update: data.auto_update ?? [],
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
        update_delay_days: data.update_delay_days ?? 0,
        agents: data.agents ?? [],
        portainer_enabled: data.portainer?.enabled ?? false,
        portainer_url: data.portainer?.url ?? '',
        portainer_api_key: data.portainer?.api_key ?? '',
        portainer_environments: formatCsv(data.portainer?.environments ?? []),
        portainer_deploy_timeout: data.portainer?.deploy_timeout ?? 120,
        trivy_enabled: data.trivy?.enabled ?? false,
        trivy_binary_path: data.trivy?.binary_path ?? 'trivy',
        trivy_severity: formatCsv(data.trivy?.severity ?? ['CRITICAL', 'HIGH']),
        trivy_scanners: formatCsv(data.trivy?.scanners ?? ['vuln']),
        trivy_timeout_seconds: data.trivy?.timeout_seconds ?? 300,
        trivy_skip_db_update: data.trivy?.skip_db_update ?? false,
        trivy_cache_ttl_minutes: data.trivy?.cache_ttl_minutes ?? 60,
        health_enabled: data.health?.enabled ?? false,
        health_interval_seconds: data.health?.interval_seconds ?? 60,
        health_auto_restart: data.health?.auto_restart ?? false,
        health_restart_unhealthy_only: data.health?.restart_unhealthy_only ?? true,
        health_unhealthy_after_samples: data.health?.unhealthy_after_samples ?? 2,
        health_max_restarts_per_hour: data.health?.max_restarts_per_hour ?? 3,
        health_cooldown_seconds: data.health?.cooldown_seconds ?? 300,
        health_notify_transitions: data.health?.notify_transitions ?? true,
        hooks: data.hooks ?? {},
        hook_timeout_seconds: data.hook_defaults?.timeout_seconds ?? 60,
        hook_user: data.hook_defaults?.user ?? '',
        hook_workdir: data.hook_defaults?.workdir ?? '',
        prune_enabled: data.prune?.enabled ?? false,
        prune_interval_hours: data.prune?.interval_hours ?? 24,
        prune_run_on_startup: data.prune?.run_on_startup ?? false,
        prune_mode: data.prune?.mode ?? 'dangling',
        prune_keep_recent_per_repository: data.prune?.keep_recent_per_repository ?? 3,
        prune_notify: data.prune?.notify ?? false,
        health_restart: data.health_restart ?? [],
      })
      if (
        data.portainer?.enabled ||
        data.trivy?.enabled ||
        data.health?.enabled ||
        data.prune?.enabled ||
        Object.keys(data.hooks ?? {}).length > 0
      ) {
        setAdvancedOpen(true)
      }
    }
  }, [data])

  const NUMERIC_FIELDS = new Set([
    'schedule_interval_seconds',
    'schedule_jitter_seconds',
    'max_concurrent_checks',
    'update_delay_days',
    'trivy_timeout_seconds',
    'trivy_cache_ttl_minutes',
    'portainer_deploy_timeout',
    'health_interval_seconds',
    'health_unhealthy_after_samples',
    'health_max_restarts_per_hour',
    'health_cooldown_seconds',
    'hook_timeout_seconds',
    'prune_interval_hours',
    'prune_keep_recent_per_repository',
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

  const handleToggleIgnored = (name: string) => {
    setForm((prev) => ({
      ...prev,
      ignored: prev.ignored.includes(name)
        ? prev.ignored.filter((n) => n !== name)
        : [...prev.ignored, name],
    }))
  }

  const handleToggleAutoUpdate = (name: string) => {
    setForm((prev) => ({
      ...prev,
      auto_update: prev.auto_update.includes(name)
        ? prev.auto_update.filter((n) => n !== name)
        : [...prev.auto_update, name],
    }))
  }

  const handleToggleHealthRestart = (name: string) => {
    setForm((prev) => ({
      ...prev,
      health_restart: prev.health_restart.includes(name)
        ? prev.health_restart.filter((n) => n !== name)
        : [...prev.health_restart, name],
    }))
  }

  const handleSave = async () => {
    setSaveMessage(null)
    const payload: Partial<DockwatchSettings> = {
      ignored: form.ignored,
      auto_update: form.auto_update,
      health_restart: form.health_restart,
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
      update_delay_days: form.update_delay_days,
      agents: form.agents,
        portainer: {
          enabled: form.portainer_enabled,
          url: form.portainer_url,
          api_key: form.portainer_api_key,
          environments: parseCsv(form.portainer_environments),
          deploy_timeout: form.portainer_deploy_timeout,
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
        health: {
          enabled: form.health_enabled,
          interval_seconds: form.health_interval_seconds,
          auto_restart: form.health_auto_restart,
          restart_unhealthy_only: form.health_restart_unhealthy_only,
          unhealthy_after_samples: form.health_unhealthy_after_samples,
          max_restarts_per_hour: form.health_max_restarts_per_hour,
          cooldown_seconds: form.health_cooldown_seconds,
          notify_transitions: form.health_notify_transitions,
        },
        hooks: cleanHooks(form.hooks),
        hook_defaults: {
          timeout_seconds: form.hook_timeout_seconds,
          user: form.hook_user,
          workdir: form.hook_workdir,
        },
        prune: {
          enabled: form.prune_enabled,
          interval_hours: form.prune_interval_hours,
          run_on_startup: form.prune_run_on_startup,
          mode: form.prune_mode,
          keep_recent_per_repository: form.prune_keep_recent_per_repository,
          notify: form.prune_notify,
        },
      }
    try {
      await saveMutation.mutateAsync(payload)
      setSaveMessage('Settings saved.')
      return true
    } catch (e) {
      setSaveMessage(e instanceof Error ? e.message : 'Save failed')
      return false
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
          ignored={form.ignored}
          autoUpdate={form.auto_update}
          healthRestart={form.health_restart}
          containerNames={containerNames}
          notifyOnly={form.notify_only}
          onToggleIgnored={handleToggleIgnored}
          onToggleAutoUpdate={handleToggleAutoUpdate}
          onToggleHealthRestart={handleToggleHealthRestart}
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
          updateDelayDays={form.update_delay_days}
          runOnStartup={form.run_on_startup}
          onChange={handleChange}
          onToggle={handleToggle}
        />

        <AgentIntegration
          agents={form.agents}
          savedAgents={data?.agents ?? []}
          onChange={(agents) => setForm((prev) => ({ ...prev, agents }))}
          onSave={handleSave}
        />

        <div className="space-y-4">
          <button
            data-tour="settings-advanced-toggle"
            onClick={() => setAdvancedOpen((prev) => !prev)}
            className="flex items-center gap-1.5 text-sm font-semibold text-[var(--color-text-primary)]"
          >
            {advancedOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
            Advanced (Portainer, Trivy, Health, Hooks, Prune)
          </button>

          {advancedOpen && (
            <div className="space-y-8 border-l-2 border-[var(--color-border)] pl-4">
              <PortainerIntegration
                enabled={form.portainer_enabled}
                url={form.portainer_url}
                apiKey={form.portainer_api_key}
                environments={form.portainer_environments}
                deployTimeout={form.portainer_deploy_timeout}
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

              <HealthConfig
                enabled={form.health_enabled}
                intervalSeconds={form.health_interval_seconds}
                autoRestart={form.health_auto_restart}
                restartUnhealthyOnly={form.health_restart_unhealthy_only}
                unhealthyAfterSamples={form.health_unhealthy_after_samples}
                maxRestartsPerHour={form.health_max_restarts_per_hour}
                cooldownSeconds={form.health_cooldown_seconds}
                notifyTransitions={form.health_notify_transitions}
                onChange={handleChange}
                onToggle={handleToggle}
              />

              <HooksConfig
                hooks={form.hooks}
                containerNames={containerNames}
                timeoutSeconds={form.hook_timeout_seconds}
                user={form.hook_user}
                workdir={form.hook_workdir}
                onChange={(hooks) => setForm((prev) => ({ ...prev, hooks }))}
                onChangeDefaults={handleChange}
              />

              <PruneConfig
                enabled={form.prune_enabled}
                intervalHours={form.prune_interval_hours}
                runOnStartup={form.prune_run_on_startup}
                mode={form.prune_mode}
                keepRecentPerRepository={form.prune_keep_recent_per_repository}
                notify={form.prune_notify}
                onChange={handleChange}
                onToggle={handleToggle}
              />
            </div>
          )}
        </div>
      </div>

      <div className="border-t border-[var(--color-border)] pt-6">
        <SettingsActions onSave={handleSave} saving={saveMutation.isPending} saveMessage={saveMessage} />
      </div>
    </div>
  )
}
